"""Phase 4.2D1: durable official-match schedules and atomic bot deadlines.

No dispatcher is enabled in D1. LOCKED means two frozen Team/Game slots exist;
it does not mean a match has executed. Phase D2 may consume these snapshots.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from .account_database import require_writer, transaction
from .auth_service import AccountConflict, PermissionDenied


class OfficialNotFound(ValueError):
    pass


class OfficialConflict(AccountConflict):
    pass


def official_publication(connection, match):
    """Project a JSON match through its durable Official SQLite authority.

    Only a reconciled COMPLETED request can publish a winner. Never mutate
    Store's internal JSON objects: these projections are presentation-only.
    Used by generic Admin history/detail and the existing Official API.
    """
    request_id = match.get("official_request_id")
    if not request_id:
        return match
    result = dict(match)
    row = connection.execute("""SELECT match_id,status,status_reason,outcome_json
        FROM official_match_requests WHERE id=?""", (request_id,)).fetchone()
    if row and row["match_id"] == match.get("id"):
        if row["status"] == "COMPLETED" and row["outcome_json"]:
            outcome = json.loads(row["outcome_json"])
            if (isinstance(outcome, dict) and isinstance(outcome.get("result"), dict)
                and outcome.get("winner_side") in ("A", "B", None)
                and outcome["result"].get("winner") == outcome["winner_side"]):
                result["status"] = "completed"
                result["winner"] = outcome["winner_side"]
                result["result"] = outcome["result"]
                return result
        if row["status"] in ("DISPATCHING", "RUNNING"):
            result["status"] = "running"
            result["winner"] = None
            result["result"] = None
            return result
        if row["status"] == "INTERRUPTED":
            result["status"] = "interrupted"
            result["winner"] = None
            result["result"] = {"winner": None,
                "reason": row["status_reason"] or "OFFICIAL_INTERRUPTED", "faults": {}}
            return result
    # Missing/mismatched/invalid authority must never publish a JSON victory.
    result["status"] = "interrupted"
    result["winner"] = None
    result["result"] = {"winner": None, "reason": "OFFICIAL_UNVERIFIED", "faults": {}}
    return result


def snapshot_source(store, record, bot):
    """Read only server-controlled source paths and fail closed on read errors.

    A broken/unreadable source must block its own request, not raise an OS
    exception that rolls back otherwise healthy requests in the due queue.
    """
    bot_id=record["bot_id"]
    language=bot.get("language")
    if (len(bot_id)!=16 or any(c not in "0123456789abcdef" for c in bot_id)
        or language not in ("py","cpp","java")):
        return None
    filename="Main.java" if language=="java" else f"bot.{language}"
    try:
        root=store.uploads.resolve()
        location=(root/bot_id/filename).resolve()
        if not location.is_relative_to(root) or not location.is_file():
            return None
        data=location.read_bytes()
    except OSError:
        return None
    if not data or len(data)>256*1024:
        return None
    return hashlib.sha256(data).hexdigest()


def lock_due_matches(connection, store, now):
    """Must be invoked inside the caller's existing BEGIN IMMEDIATE transaction.

    This function also runs before every Active Bot mutation. A delayed scheduler
    cannot allow selecting a bot after a request's lock deadline.
    """
    rows=connection.execute("""SELECT * FROM official_match_requests
        WHERE status='SCHEDULED' AND bot_lock_at <= ?
        ORDER BY bot_lock_at,id""",(now,)).fetchall()
    results=[]
    for request in rows:
        slots=[]
        reason=None
        for side in ("A","B"):
            tid=request["team_a_id"] if side=="A" else request["team_b_id"]
            team=connection.execute("SELECT * FROM teams WHERE id=?",(tid,)).fetchone()
            if not team or team["status"]!="ACTIVE":
                reason="TEAM_INACTIVE";break
            selected=connection.execute("""SELECT b.bot_id,b.revision
                FROM team_game_bots b WHERE b.team_id=? AND b.game_id=?""",
                (tid,request["game_id"])).fetchone()
            if not selected:
                reason="ACTIVE_BOT_MISSING";break
            binding=connection.execute("""SELECT bot_id,team_id,game_id FROM submission_ownership
                WHERE bot_id=? AND team_id=? AND game_id=?""",
                (selected["bot_id"],tid,request["game_id"])).fetchone()
            bot=store.get_bot(selected["bot_id"])
            if (not binding or not bot or bot.get("team_id")!=tid
                or bot.get("game_id")!=request["game_id"] or bot.get("status")!="ready"):
                reason="BOT_UNAVAILABLE";break
            attestation=connection.execute("""SELECT source_sha256 FROM official_source_attestations
                WHERE bot_id=?""",(selected["bot_id"],)).fetchone()
            if attestation is None:
                reason="SOURCE_UNVERIFIED";break
            digest=snapshot_source(store,binding,bot)
            if digest is None:
                reason="SOURCE_UNAVAILABLE";break
            if digest != attestation["source_sha256"]:
                reason="SOURCE_CHANGED";break
            slots.append((request["id"],side,tid,team["display_name"],
                          request["game_id"],bot["id"],bot["name"],bot["language"],
                          digest,bot.get("artifact_id"),bot.get("artifact_digest"),
                          selected["revision"],now))
        if reason is None:
            # Slots and transition are in one SQLite transaction; nothing half-locked
            # becomes visible to readers.
            connection.executemany("""INSERT INTO official_match_slots
                (request_id,side,team_id,team_name_snapshot,game_id,bot_id,
                 bot_name_snapshot,bot_language,source_sha256,
                 artifact_id,artifact_digest,bot_revision,locked_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",slots)
            connection.execute("""UPDATE official_match_requests
                SET status='LOCKED',locked_at=?,revision=revision+1 WHERE id=?""",
                (now,request["id"]))
            action="OFFICIAL_MATCH_LOCKED"
            state="LOCKED"
        else:
            connection.execute("""UPDATE official_match_requests
                SET status='BLOCKED',status_reason=?,revision=revision+1 WHERE id=?""",
                (reason,request["id"]))
            action="OFFICIAL_MATCH_BLOCKED"
            state="BLOCKED"
        connection.execute("""INSERT INTO audit_events
            (occurred_at,actor_user_id,action,target_type,target_id,details_json)
            VALUES (?,NULL,?,'official_match',?,?)""",
            (now,action,request["id"],json.dumps({"reason":reason})))
        results.append((request["id"],state))
    return results


def official_json(connection,row,*,include_slots=True):
    result={name:row[name] for name in (
        "id","team_a_id","team_b_id","game_id","bot_lock_at",
        "scheduled_at","created_at","status","locked_at","status_reason","revision")}
    result.update(match_id=row["match_id"],started_at=row["started_at"],
                  finished_at=row["finished_at"],
                  outcome=json.loads(row["outcome_json"]) if row["outcome_json"] else None)
    result["rules_snapshot"]=json.loads(row["rules_json"])
    if include_slots:
        result["slots"]=[dict(slot) for slot in connection.execute("""SELECT side,team_id,team_name_snapshot,
            game_id,bot_id,bot_name_snapshot,bot_language,source_sha256,
            bot_revision,locked_at FROM official_match_slots WHERE request_id=?
            ORDER BY side""",(row["id"],)).fetchall()]
    return result


class OfficialSchedule:
    def __init__(self, connection,writer,auth,store,registry):
        self.db,self.writer,self.auth,self.store,self.registry=connection,writer,auth,store,registry

    def _now(self):
        return self.auth._now()

    def _ready(self):
        require_writer(self.writer,self.writer.path.parent)

    def create(self,actor,*,team_a_id,team_b_id,game_id,bot_lock_at,scheduled_at,
               team_tournament_fixture_id=None):
        self._ready()
        with transaction(self.db):
            now=self._now()
            admin=self.auth.require_actor(actor,now,admin=True)
            if (not isinstance(bot_lock_at,int) or isinstance(bot_lock_at,bool)
                or not isinstance(scheduled_at,int) or isinstance(scheduled_at,bool)
                or not now <= bot_lock_at <= scheduled_at <= now+365*86400):
                raise ValueError("Invalid lock deadline or schedule")
            if team_a_id==team_b_id:
                raise OfficialConflict("An Official Match requires two distinct Teams")
            if game_id not in self.registry.ids():
                raise ValueError("Unknown game")
            teams=self.db.execute("""SELECT id,status FROM teams
                WHERE id IN (?,?)""",(team_a_id,team_b_id)).fetchall()
            if len(teams)!=2:
                raise OfficialNotFound("Team not found")
            if any(t["status"]!="ACTIVE" for t in teams):
                raise OfficialConflict("Both Teams must be ACTIVE")
            fixture = None
            if team_tournament_fixture_id is not None:
                fixture = self.db.execute("""SELECT f.*,t.game_id,t.status AS tournament_status
                    FROM team_tournament_fixtures f JOIN team_tournaments t ON t.id=f.tournament_id
                    WHERE f.id=?""", (team_tournament_fixture_id,)).fetchone()
                if not fixture:
                    raise OfficialNotFound("Tournament fixture not found")
                if (fixture["tournament_status"] != "ACTIVE" or fixture["official_request_id"]
                    or fixture["game_id"] != game_id
                    or {fixture["team_a_id"], fixture["team_b_id"]} != {team_a_id, team_b_id}):
                    raise OfficialConflict("Tournament fixture is unavailable or does not match this schedule")
            rules=self.registry.get(game_id).validate_rules(self.store.get_rules(game_id))
            request_id=uuid4().hex
            self.db.execute("""INSERT INTO official_match_requests
                (id,created_by,team_a_id,team_b_id,game_id,rules_json,
                 bot_lock_at,scheduled_at,created_at,status)
                VALUES (?,?,?,?,?,?,?,?,?,'SCHEDULED')""",
                (request_id,admin["id"],team_a_id,team_b_id,game_id,
                 json.dumps(rules,separators=(",",":"),sort_keys=True),
                 bot_lock_at,scheduled_at,now))
            self.db.execute("""INSERT INTO audit_events
                (occurred_at,actor_user_id,action,target_type,target_id,details_json)
                VALUES (?,?,'OFFICIAL_MATCH_SCHEDULED','official_match',?,'{}')""",
                (now,admin["id"],request_id))
            if fixture is not None:
                self.db.execute("UPDATE team_tournament_fixtures SET official_request_id=? WHERE id=?",
                                 (request_id, team_tournament_fixture_id))
                self.db.execute("""INSERT INTO team_tournament_audit
                    (tournament_id,fixture_id,actor_user_id,action,occurred_at)
                    VALUES (?,?,?,'FIXTURE_SCHEDULED',?)""",
                    (fixture["tournament_id"], team_tournament_fixture_id, admin["id"], now))
            lock_due_matches(self.db,self.store,now)
            return official_json(self.db,self._get(request_id))

    def _get(self,request_id):
        row=self.db.execute("SELECT * FROM official_match_requests WHERE id=?",(request_id,)).fetchone()
        if row is None:
            raise OfficialNotFound("Official Match not found")
        return row

    def list_admin(self,actor):
        self.auth.require_actor(actor,self._now(),admin=True,touch=False)
        return [official_json(self.db,row) for row in self.db.execute(
            "SELECT * FROM official_match_requests ORDER BY scheduled_at DESC,id DESC LIMIT 200")]

    def detail_admin(self,actor,request_id):
        self.auth.require_actor(actor,self._now(),admin=True,touch=False)
        return official_json(self.db,self._get(request_id))

    def detail_player(self, actor, request_id):
        user = self.auth.require_actor(actor, self._now(), player_only=True, touch=False)
        row = self.db.execute("""SELECT r.* FROM official_match_requests r
            WHERE r.id=? AND EXISTS (
                SELECT 1 FROM team_memberships m WHERE m.user_id=?
                    AND m.left_at IS NULL AND m.team_id IN
                    (r.team_a_id,r.team_b_id))""",
            (request_id, user["id"])).fetchone()
        if not row:
            raise OfficialNotFound("Official match not found")
        return official_json(self.db,row)

    def list_player(self,actor):
        user=self.auth.require_actor(actor,self._now(),player_only=True,touch=False)
        return [official_json(self.db,row) for row in self.db.execute("""SELECT r.*
            FROM official_match_requests r
            WHERE EXISTS (SELECT 1 FROM team_memberships m
                WHERE m.user_id=? AND m.left_at IS NULL AND
                  m.team_id IN (r.team_a_id,r.team_b_id))
            ORDER BY r.scheduled_at DESC,r.id DESC LIMIT 100""",(user["id"],))]

    def cancel(self,actor,request_id):
        self._ready()
        with transaction(self.db):
            now=self._now()
            admin=self.auth.require_actor(actor,now,admin=True)
            lock_due_matches(self.db,self.store,now)
            row=self._get(request_id)
            if row["status"] not in ("SCHEDULED","LOCKED","BLOCKED"):
                raise OfficialConflict("Official request already cancelled")
            self.db.execute("""UPDATE official_match_requests
                SET status='CANCELLED',locked_at=NULL,revision=revision+1
                WHERE id=?""",(request_id,))
            fixture = self.db.execute("""SELECT id AS fixture_id,tournament_id FROM
                team_tournament_fixtures WHERE official_request_id=?""", (request_id,)).fetchone()
            if fixture:
                # Keep the cancelled request and audit history, but make its
                # fixture schedulable again from the Team tournament view.
                self.db.execute("UPDATE team_tournament_fixtures SET official_request_id=NULL WHERE id=?",
                                 (fixture["fixture_id"],))
                self.db.execute("""INSERT INTO team_tournament_audit
                    (tournament_id,fixture_id,actor_user_id,action,occurred_at)
                    VALUES (?,?,?,'FIXTURE_UNSCHEDULED',?)""",
                    (fixture["tournament_id"], fixture["fixture_id"], admin["id"], now))
            self.db.execute("""INSERT INTO audit_events
                (occurred_at,actor_user_id,action,target_type,target_id,details_json)
                VALUES (?,?,'OFFICIAL_MATCH_CANCELLED','official_match',?,'{}')""",
                (now,admin["id"],request_id))
            return official_json(self.db,self._get(request_id))


    def _stamp_execution(self, request_id, status, now, *, reason=None, outcome=None):
        self.db.execute("""UPDATE official_match_requests
            SET status=?, status_reason=?, finished_at=?,
                outcome_json=?, revision=revision+1 WHERE id=?""",
            (status, reason, now if status in ("COMPLETED", "INTERRUPTED") else None,
             json.dumps(outcome, separators=(",", ":")) if outcome is not None else None, request_id))
        self.db.execute("""INSERT INTO audit_events
            (occurred_at,actor_user_id,action,target_type,target_id,details_json)
            VALUES (?,NULL,?,'official_match',?,?)""",
            (now, "OFFICIAL_MATCH_" + status, request_id,
             json.dumps({"reason": reason}, separators=(",", ":"))))

    def claim_due(self):
        """Reserve ONE due match in SQLite before any runner or JSON side effect.

        A claimed match is NEVER reclaimed for execution after restart; this
        prevents duplicates even if the process dies between claim and launch.
        """
        self._ready()
        with transaction(self.db):
            now = self._now()
            row = self.db.execute("""SELECT * FROM official_match_requests
                WHERE status='LOCKED' AND scheduled_at <= ?
                ORDER BY scheduled_at,id LIMIT 1""", (now,)).fetchone()
            if row is None:
                return None
            slots = {s["side"]: dict(s) for s in self.db.execute(
                "SELECT * FROM official_match_slots WHERE request_id=?",
                (row["id"],)).fetchall()}
            reason = None
            if set(slots) != {"A", "B"}:
                reason = "FROZEN_SLOTS_MISSING"
            else:
                for side in ("A", "B"):
                    slot = slots[side]
                    bot = self.store.get_bot(slot["bot_id"])
                    if (not bot or bot.get("team_id") != slot["team_id"]
                        or bot.get("game_id") != slot["game_id"]
                        or bot.get("language") != slot["bot_language"]
                        or bot.get("status") != "ready"
                        or bot.get("execution_backend") != "sandbox"
                        or not slot.get("artifact_id") or not slot.get("artifact_digest")
                        or bot.get("artifact_id") != slot["artifact_id"]
                        or bot.get("artifact_digest") != slot["artifact_digest"]):
                        reason = "FROZEN_ARTIFACT_UNAVAILABLE"
                        break
                    actual = snapshot_source(self.store, slot, bot)
                    if actual is None:
                        reason = "SOURCE_UNAVAILABLE"
                        break
                    if actual != slot["source_sha256"]:
                        reason = "SOURCE_CHANGED"
                        break
                    attested = self.db.execute("""SELECT source_sha256
                        FROM official_source_attestations WHERE bot_id=?""",
                        (slot["bot_id"],)).fetchone()
                    if not attested or actual != attested["source_sha256"]:
                        reason = "SOURCE_UNVERIFIED"
                        break
            if reason:
                self.db.execute("""UPDATE official_match_requests
                    SET status='BLOCKED',locked_at=NULL,status_reason=?,
                        revision=revision+1 WHERE id=?""", (reason,row["id"]))
                self.db.execute("""INSERT INTO audit_events
                    (occurred_at,actor_user_id,action,target_type,target_id,details_json)
                    VALUES (?,NULL,'OFFICIAL_MATCH_BLOCKED','official_match',?,?)""",
                    (now,row["id"],json.dumps({"reason":reason})))
                return {"blocked": row["id"], "reason": reason}
            match_id = "o" + row["id"][:15]
            self.db.execute("""UPDATE official_match_requests
                SET status='DISPATCHING',match_id=?,started_at=?,
                    revision=revision+1 WHERE id=? AND status='LOCKED'""",
                (match_id,now,row["id"]))
            self.db.execute("""INSERT INTO audit_events
                (occurred_at,actor_user_id,action,target_type,target_id,details_json)
                VALUES (?,NULL,'OFFICIAL_MATCH_DISPATCHING','official_match',?,'{}')""",
                (now,row["id"]))
            return {"id":row["id"],"match_id":match_id,"game_id":row["game_id"],
                    "rules_snapshot":json.loads(row["rules_json"]),"slots":slots}

    def sync_execution(self):
        """Reconcile saved MatchManager results during normal server operation."""
        self._ready()
        with transaction(self.db):
            now = self._now()
            changed = []
            rows = self.db.execute("""SELECT * FROM official_match_requests WHERE
                status IN ('DISPATCHING','RUNNING')""").fetchall()
            for row in rows:
                match = self.store.get_match(row["match_id"])
                if not match or match.get("official_request_id") != row["id"]:
                    continue
                status = match.get("status")
                if status == "completed":
                    replay = self.store.get_replay(row["match_id"])
                    frames = replay.get("frames", []) if replay else []
                    terminal = frames[-1] if frames else {}
                    # MatchManager stores adapter.get_result(state), which can
                    # enrich the serialized frame result (e.g. Robot HP scores).
                    # Reconstruct that exact value from the persisted terminal
                    # frame; missing or inconsistent evidence still fails closed.
                    try:
                        verified_result = (self.registry.get(row["game_id"]).get_result(terminal)
                            if isinstance(terminal, dict) and terminal.get("game_id") == row["game_id"]
                            else None)
                    except (KeyError, TypeError, ValueError, AttributeError):
                        verified_result = None
                    if (not frames or not verified_result or not match.get("result")
                        or terminal.get("turn") != match.get("turn")
                        or verified_result != match.get("result")):
                        # A persisted JSON victory without its final replay
                        # frame is NOT a verified completed Official Match.
                        self._stamp_execution(row["id"], "INTERRUPTED", now, reason="REPLAY_INCOMPLETE")
                    else:
                        winner = match["result"].get("winner")
                        slots = dict((s["side"], s["team_id"]) for s in self.db.execute(
                            "SELECT side,team_id FROM official_match_slots WHERE request_id=?", (row["id"],)))
                        outcome = {"winner_side":winner,"winner_team_id":slots.get(winner),
                                   "result":match["result"],"turn":match.get("turn",0)}
                        self._stamp_execution(row["id"], "COMPLETED", now, outcome=outcome)
                    changed.append(row["id"])
                elif status == "interrupted":
                    self._stamp_execution(row["id"], "INTERRUPTED", now,
                                          reason=match.get("result",{}).get("reason","MATCH_INTERRUPTED"))
                    changed.append(row["id"])
                elif status in ("queued","running") and row["status"] == "DISPATCHING":
                    self.db.execute("""UPDATE official_match_requests
                        SET status='RUNNING',revision=revision+1 WHERE id=?""", (row["id"],))
                    changed.append(row["id"])
            return changed

    def recover_uncertain(self):
        """Startup fence: never execute an in-flight/possibly executed claim twice."""
        self._ready()
        self.sync_execution()
        with transaction(self.db):
            now = self._now()
            rows = self.db.execute("""SELECT id FROM official_match_requests
                WHERE status IN ('DISPATCHING','RUNNING')""").fetchall()
            for row in rows:
                self._stamp_execution(row["id"], "INTERRUPTED", now, reason="SERVER_RESTART")
            return len(rows)

    def dispatch_failed(self, request_id):
        """No retry of an execution claim with uncertain side effects."""
        self._ready()
        with transaction(self.db):
            row = self._get(request_id)
            if row["status"] not in ("DISPATCHING","RUNNING"):
                return False
            self._stamp_execution(request_id,"INTERRUPTED",self._now(),
                                  reason="DISPATCH_FAILED")
            return True

    def replay(self, actor, request_id, *, audience, manager):
        now = self._now()
        if audience == "ADMIN":
            self.auth.require_actor(actor, now, admin=True, touch=False)
        elif audience == "PLAYER":
            player = self.auth.require_actor(actor, now, player_only=True, touch=False)
            member = self.db.execute("""SELECT 1 FROM team_memberships
                WHERE user_id=? AND left_at IS NULL AND team_id IN
                    (SELECT team_a_id FROM official_match_requests WHERE id=?
                     UNION SELECT team_b_id FROM official_match_requests WHERE id=?)""",
                (player["id"],request_id,request_id)).fetchone()
            if not member:
                raise OfficialNotFound("Official match not found")
        else:
            raise PermissionDenied("Wrong account audience")
        row = self._get(request_id)
        if not row["match_id"]:
            raise OfficialConflict("Match has not started; no replay exists")
        payload = manager.get_replay(row["match_id"])
        if not payload or payload["match"].get("official_request_id") != row["id"]:
            raise OfficialConflict("Match replay is not available")
        match = payload["match"]
        # Explicit allowlist: never expose server-side execution commands,
        # artifact IDs/digests, source, runner tokens or internal owner details.
        fields = ("id","game_id","game","game_name","game_version","status",
                  "created_at","finished_at","turn","result","winner","rules",
                  "rules_snapshot","player_a_name_snapshot","player_b_name_snapshot")
        safe = {key:match[key] for key in fields if key in match}
        frames = payload.get("frames", [])
        # SQLite is the Official publication authority. A JSON match may
        # claim completion before its terminal replay is verified.
        if row["status"] == "COMPLETED":
            outcome = json.loads(row["outcome_json"]) if row["outcome_json"] else None
            if not outcome:
                raise OfficialConflict("Verified Official result is unavailable")
            safe["status"] = "completed"
            safe["result"] = outcome["result"]
            safe["winner"] = outcome["winner_side"]
        else:
            safe["winner"] = None
            if row["status"] == "INTERRUPTED":
                safe["status"] = "interrupted"
                safe["result"] = {"winner": None,
                    "reason": row["status_reason"] or "OFFICIAL_INTERRUPTED",
                    "faults": {}}
            else:
                safe["status"] = "running"
                safe["result"] = None
            # Do not expose an unverified terminal win via individual frames.
            # Construct copies: persisted frames stay untouched.
            frames = [{**frame, "result": None} if frame.get("result") else frame
                      for frame in frames]
        safe["bots"] = {side: {key:bot[key] for key in ("id","name","language") if key in bot}
                        for side,bot in match.get("bots",{}).items()}
        return {"match":safe,"version":payload.get("version",1),
                "frames":frames}

    def freeze_due(self):
        self._ready()
        with transaction(self.db):
            return lock_due_matches(self.db,self.store,self._now())
