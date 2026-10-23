"""Durable, bounded Team practice queue. Membership never grants opponent source access."""
import json
import uuid

from .account_database import require_writer, transaction, validate_service_connection
from .official_service import snapshot_source
from .artifact_compat import artifact_current
from .team_service import TeamConflict, TeamNotFound, TeamPermissionDenied

PENDING = ('QUEUED', 'DISPATCHING', 'RUNNING')


class Scrimmages:
    def __init__(self, auth, db, writer, store, registry):
        validate_service_connection(db, writer)
        self.auth, self.db, self.writer = auth, db, writer
        self.store, self.registry = store, registry

    def member(self, actor, *, active=False):
        user = self.auth.require_actor(actor, player_only=True, touch=False)
        row = self.db.execute("""SELECT t.*,m.team_role FROM team_memberships m
            JOIN teams t ON t.id=m.team_id WHERE m.user_id=? AND m.left_at IS NULL""", (user['id'],)).fetchone()
        if not row or (active and row['status'] != 'ACTIVE'):
            raise TeamPermissionDenied('Active Team membership required')
        return user, row

    def frozen(self, team_id, game_id):
        team = self.db.execute("SELECT * FROM teams WHERE id=? AND status='ACTIVE'", (team_id,)).fetchone()
        row = self.db.execute("""SELECT a.bot_id,a.game_id,s.source_sha256 FROM team_game_bots a
            JOIN submission_ownership o ON o.bot_id=a.bot_id AND o.team_id=a.team_id AND o.game_id=a.game_id
            JOIN official_source_attestations s ON s.bot_id=a.bot_id WHERE a.team_id=? AND a.game_id=?""", (team_id,game_id)).fetchone()
        if row and self.db.execute("SELECT 1 FROM submission_archives WHERE bot_id=?", (row['bot_id'],)).fetchone():
            raise TeamConflict('Active Bot has been archived')
        bot = self.store.get_bot(row['bot_id']) if row else None
        if (not team or not bot or bot.get('team_id') != team_id or bot.get('game_id') != game_id
            or not artifact_current(self.store, bot) or bot.get('execution_backend') != 'sandbox'
            or not bot.get('artifact_id') or not bot.get('artifact_digest')
            or snapshot_source(self.store, row, bot) != row['source_sha256']):
            raise TeamConflict('Hai đội cần bot đại diện đã biên dịch bằng Sandbox hiện tại. Hãy nộp lại bot cũ và chọn lại.')
        return {'team_id':team_id, 'team_name_snapshot':team['display_name'], 'game_id':game_id,
                'bot_id':bot['id'], 'bot_name':bot['name'], 'language':bot['language'],
                'artifact_id':bot['artifact_id'], 'artifact_digest':bot['artifact_digest']}

    def opponents(self, actor, game_id):
        _, team = self.member(actor, active=True)
        if game_id not in self.registry.ids():
            raise ValueError('Game is not installed')
        result = []
        for row in self.db.execute("SELECT id,display_name FROM teams WHERE status='ACTIVE' AND id!=? ORDER BY display_name", (team['id'],)):
            try:
                slot = self.frozen(row['id'], game_id)
            except TeamConflict:
                continue
            result.append({'id':row['id'], 'display_name':row['display_name'], 'bot_name':slot['bot_name'], 'language':slot['language']})
        return result

    def public(self, row):
        plan = json.loads(row['plan_json'])
        return {**{key:row[key] for key in ('id','game_id','status','created_at','updated_at','match_id','status_reason')},
                'teams':{side:{key:slot[key] for key in ('team_id','team_name_snapshot','bot_name','language')} for side,slot in plan['slots'].items()},
                'rules':plan['rules_snapshot'], 'result':json.loads(row['outcome_json']) if row['outcome_json'] else None}

    def list(self, actor, *, admin=False):
        if admin:
            self.auth.require_actor(actor, admin=True, touch=False)
            rows = self.db.execute("SELECT * FROM scrimmage_requests ORDER BY created_at DESC,id DESC LIMIT 200").fetchall()
        else:
            try:
                _, team = self.member(actor)
            except TeamPermissionDenied:
                return []
            rows = self.db.execute("""SELECT * FROM scrimmage_requests WHERE team_a_id=? OR team_b_id=?
                ORDER BY created_at DESC,id DESC LIMIT 200""", (team['id'],team['id'])).fetchall()
        return [self.public(row) for row in rows]

    def detail(self, actor, request_id, *, admin=False):
        row = self.db.execute("SELECT * FROM scrimmage_requests WHERE id=?", (request_id,)).fetchone()
        if admin:
            self.auth.require_actor(actor, admin=True, touch=False)
        else:
            _, team = self.member(actor)
            if row and team['id'] not in (row['team_a_id'],row['team_b_id']):
                row = None
        if not row:
            raise TeamNotFound('Scrimmage not found')
        return row

    def create(self, actor, game_id, opponent_id):
        require_writer(self.writer, self.writer.path.parent)
        with transaction(self.db):
            now = self.auth._now()
            user, mine = self.member(actor, active=True)
            if mine['id'] == opponent_id:
                raise ValueError('Choose another Team')
            if game_id not in self.registry.ids():
                raise ValueError('Game is not installed')
            count = self.db.execute("""SELECT count(*) FROM scrimmage_requests WHERE team_a_id=?
                AND status IN ('QUEUED','DISPATCHING','RUNNING')""", (mine['id'],)).fetchone()[0]
            if count >= 3:
                raise TeamConflict('Your Team already has three pending practice matches')
            if self.db.execute("""SELECT 1 FROM scrimmage_requests WHERE game_id=? AND team_a_id=? AND team_b_id=?
                AND status IN ('QUEUED','DISPATCHING','RUNNING')""", (game_id,mine['id'],opponent_id)).fetchone():
                raise TeamConflict('This challenge is already pending')
            # Keep the legacy challenge API, but do not interfere with a Team
            # that has opted into the new exclusive matchmaking flow.
            if self.db.execute("""SELECT 1 FROM matchmaking_searches s LEFT JOIN scrimmage_requests r ON r.id=s.request_id
                WHERE s.team_id IN (?,?) AND (s.status='SEARCHING' OR (s.status='MATCHED' AND r.status IN ('QUEUED','DISPATCHING','RUNNING')))""", (mine['id'],opponent_id)).fetchone():
                raise TeamConflict('A Team is already matchmaking')
            request_id = self.enqueue(user['id'], mine['id'], opponent_id, game_id, now)
        return self.public(self.detail(actor,request_id))

    def enqueue(self, user_id, team_a, team_b, game_id, now):
        """Called within the caller's serialized writer transaction."""
        if not self.db.in_transaction:
            raise RuntimeError('Enqueue requires the matchmaking transaction')
        if self.db.execute("SELECT count(*) FROM scrimmage_requests WHERE status='QUEUED'").fetchone()[0] >= 100:
            raise TeamConflict('Hàng đợi đấu luyện đã đầy. Hãy thử lại sau.')
        request_id = uuid.uuid4().hex
        plan = {'id':request_id,'game_id':game_id,
                'rules_snapshot':self.registry.get(game_id).validate_rules(self.store.get_rules(game_id)),
                'slots':{'A':self.frozen(team_a,game_id), 'B':self.frozen(team_b,game_id)}}
        self.db.execute("""INSERT INTO scrimmage_requests
            (id,requested_by,team_a_id,team_b_id,game_id,status,created_at,updated_at,plan_json)
            VALUES (?,?,?,?,?,'QUEUED',?,?,?)""", (request_id,user_id,team_a,team_b,game_id,now,now,json.dumps(plan)))
        self.db.execute("""INSERT INTO audit_events(occurred_at,actor_user_id,action,target_type,target_id,details_json)
            VALUES (?,?,'SCRIMMAGE_REQUESTED','scrimmage',?,'{}')""", (now,user_id,request_id))
        return request_id

    def cancel(self, actor, request_id, *, admin=False):
        require_writer(self.writer, self.writer.path.parent)
        with transaction(self.db):
            row = self.detail(actor,request_id,admin=admin)
            user = self.auth.require_actor(actor, admin=admin)
            if not admin:
                _, team = self.member(actor)
                if row['team_a_id'] != team['id']:
                    raise TeamPermissionDenied('Only the challenging Team can cancel its queued request')
            if row['status'] != 'QUEUED':
                raise TeamConflict('Only queued practice matches can be cancelled')
            self.db.execute("UPDATE scrimmage_requests SET status='CANCELLED',updated_at=? WHERE id=?", (self.auth._now(),request_id))
            self.db.execute("""INSERT INTO audit_events(occurred_at,actor_user_id,action,target_type,target_id,details_json)
                VALUES (?,?,'SCRIMMAGE_CANCELLED','scrimmage',?,'{}')""", (self.auth._now(),user['id'],request_id))
        return self.public(self.detail(actor,request_id,admin=admin))

    def claim(self):
        require_writer(self.writer, self.writer.path.parent)
        with transaction(self.db):
            row = self.db.execute("SELECT * FROM scrimmage_requests WHERE status='QUEUED' ORDER BY created_at,id LIMIT 1").fetchone()
            if not row:
                return None
            self.db.execute("UPDATE scrimmage_requests SET status='DISPATCHING',match_id=?,updated_at=? WHERE id=?",
                            ('s'+row['id'][:15],self.auth._now(),row['id']))
            return json.loads(row['plan_json'])

    def reconcile(self, manager, *, recover=False):
        require_writer(self.writer, self.writer.path.parent)
        with transaction(self.db):
            rows = self.db.execute("SELECT * FROM scrimmage_requests WHERE status IN ('DISPATCHING','RUNNING')").fetchall()
            for row in rows:
                match = manager.get_match(row['match_id'])
                status, reason, outcome = None, None, None
                plan = json.loads(row['plan_json'])
                verified = (match and match.get('scrimmage_request_id') == row['id'] and match.get('game_id') == row['game_id']
                    and match.get('rules') == plan['rules_snapshot'] and all(match.get('bot_' + side.lower() + '_id') == slot['bot_id']
                    and match.get('player_' + side.lower() + '_id') == slot['team_id'] for side,slot in plan['slots'].items()))
                if verified and match['status'] == 'completed' and isinstance(match.get('result'),dict):
                    status, outcome = 'COMPLETED',json.dumps(match['result'])
                elif verified and match['status'] == 'interrupted':
                    status, reason = 'INTERRUPTED', (match.get('result') or {}).get('reason','EXECUTION_INTERRUPTED')
                elif recover or not verified:
                    status, reason = 'INTERRUPTED', 'UNCERTAIN_EXECUTION'
                else:
                    status = 'RUNNING'
                self.db.execute("UPDATE scrimmage_requests SET status=?,status_reason=?,outcome_json=?,updated_at=? WHERE id=?",
                                (status,reason,outcome,self.auth._now(),row['id']))

    def fail(self, request_id):
        require_writer(self.writer, self.writer.path.parent)
        with transaction(self.db):
            self.db.execute("UPDATE scrimmage_requests SET status='INTERRUPTED',status_reason='DISPATCH_FAILED',updated_at=? WHERE id=? AND status='DISPATCHING'",
                            (self.auth._now(),request_id))
