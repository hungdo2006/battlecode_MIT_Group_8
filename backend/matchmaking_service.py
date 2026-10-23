"""Opt-in FIFO matchmaking, committed atomically with frozen Scrimmage plans.

One writer transaction owns the search check, opponent claim and both updates.
The database partial unique index additionally forbids concurrent Team searches.
Searches survive reload/disconnect for five minutes; restart cancels waiting
searches explicitly. Created matches use the existing dispatcher and recovery.
"""
import uuid

from .account_database import require_writer, transaction
from .scrimmage_service import Scrimmages
from .team_service import TeamConflict, TeamNotFound, TeamPermissionDenied

SEARCH_SECONDS = 300
MAX_SEARCHES = 100


class Matchmaking(Scrimmages):
    def audit(self, now, actor_id, action, search_id):
        self.db.execute("""INSERT INTO audit_events(occurred_at,actor_user_id,action,target_type,target_id,details_json)
            VALUES (?,?,?,'matchmaking',?,'{}')""", (now,actor_id,action,search_id))

    def expire(self, now, *, restart=False):
        rows = self.db.execute("SELECT id FROM matchmaking_searches WHERE status='SEARCHING'" +
                               ("" if restart else " AND expires_at<=?"), () if restart else (now,)).fetchall()
        for row in rows:
            self.db.execute("UPDATE matchmaking_searches SET status=?,status_reason=?,updated_at=? WHERE id=?",
                            ('CANCELLED' if restart else 'EXPIRED', 'SERVER_RESTART' if restart else 'SEARCH_TIMEOUT', now,row['id']))
            self.audit(now,None,'MATCHMAKING_CANCELLED' if restart else 'MATCHMAKING_EXPIRED',row['id'])

    def maintain(self, *, restart=False):
        require_writer(self.writer,self.writer.path.parent)
        with transaction(self.db):
            self.expire(self.auth._now(),restart=restart)

    def current(self, team_id):
        return self.db.execute("""SELECT s.* FROM matchmaking_searches s
            LEFT JOIN scrimmage_requests r ON r.id=s.request_id WHERE s.team_id=?
            AND (s.status='SEARCHING' OR (s.status='MATCHED' AND r.status IN ('QUEUED','DISPATCHING','RUNNING')))
            ORDER BY s.created_at DESC,s.id DESC LIMIT 1""", (team_id,)).fetchone()

    def busy(self, team_id):
        return self.db.execute("""SELECT 1 FROM scrimmage_requests WHERE (team_a_id=? OR team_b_id=?)
            AND status IN ('QUEUED','DISPATCHING','RUNNING') LIMIT 1""", (team_id,team_id)).fetchone() is not None

    def search_public(self, row):
        if not row:
            return None
        result = {key:row[key] for key in ('id','game_id','status','created_at','expires_at','updated_at','status_reason','request_id')}
        if row['request_id']:
            request = self.db.execute('SELECT * FROM scrimmage_requests WHERE id=?',(row['request_id'],)).fetchone()
            result['request'] = self.public(request)
            result['status'] = {'QUEUED':'MATCHED','DISPATCHING':'MATCHED','RUNNING':'RUNNING',
                                'COMPLETED':'COMPLETED','CANCELLED':'CANCELLED','INTERRUPTED':'ERROR'}[request['status']]
            result['status_reason'] = request['status_reason']
        return result

    def status(self, actor, game_id):
        if game_id not in self.registry.ids():
            raise ValueError('Game is not installed')
        with transaction(self.db):
            now = self.auth._now()
            self.expire(now)
            try:
                _, team = self.member(actor)
            except TeamPermissionDenied:
                return {'search':None,'can_search':False,'reason':'Tạo hoặc tham gia đội trước khi tìm trận.',
                        'waiting_count':0,'server_time':now,'ready_bot':False}
            row = self.current(team['id'])
            if not row:
                row = self.db.execute("SELECT * FROM matchmaking_searches WHERE team_id=? AND game_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1",(team['id'],game_id)).fetchone()
            reason = ''
            ready_bot = True
            try:
                self.frozen(team['id'],game_id)
            except TeamConflict:
                ready_bot = False
                reason = 'Đội cần hoạt động và có Active Bot hợp lệ cho game này. Captain chọn bot trước khi tìm trận.'
            if self.current(team['id']) or self.busy(team['id']):
                reason = 'Đội đang tìm hoặc đang có trận đấu luyện. Hoàn tất hay hủy lượt hiện tại trước khi tìm tiếp.'
            count = self.db.execute("""SELECT count(*) FROM matchmaking_searches s JOIN teams t ON t.id=s.team_id
                WHERE s.status='SEARCHING' AND s.game_id=? AND s.team_id!=? AND t.status='ACTIVE'""", (game_id,team['id'])).fetchone()[0]
            return {'search':self.search_public(row),'can_search':not reason,'reason':reason,'waiting_count':count,'server_time':now,'ready_bot':ready_bot}

    def find(self, actor, game_id):
        require_writer(self.writer,self.writer.path.parent)
        if game_id not in self.registry.ids():
            raise ValueError('Game is not installed')
        with transaction(self.db):
            now = self.auth._now()
            self.expire(now)
            user, team = self.member(actor,active=True)
            existing = self.current(team['id'])
            if existing:
                return self.search_public(existing)  # Duplicate click / another tab.
            if self.busy(team['id']):
                raise TeamConflict('Đội đang có trận đấu luyện chưa hoàn tất.')
            self.frozen(team['id'],game_id)
            if self.db.execute("SELECT count(*) FROM matchmaking_searches WHERE status='SEARCHING'").fetchone()[0] >= MAX_SEARCHES:
                raise TeamConflict('Hàng tìm trận đã đầy. Hãy thử lại sau.')
            search_id = uuid.uuid4().hex
            self.db.execute("""INSERT INTO matchmaking_searches(id,team_id,requested_by,game_id,status,created_at,expires_at,updated_at)
                VALUES (?,?,?,?,'SEARCHING',?,?,?)""",(search_id,team['id'],user['id'],game_id,now,now+SEARCH_SECONDS,now))
            self.audit(now,user['id'],'MATCHMAKING_STARTED',search_id)
            # FIFO among valid willing Teams prevents indefinite starvation.
            candidates = self.db.execute("""SELECT * FROM matchmaking_searches WHERE status='SEARCHING'
                AND game_id=? AND team_id!=? ORDER BY created_at,id""",(game_id,team['id'])).fetchall()
            for other in candidates:
                eligible = self.db.execute("""SELECT 1 FROM team_memberships m JOIN users u ON u.id=m.user_id
                    WHERE m.team_id=? AND m.user_id=? AND m.left_at IS NULL AND u.status='ACTIVE'""",
                    (other['team_id'],other['requested_by'])).fetchone()
                try:
                    if not eligible or self.busy(other['team_id']):
                        raise TeamConflict('Search eligibility changed')
                    self.frozen(other['team_id'],game_id)
                except TeamConflict:
                    self.db.execute("UPDATE matchmaking_searches SET status='ERROR',status_reason='TEAM_NOT_READY',updated_at=? WHERE id=?",(now,other['id']))
                    self.audit(now,None,'MATCHMAKING_INVALIDATED',other['id'])
                    continue
                request_id = self.enqueue(user['id'],other['team_id'],team['id'],game_id,now)
                self.db.execute("""UPDATE matchmaking_searches SET status='MATCHED',request_id=?,updated_at=?
                    WHERE id IN (?,?) AND status='SEARCHING'""",(request_id,now,search_id,other['id']))
                self.audit(now,user['id'],'MATCHMAKING_MATCHED',search_id)
                self.audit(now,None,'MATCHMAKING_MATCHED',other['id'])
                break
            return self.search_public(self.db.execute('SELECT * FROM matchmaking_searches WHERE id=?',(search_id,)).fetchone())

    def cancel_search(self, actor, search_id):
        require_writer(self.writer,self.writer.path.parent)
        with transaction(self.db):
            now = self.auth._now()
            self.expire(now)
            user, team = self.member(actor)
            row = self.db.execute('SELECT * FROM matchmaking_searches WHERE id=? AND team_id=?',(search_id,team['id'])).fetchone()
            if not row:
                raise TeamNotFound('Search not found')
            if row['status'] in ('CANCELLED','EXPIRED','ERROR'):
                return self.search_public(row)
            if row['status'] != 'SEARCHING':
                raise TeamConflict('Trận đã được ghép. Không thể hủy tìm trận sau khi ghép.')
            self.db.execute("UPDATE matchmaking_searches SET status='CANCELLED',status_reason='USER_CANCELLED',updated_at=? WHERE id=?",(now,search_id))
            self.audit(now,user['id'],'MATCHMAKING_CANCELLED',search_id)
            return self.search_public(self.db.execute('SELECT * FROM matchmaking_searches WHERE id=?',(search_id,)).fetchone())
