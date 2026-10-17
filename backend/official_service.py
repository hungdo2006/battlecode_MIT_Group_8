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
                          digest,selected["revision"],now))
        if reason is None:
            # Slots and transition are in one SQLite transaction; nothing half-locked
            # becomes visible to readers.
            connection.executemany("""INSERT INTO official_match_slots
                (request_id,side,team_id,team_name_snapshot,game_id,bot_id,
                 bot_name_snapshot,bot_language,source_sha256,bot_revision,locked_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",slots)
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

    def create(self,actor,*,team_a_id,team_b_id,game_id,bot_lock_at,scheduled_at):
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
            self.db.execute("""INSERT INTO audit_events
                (occurred_at,actor_user_id,action,target_type,target_id,details_json)
                VALUES (?,?,'OFFICIAL_MATCH_CANCELLED','official_match',?,'{}')""",
                (now,admin["id"],request_id))
            return official_json(self.db,self._get(request_id))

    def freeze_due(self):
        self._ready()
        with transaction(self.db):
            return lock_due_matches(self.db,self.store,self._now())
