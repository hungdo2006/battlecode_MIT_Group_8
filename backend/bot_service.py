"""Team-owned submissions with fail-closed cross-store publication and recovery.

Journal PREPARING exists before compilation; JSON is written before the immutable
SQLite ownership binding. Readers require both a committed binding and a matching
ready/error JSON bot, never a legacy owner fallback.
"""
import uuid
from pathlib import Path

from .account_database import transaction, require_writer
from .auth_service import PermissionDenied
from .team_service import TeamConflict, TeamNotFound, TeamValidationError, TeamPermissionDenied


def bot_public(bot):
    return {key: bot[key] for key in (
        "id", "name", "filename", "language", "game_id", "status", "created_at", "execution_backend"
    ) if key in bot}


def bot_compiler_detail(bot):
    return {**bot_public(bot), "logs": bot.get("logs", "")}


class TeamBots:
    def __init__(self, auth, connection, writer, store, registry):
        self.auth, self.db, self.writer = auth, connection, writer
        self.store, self.registry = store, registry

    def _member(self, actor, now, *, captain=False, touch=True):
        user = self.auth.require_actor(actor, now, player_only=True, touch=touch)
        row = self.db.execute("""SELECT t.id, t.status, m.team_role
            FROM team_memberships m JOIN teams t ON t.id=m.team_id
            WHERE m.user_id=? AND m.left_at IS NULL""", (user["id"],)).fetchone()
        if not row or row["status"] == "ARCHIVED":
            raise TeamPermissionDenied("Active Team membership required")
        if captain and row["team_role"] != "CAPTAIN":
            raise TeamPermissionDenied("Only Team Captain can select active bots")
        return user, row

    def begin(self, actor, game_id):
        require_writer(self.writer, self.writer.path.parent)
        with transaction(self.db):
            now = self.auth._now()
            user, member = self._member(actor, now)
            if game_id not in self.registry.ids():
                raise TeamValidationError("Game is not installed")
            bot_id = uuid.uuid4().hex[:16]
            self.db.execute("""INSERT INTO submission_journal
                (bot_id,team_id,game_id,uploaded_by,created_at,state)
                VALUES (?,?,?,?,?,'PREPARING')""",
                (bot_id,member["id"],game_id,user["id"],now))
            return {"bot_id":bot_id,"team_id":member["id"],"user_id":user["id"],"created_at":now}

    def check_upload(self, actor, ticket):
        require_writer(self.writer, self.writer.path.parent)
        user, member = self._member(actor, self.auth._now())
        if user["id"] != ticket["user_id"] or member["id"] != ticket["team_id"]:
            raise TeamConflict("Team membership changed during compilation")
        return True

    def finish(self, actor, bot_id, *, saved):
        require_writer(self.writer, self.writer.path.parent)
        with transaction(self.db):
            now = self.auth._now()
            user, member = self._member(actor, now)
            row = self.db.execute("SELECT * FROM submission_journal WHERE bot_id=?", (bot_id,)).fetchone()
            if not row or row["state"] != "PREPARING":
                raise TeamConflict("Submission is no longer pending")
            if (row["team_id"] != member["id"] or row["uploaded_by"] != user["id"]
                or not saved or saved.get("id") != bot_id or saved.get("game_id") != row["game_id"]
                or saved.get("team_id") != member["id"]):
                raise TeamConflict("Submission Team, uploader or data changed")
            self.db.execute("""INSERT INTO submission_ownership
                (bot_id,team_id,game_id,uploaded_by,origin,created_at)
                VALUES (?,?,?,?,'NEW',?)""", (bot_id,row["team_id"],row["game_id"],user["id"],row["created_at"]))
            self.db.execute("UPDATE submission_journal SET state='COMMITTED' WHERE bot_id=?", (bot_id,))
            self.db.execute("""INSERT INTO audit_events(occurred_at,actor_user_id,action,target_type,target_id,details_json)
                VALUES (?,?,'TEAM_BOT_SUBMITTED','bot',?,'{}')""", (now,user["id"],bot_id))
            return row["team_id"]

    def abort(self, bot_id):
        require_writer(self.writer, self.writer.path.parent)
        with transaction(self.db):
            self.db.execute("UPDATE submission_journal SET state='ABORTED' WHERE bot_id=? AND state='PREPARING'", (bot_id,))

    def list_owned(self, actor, *, game_id=None):
        now = self.auth._now()
        user, member = self._member(actor, now, touch=False)
        records = self.db.execute("""SELECT bot_id, game_id FROM submission_ownership
            WHERE team_id=? ORDER BY created_at DESC, bot_id DESC""", (member["id"],)).fetchall()
        result = []
        for record in records:
            if game_id and record["game_id"] != game_id:
                continue
            bot = self.store.get_bot(record["bot_id"])
            if bot and bot.get("team_id") == member["id"] and bot.get("game_id") == record["game_id"]:
                result.append(bot_compiler_detail(bot))
        return result

    def bot_detail(self, actor, bot_id):
        now = self.auth._now()
        _, member = self._member(actor, now, touch=False)
        record = self.db.execute("""SELECT game_id FROM submission_ownership
            WHERE bot_id=? AND team_id=?""", (bot_id,member["id"])).fetchone()
        bot = self.store.get_bot(bot_id)
        if not record or not bot or bot.get("team_id") != member["id"] or bot.get("game_id") != record["game_id"]:
            raise TeamNotFound("Team bot not found")
        return bot_compiler_detail(bot)

    def source(self, actor, bot_id):
        # Only authorized same-Team members can obtain source. Construct the
        # path from validated upload root and bot ID, never from JSON folder.
        detail = self.bot_detail(actor, bot_id)
        bot = self.store.get_bot(bot_id)
        language = detail["language"]
        filename = "Main.java" if language == "java" else "bot." + language
        if language not in ("py", "cpp", "java") or len(bot_id) != 16 or any(c not in "0123456789abcdef" for c in bot_id):
            raise TeamNotFound("Source not found")
        root = self.store.uploads.resolve()
        source = (root / bot_id / filename).resolve()
        if not source.is_relative_to(root) or not source.is_file():
            raise TeamNotFound("Source not found")
        raw = source.read_bytes()
        if len(raw) > 256 * 1024:
            raise TeamConflict("Source exceeds expected maximum")
        return {"filename": bot["filename"], "source": raw.decode("utf-8", errors="replace")}

    def active(self, actor, game_id):
        now = self.auth._now()
        _, member = self._member(actor, now, touch=False)
        row = self.db.execute("""SELECT * FROM team_game_bots
            WHERE team_id=? AND game_id=?""", (member["id"],game_id)).fetchone()
        if not row:
            return None
        bot = self.store.get_bot(row["bot_id"])
        if not bot or bot.get("team_id") != member["id"] or bot.get("game_id") != game_id or bot.get("status") != "ready":
            return None  # Fail closed; never advertise stale/incompatible active bot.
        return {"game_id":game_id,"bot":bot_public(bot),"revision":row["revision"],
                "selected_at":row["selected_at"]}

    def select(self, actor, game_id, bot_id):
        require_writer(self.writer, self.writer.path.parent)
        with transaction(self.db):
            now = self.auth._now()
            user, member = self._member(actor, now, captain=True)
            if member["status"] != "ACTIVE":
                raise TeamConflict("Activate Team before selecting official active bot")
            row = self.db.execute("""SELECT 1 FROM submission_ownership
                WHERE bot_id=? AND team_id=? AND game_id=?""", (bot_id,member["id"],game_id)).fetchone()
            bot = self.store.get_bot(bot_id)
            if not row or not bot or bot.get("team_id") != member["id"] or bot.get("game_id") != game_id:
                raise TeamNotFound("Bot is not owned by your Team and game")
            if bot.get("status") != "ready":
                raise TeamConflict("Only ready bots can be selected")
            previous = self.db.execute("SELECT revision FROM team_game_bots WHERE team_id=? AND game_id=?",
                                        (member["id"],game_id)).fetchone()
            revision = previous["revision"]+1 if previous else 1
            self.db.execute("""INSERT INTO team_game_bots
                (team_id,game_id,bot_id,selected_by,selected_at,revision)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(team_id,game_id) DO UPDATE SET
                    bot_id=excluded.bot_id,selected_by=excluded.selected_by,
                    selected_at=excluded.selected_at,revision=excluded.revision""",
                (member["id"],game_id,bot_id,user["id"],now,revision))
            self.db.execute("""INSERT INTO audit_events
                (occurred_at,actor_user_id,action,target_type,target_id,details_json)
                VALUES (?,?,'TEAM_ACTIVE_BOT_SELECTED','bot',?,'{}')""", (now,user["id"],bot_id))
            return {"game_id":game_id,"bot":bot_public(bot),"revision":revision,"selected_at":now}

    def reconcile(self):
        """Idempotent startup inspection; never invent ownership for legacy bots.

        Incomplete journals become ABORTED, committed bindings missing matching
        JSON stay unavailable. Physical artifacts/JSON are left untouched for review.
        """
        require_writer(self.writer, self.writer.path.parent)
        with transaction(self.db):
            rows = self.db.execute("SELECT bot_id FROM submission_journal WHERE state IN ('PREPARING','RECOVERING')").fetchall()
            for row in rows:
                self.db.execute("UPDATE submission_journal SET state='ABORTED' WHERE bot_id=?", (row["bot_id"],))
            return len(rows)
