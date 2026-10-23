"""Phase 4.2C1: Team domain service.

Manages Team lifecycle (DRAFT, ACTIVE, ARCHIVED), membership (CAPTAIN, MEMBER),
invitations, RBAC, succession, and audit trails.
All mutations run under an active WriterLock in explicit SQLite transactions.
"""
from dataclasses import dataclass
import json
import math
import re
import sqlite3
import time
import uuid

from .account_database import require_writer, transaction, validate_service_connection
from .account_identity import display_name
from .auth_service import AccountConflict, AuthService, InvalidInvitation, PermissionDenied, Principal


DEFAULT_INVITATION_TTL = 7 * 86400  # 7 days


class TeamNotFound(ValueError):
    """Team not found."""


class TeamPermissionDenied(PermissionDenied):
    """Actor is not authorized for the requested team operation."""


class TeamConflict(AccountConflict):
    """Team state conflict (duplicate membership, invalid state transition, etc.)."""


class TeamValidationError(ValueError):
    """Invalid input parameter or user eligibility."""


def normalize_slug(slug: str) -> str:
    if not isinstance(slug, str):
        raise TeamValidationError("Team slug must be text")
    result = slug.strip().lower()
    if not re.fullmatch(r"[a-z0-9-]{3,48}", result, flags=re.ASCII):
        raise TeamValidationError("Team slug must be 3..48 ASCII lowercase letters, numbers, or hyphens")
    return result


def validate_team_display_name(name: str) -> str:
    try:
        return display_name(name)
    except ValueError as exc:
        raise TeamValidationError(str(exc)) from exc


@dataclass(frozen=True)
class Team:
    id: str
    slug: str
    display_name: str
    status: str  # 'DRAFT', 'ACTIVE', 'ARCHIVED'
    created_by: str
    created_at: int
    updated_at: int
    captain_id: str | None = None
    member_count: int = 1
    max_members: int = 5


@dataclass(frozen=True)
class TeamMember:
    id: str
    team_id: str
    user_id: str
    username: str
    display_name: str
    team_role: str  # 'CAPTAIN', 'MEMBER'
    joined_at: int
    left_at: int | None = None


@dataclass(frozen=True)
class TeamInvitation:
    id: str
    team_id: str
    team_slug: str | None
    team_display_name: str | None
    invited_user_id: str
    invited_username: str | None
    invited_by: str
    invited_by_username: str | None
    status: str  # 'PENDING', 'ACCEPTED', 'DECLINED', 'REVOKED', 'EXPIRED'
    created_at: int
    expires_at: int
    responded_at: int | None = None


@dataclass(frozen=True)
class MyTeam:
    team: Team
    my_role: str  # 'CAPTAIN' | 'MEMBER'
    my_membership_id: str


class TeamService:
    def __init__(self, connection, writer_lock, *, auth_service: AuthService,
                 clock=time.time, invitation_ttl=DEFAULT_INVITATION_TTL):
        validate_service_connection(connection, writer_lock)
        connection.row_factory = sqlite3.Row
        self._db = connection
        self._writer = writer_lock
        self._data_dir = writer_lock.path.parent
        self._auth = auth_service
        self._clock = clock
        self._invitation_ttl = invitation_ttl

    def _ready(self):
        require_writer(self._writer, self._data_dir)
        if self._db.in_transaction:
            raise RuntimeError("TeamService must not run inside a caller transaction")
        if self._db.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise RuntimeError("TeamService connection must keep foreign keys enabled")

    def _now(self):
        now = self._clock()
        if type(now) not in (int, float) or not math.isfinite(now) or not 0 <= now < 2 ** 62:
            raise RuntimeError("Invalid server clock")
        return int(now)

    def _audit(self, now, actor_id, action, target_type, target_id, **details):
        self._db.execute("""INSERT INTO audit_events (
            occurred_at, actor_user_id, action, target_type, target_id, details_json)
            VALUES (?, ?, ?, ?, ?, ?)""", (now, actor_id, action, target_type, target_id, json.dumps(details)))

    def _active_team_captain(self, team_id: str) -> str | None:
        row = self._db.execute(
            "SELECT user_id FROM team_memberships WHERE team_id = ? AND left_at IS NULL AND team_role = 'CAPTAIN'",
            (team_id,)).fetchone()
        return row["user_id"] if row else None

    def _active_team_member_count(self, team_id: str) -> int:
        return self._db.execute(
            "SELECT count(*) FROM team_memberships WHERE team_id = ? AND left_at IS NULL",
            (team_id,)).fetchone()[0]

    def member_limit(self):
        return self._db.execute("SELECT max_members FROM team_policy WHERE id=1").fetchone()[0]

    def policy(self, actor):
        self._ready()
        self._auth.require_actor(actor, self._now(), touch=False)
        return {"max_members": self.member_limit()}

    def set_member_limit(self, actor, limit):
        self._ready()
        if type(limit) is not int or not 2 <= limit <= 20:
            raise TeamValidationError("Giới hạn đội phải từ 2 đến 20 người, tính cả Captain.")
        with transaction(self._db):
            now = self._now()
            user = self._auth.require_actor(actor, now, admin=True)
            previous = self.member_limit()
            self._db.execute("UPDATE team_policy SET max_members=?,updated_at=?,updated_by=? WHERE id=1", (limit, now, user['id']))
            self._audit(now, user['id'], 'TEAM_MEMBER_LIMIT_CHANGED', 'team_policy', '1', previous=previous, max_members=limit)
        return {"max_members": limit}

    def _require_space(self, team_id):
        if self._active_team_member_count(team_id) >= self.member_limit():
            raise TeamConflict("Đội đã đủ thành viên. Liên hệ Admin hoặc chờ đội có chỗ trống.")

    def _team_dto(self, row) -> Team:
        captain_id = self._active_team_captain(row["id"])
        count = self._active_team_member_count(row["id"])
        return Team(
            id=row["id"], slug=row["slug"], display_name=row["display_name"],
            status=row["status"], created_by=row["created_by"],
            created_at=row["created_at"], updated_at=row["updated_at"],
            captain_id=captain_id, member_count=count, max_members=self.member_limit())

    def create_team(self, actor: Principal, slug: str, display_name: str) -> Team:
        self._ready()
        canonical_slug = normalize_slug(slug)
        canonical_name = validate_team_display_name(display_name)
        with transaction(self._db):
            now = self._now()
            user = self._auth.require_actor(actor, now, player_only=True)
            # Global single active team membership check
            active_m = self._db.execute(
                "SELECT team_id FROM team_memberships WHERE user_id = ? AND left_at IS NULL",
                (user["id"],)).fetchone()
            if active_m:
                raise TeamConflict("Player already has an active team membership")
            # Slug uniqueness check
            if self._db.execute("SELECT 1 FROM teams WHERE slug = ?", (canonical_slug,)).fetchone():
                raise TeamConflict("Team slug is already in use")
            team_id = uuid.uuid4().hex
            membership_id = uuid.uuid4().hex
            self._db.execute("""INSERT INTO teams (
                id, slug, display_name, status, created_by, created_at, updated_at)
                VALUES (?, ?, ?, 'DRAFT', ?, ?, ?)""",
                (team_id, canonical_slug, canonical_name, user["id"], now, now))
            self._db.execute("""INSERT INTO team_memberships (
                id, team_id, user_id, team_role, joined_at, left_at)
                VALUES (?, ?, ?, 'CAPTAIN', ?, NULL)""",
                (membership_id, team_id, user["id"], now))
            self._audit(now, user["id"], "TEAM_CREATED", "team", team_id,
                        slug=canonical_slug, display_name=canonical_name, captain_id=user["id"])
            return Team(id=team_id, slug=canonical_slug, display_name=canonical_name,
                        status="DRAFT", created_by=user["id"], created_at=now, updated_at=now,
                        captain_id=user["id"], member_count=1, max_members=self.member_limit())

    def get_my_team(self, actor: Principal) -> MyTeam | None:
        self._ready()
        now = self._now()
        user = self._auth.require_actor(actor, now, player_only=True, touch=False)
        membership = self._db.execute(
            "SELECT * FROM team_memberships WHERE user_id = ? AND left_at IS NULL",
            (user["id"],)).fetchone()
        if not membership:
            return None
        team_row = self._db.execute("SELECT * FROM teams WHERE id = ?", (membership["team_id"],)).fetchone()
        if not team_row:
            return None
        team_dto = self._team_dto(team_row)
        return MyTeam(team=team_dto, my_role=membership["team_role"], my_membership_id=membership["id"])

    def get_team(self, actor: Principal, team_id: str) -> Team:
        self._ready()
        now = self._now()
        user = self._auth.require_actor(actor, now, touch=False)
        team_row = self._db.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone()
        if not team_row:
            raise TeamNotFound("Team not found")
        # RBAC / IDOR protection: Players can only query teams they belong to
        if user["system_role"] == "PLAYER":
            is_member = self._db.execute(
                "SELECT 1 FROM team_memberships WHERE team_id = ? AND user_id = ? AND left_at IS NULL",
                (team_id, user["id"])).fetchone()
            if not is_member:
                raise TeamPermissionDenied("Not authorized to view this team")
        return self._team_dto(team_row)

    def update_team(self, actor: Principal, team_id: str, *, display_name: str) -> Team:
        self._ready()
        canonical_name = validate_team_display_name(display_name)
        with transaction(self._db):
            now = self._now()
            user = self._auth.require_actor(actor, now, player_only=True)
            team_row = self._db.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone()
            if not team_row:
                raise TeamNotFound("Team not found")
            if team_row["status"] == "ARCHIVED":
                raise TeamConflict("Cannot modify an archived team")
            captain_row = self._db.execute(
                "SELECT 1 FROM team_memberships WHERE team_id = ? AND user_id = ? AND left_at IS NULL AND team_role = 'CAPTAIN'",
                (team_id, user["id"])).fetchone()
            if not captain_row:
                raise TeamPermissionDenied("Only the Team Captain may update team settings")
            self._db.execute(
                "UPDATE teams SET display_name = ?, updated_at = ? WHERE id = ?",
                (canonical_name, now, team_id))
            self._audit(now, user["id"], "TEAM_UPDATED", "team", team_id,
                        old_display_name=team_row["display_name"], new_display_name=canonical_name)
            return Team(
                id=team_row["id"], slug=team_row["slug"], display_name=canonical_name,
                status=team_row["status"], created_by=team_row["created_by"],
                created_at=team_row["created_at"], updated_at=now,
                captain_id=user["id"], member_count=self._active_team_member_count(team_id), max_members=self.member_limit())

    def activate_team(self, actor: Principal, team_id: str) -> Team:
        self._ready()
        with transaction(self._db):
            now = self._now()
            user = self._auth.require_actor(actor, now, player_only=True)
            team_row = self._db.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone()
            if not team_row:
                raise TeamNotFound("Team not found")
            if team_row["status"] == "ACTIVE":
                raise TeamConflict("Team is already active")
            if team_row["status"] == "ARCHIVED":
                raise TeamConflict("Cannot activate an archived team")
            captain_row = self._db.execute(
                "SELECT 1 FROM team_memberships WHERE team_id = ? AND user_id = ? AND left_at IS NULL AND team_role = 'CAPTAIN'",
                (team_id, user["id"])).fetchone()
            if not captain_row:
                raise TeamPermissionDenied("Only the Team Captain may activate the team")
            self._db.execute("UPDATE teams SET status = 'ACTIVE', updated_at = ? WHERE id = ?", (now, team_id))
            self._audit(now, user["id"], "TEAM_ACTIVATED", "team", team_id)
            return Team(
                id=team_row["id"], slug=team_row["slug"], display_name=team_row["display_name"],
                status="ACTIVE", created_by=team_row["created_by"],
                created_at=team_row["created_at"], updated_at=now,
                captain_id=user["id"], member_count=self._active_team_member_count(team_id), max_members=self.member_limit())

    def archive_team(self, actor: Principal, team_id: str) -> Team:
        self._ready()
        with transaction(self._db):
            now = self._now()
            user = self._auth.require_actor(actor, now)
            team_row = self._db.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone()
            if not team_row:
                raise TeamNotFound("Team not found")
            if team_row["status"] == "ARCHIVED":
                raise TeamConflict("Team is already archived")
            is_admin = user["system_role"] == "ADMIN"
            if not is_admin:
                captain_row = self._db.execute(
                    "SELECT 1 FROM team_memberships WHERE team_id = ? AND user_id = ? AND left_at IS NULL AND team_role = 'CAPTAIN'",
                    (team_id, user["id"])).fetchone()
                if not captain_row:
                    raise TeamPermissionDenied("Only the Team Captain or an Administrator may archive the team")
            # 1. Update team status to ARCHIVED
            self._db.execute("UPDATE teams SET status = 'ARCHIVED', updated_at = ? WHERE id = ?", (now, team_id))
            # 2. End all active memberships
            self._db.execute("UPDATE team_memberships SET left_at = ? WHERE team_id = ? AND left_at IS NULL", (now, team_id))
            # 3. Revoke all pending invitations
            self._db.execute("""UPDATE team_invitations SET status = 'REVOKED', responded_at = ?
                WHERE team_id = ? AND status = 'PENDING'""", (now, team_id))
            # 4. Audit
            action = "ADMIN_TEAM_ARCHIVED" if is_admin else "TEAM_ARCHIVED"
            self._audit(now, user["id"], action, "team", team_id)
            return Team(
                id=team_row["id"], slug=team_row["slug"], display_name=team_row["display_name"],
                status="ARCHIVED", created_by=team_row["created_by"],
                created_at=team_row["created_at"], updated_at=now,
                captain_id=None, member_count=0, max_members=self.member_limit())

    def list_members(self, actor: Principal, team_id: str, *, include_history: bool = False) -> list[TeamMember]:
        self._ready()
        now = self._now()
        user = self._auth.require_actor(actor, now, touch=False)
        team_row = self._db.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone()
        if not team_row:
            raise TeamNotFound("Team not found")
        if user["system_role"] == "PLAYER":
            is_member = self._db.execute(
                "SELECT 1 FROM team_memberships WHERE team_id = ? AND user_id = ? AND left_at IS NULL",
                (team_id, user["id"])).fetchone()
            if not is_member:
                raise TeamPermissionDenied("Not authorized to view members of this team")
        query = """
            SELECT m.id, m.team_id, m.user_id, u.username, u.display_name, m.team_role, m.joined_at, m.left_at
            FROM team_memberships m
            JOIN users u ON m.user_id = u.id
            WHERE m.team_id = ?
        """
        if not include_history:
            query += " AND m.left_at IS NULL"
        query += " ORDER BY CASE WHEN m.team_role = 'CAPTAIN' AND m.left_at IS NULL THEN 0 WHEN m.left_at IS NULL THEN 1 ELSE 2 END, m.joined_at ASC"
        rows = self._db.execute(query, (team_id,)).fetchall()
        return [
            TeamMember(
                id=row["id"], team_id=row["team_id"], user_id=row["user_id"],
                username=row["username"], display_name=row["display_name"],
                team_role=row["team_role"], joined_at=row["joined_at"], left_at=row["left_at"])
            for row in rows
        ]

    def invite_member(self, actor: Principal, team_id: str, *, username: str, ttl_seconds: int | None = None) -> TeamInvitation:
        self._ready()
        from .account_identity import normalize_username
        canonical_target_username = normalize_username(username)
        ttl = ttl_seconds if ttl_seconds is not None else self._invitation_ttl
        if type(ttl) is not int or not 0 < ttl <= 365 * 86400:
            raise TeamValidationError("TTL must be an integer from 1 second to 365 days")
        with transaction(self._db):
            now = self._now()
            user = self._auth.require_actor(actor, now, player_only=True)
            team_row = self._db.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone()
            if not team_row:
                raise TeamNotFound("Team not found")
            if team_row["status"] == "ARCHIVED":
                raise TeamConflict("Cannot invite members to an archived team")
            captain_row = self._db.execute(
                "SELECT 1 FROM team_memberships WHERE team_id = ? AND user_id = ? AND left_at IS NULL AND team_role = 'CAPTAIN'",
                (team_id, user["id"])).fetchone()
            if not captain_row:
                raise TeamPermissionDenied("Only the Team Captain may invite members")
            self._require_space(team_id)
            # Lookup target player
            target = self._db.execute(
                "SELECT * FROM users WHERE username = ?", (canonical_target_username,)).fetchone()
            if not target or target["system_role"] != "PLAYER" or target["status"] != "ACTIVE":
                # Generic response to prevent account enumeration
                raise TeamValidationError("User not found or not eligible for team invitation")
            target_id = target["id"]
            if target_id == user["id"]:
                raise TeamConflict("Cannot invite yourself to your own team")
            # Check across all Teams at issuance; acceptance repeats this check.
            already_member = self._db.execute(
                "SELECT 1 FROM team_memberships WHERE user_id = ? AND left_at IS NULL",
                (target_id,)).fetchone()
            if already_member:
                raise TeamConflict("Player already has an active team membership")
            # Check existing pending invitation
            pending = self._db.execute(
                "SELECT * FROM team_invitations WHERE team_id = ? AND invited_user_id = ? AND status = 'PENDING'",
                (team_id, target_id)).fetchone()
            if pending:
                if pending["expires_at"] <= now:
                    # Expired pending row does not block new invitations; supersede it
                    self._db.execute(
                        "UPDATE team_invitations SET status = 'EXPIRED', responded_at = ? WHERE id = ?",
                        (now, pending["id"]))
                else:
                    raise TeamConflict("A pending invitation already exists for this player")
            invitation_id = uuid.uuid4().hex
            expires_at = now + ttl
            self._db.execute("""INSERT INTO team_invitations (
                id, team_id, invited_user_id, invited_by, status, created_at, expires_at, responded_at)
                VALUES (?, ?, ?, ?, 'PENDING', ?, ?, NULL)""",
                (invitation_id, team_id, target_id, user["id"], now, expires_at))
            self._audit(now, user["id"], "TEAM_INVITATION_CREATED", "team_invitation", invitation_id,
                        team_id=team_id, invited_user_id=target_id)
            return TeamInvitation(
                id=invitation_id, team_id=team_id, team_slug=team_row["slug"],
                team_display_name=team_row["display_name"], invited_user_id=target_id,
                invited_username=target["username"], invited_by=user["id"],
                invited_by_username=user["username"], status="PENDING",
                created_at=now, expires_at=expires_at, responded_at=None)

    def list_my_invitations(self, actor: Principal) -> list[TeamInvitation]:
        self._ready()
        now = self._now()
        user = self._auth.require_actor(actor, now, player_only=True, touch=False)
        with transaction(self._db):
            # Clean up expired pending invitations
            self._db.execute("""UPDATE team_invitations SET status = 'EXPIRED', responded_at = ?
                WHERE invited_user_id = ? AND status = 'PENDING' AND expires_at <= ?""",
                (now, user["id"], now))
        rows = self._db.execute("""
            SELECT i.id, i.team_id, t.slug as team_slug, t.display_name as team_display_name,
                   i.invited_user_id, u_target.username as invited_username,
                   i.invited_by, u_inviter.username as invited_by_username,
                   i.status, i.created_at, i.expires_at, i.responded_at
            FROM team_invitations i
            JOIN teams t ON i.team_id = t.id
            JOIN users u_target ON i.invited_user_id = u_target.id
            JOIN users u_inviter ON i.invited_by = u_inviter.id
            WHERE i.invited_user_id = ?
            ORDER BY i.created_at DESC
        """, (user["id"],)).fetchall()
        return [
            TeamInvitation(
                id=row["id"], team_id=row["team_id"], team_slug=row["team_slug"],
                team_display_name=row["team_display_name"], invited_user_id=row["invited_user_id"],
                invited_username=row["invited_username"], invited_by=row["invited_by"],
                invited_by_username=row["invited_by_username"], status=row["status"],
                created_at=row["created_at"], expires_at=row["expires_at"],
                responded_at=row["responded_at"])
            for row in rows
        ]

    def accept_invitation(self, actor: Principal, invitation_id: str) -> tuple[Team, TeamMember]:
        self._ready()
        terminal = None
        with transaction(self._db):
            now = self._now()
            user = self._auth.require_actor(actor, now, player_only=True)
            invitation = self._db.execute("SELECT * FROM team_invitations WHERE id=?", (invitation_id,)).fetchone()
            if not invitation:
                raise InvalidInvitation("Invitation not found")
            if invitation["invited_user_id"] != user["id"]:
                raise TeamPermissionDenied("Not authorized to accept another user's invitation")
            if invitation["status"] != "PENDING":
                raise TeamConflict("Invitation is not pending")
            if invitation["expires_at"] <= now:
                self._db.execute("UPDATE team_invitations SET status='EXPIRED', responded_at=? WHERE id=?", (now, invitation_id))
                self._audit(now, user["id"], "TEAM_INVITATION_EXPIRED", "team_invitation", invitation_id)
                terminal = "EXPIRED"
            else:
                team_row = self._db.execute("SELECT * FROM teams WHERE id=?", (invitation["team_id"],)).fetchone()
                if not team_row or team_row["status"] == "ARCHIVED":
                    self._db.execute("UPDATE team_invitations SET status='REVOKED', responded_at=? WHERE id=?", (now, invitation_id))
                    self._audit(now, user["id"], "TEAM_INVITATION_REVOKED_ARCHIVE", "team_invitation", invitation_id)
                    terminal = "ARCHIVED"
                else:
                    active = self._db.execute("SELECT team_id FROM team_memberships WHERE user_id=? AND left_at IS NULL",
                                              (user["id"],)).fetchone()
                    if active:
                        raise TeamConflict("Player already has an active team membership")
                    # BEGIN IMMEDIATE serializes capacity check + insertion,
                    # including accepts made through different browser tabs.
                    self._require_space(team_row['id'])
                    membership_id = uuid.uuid4().hex
                    self._db.execute("UPDATE team_invitations SET status='ACCEPTED', responded_at=? WHERE id=? AND status='PENDING'",
                                     (now, invitation_id))
                    self._db.execute("""INSERT INTO team_memberships
                        (id, team_id, user_id, team_role, joined_at, left_at)
                        VALUES (?, ?, ?, 'MEMBER', ?, NULL)""", (membership_id, team_row["id"], user["id"], now))
                    self._audit(now, user["id"], "TEAM_INVITATION_ACCEPTED", "team_invitation", invitation_id,
                                team_id=team_row["id"])
                    self._audit(now, user["id"], "TEAM_MEMBER_JOINED", "team_membership", membership_id,
                                team_id=team_row["id"], user_id=user["id"], team_role="MEMBER")
                    terminal = (self._team_dto(team_row), TeamMember(
                        id=membership_id, team_id=team_row["id"], user_id=user["id"],
                        username=user["username"], display_name=user["display_name"],
                        team_role="MEMBER", joined_at=now, left_at=None))
        # Raise AFTER committing terminal invitation state; raising inside transaction rolls back.
        if terminal == "EXPIRED":
            raise InvalidInvitation("Invitation has expired")
        if terminal == "ARCHIVED":
            raise TeamConflict("Team is archived or no longer available")
        return terminal

    def decline_invitation(self, actor: Principal, invitation_id: str) -> bool:
        self._ready()
        with transaction(self._db):
            now = self._now()
            user = self._auth.require_actor(actor, now, player_only=True)
            invitation = self._db.execute("SELECT * FROM team_invitations WHERE id = ?", (invitation_id,)).fetchone()
            if not invitation:
                raise InvalidInvitation("Invitation not found")
            if invitation["invited_user_id"] != user["id"]:
                raise TeamPermissionDenied("Not authorized to decline another user's invitation")
            if invitation["status"] != "PENDING":
                raise TeamConflict("Invitation is not pending")
            self._db.execute("""UPDATE team_invitations SET status = 'DECLINED', responded_at = ?
                WHERE id = ? AND status = 'PENDING'""", (now, invitation_id))
            self._audit(now, user["id"], "TEAM_INVITATION_DECLINED", "team_invitation", invitation_id,
                        team_id=invitation["team_id"])
            return True

    def revoke_invitation(self, actor: Principal, team_id: str, invitation_id: str) -> bool:
        self._ready()
        with transaction(self._db):
            now = self._now()
            user = self._auth.require_actor(actor, now)
            is_admin = user["system_role"] == "ADMIN"
            if not is_admin:
                captain_row = self._db.execute(
                    "SELECT 1 FROM team_memberships WHERE team_id = ? AND user_id = ? AND left_at IS NULL AND team_role = 'CAPTAIN'",
                    (team_id, user["id"])).fetchone()
                if not captain_row:
                    raise TeamPermissionDenied("Only the Team Captain or an Administrator may revoke invitations")
            invitation = self._db.execute(
                "SELECT * FROM team_invitations WHERE id = ? AND team_id = ?",
                (invitation_id, team_id)).fetchone()
            if not invitation:
                raise InvalidInvitation("Invitation not found")
            if invitation["status"] != "PENDING":
                raise TeamConflict("Invitation is not pending")
            self._db.execute("""UPDATE team_invitations SET status = 'REVOKED', responded_at = ?
                WHERE id = ? AND status = 'PENDING'""", (now, invitation_id))
            self._audit(now, user["id"], "TEAM_INVITATION_REVOKED", "team_invitation", invitation_id,
                        team_id=team_id)
            return True

    def remove_member(self, actor: Principal, team_id: str, target_user_id: str) -> bool:
        self._ready()
        with transaction(self._db):
            now = self._now()
            user = self._auth.require_actor(actor, now, player_only=True)
            team_row = self._db.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone()
            if not team_row:
                raise TeamNotFound("Team not found")
            if team_row["status"] == "ARCHIVED":
                raise TeamConflict("Cannot remove members from an archived team")
            captain_row = self._db.execute(
                "SELECT 1 FROM team_memberships WHERE team_id = ? AND user_id = ? AND left_at IS NULL AND team_role = 'CAPTAIN'",
                (team_id, user["id"])).fetchone()
            if not captain_row:
                raise TeamPermissionDenied("Only the Team Captain may remove members")
            if target_user_id == user["id"]:
                raise TeamConflict("Captain cannot be removed. Transfer captaincy or archive the team instead.")
            target_membership = self._db.execute(
                "SELECT * FROM team_memberships WHERE team_id = ? AND user_id = ? AND left_at IS NULL",
                (team_id, target_user_id)).fetchone()
            if not target_membership:
                raise TeamNotFound("Target player is not an active member of this team")
            if target_membership["team_role"] == "CAPTAIN":
                raise TeamConflict("Cannot remove team captain")
            self._db.execute("UPDATE team_memberships SET left_at = ? WHERE id = ?",
                             (now, target_membership["id"]))
            self._audit(now, user["id"], "TEAM_MEMBER_REMOVED", "team_membership", target_membership["id"],
                        team_id=team_id, removed_user_id=target_user_id)
            return True

    def leave_team(self, actor: Principal, team_id: str) -> bool:
        self._ready()
        with transaction(self._db):
            now = self._now()
            user = self._auth.require_actor(actor, now, player_only=True)
            team_row = self._db.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone()
            if not team_row:
                raise TeamNotFound("Team not found")
            if team_row["status"] == "ARCHIVED":
                raise TeamConflict("Cannot leave an archived team")
            membership = self._db.execute(
                "SELECT * FROM team_memberships WHERE team_id = ? AND user_id = ? AND left_at IS NULL",
                (team_id, user["id"])).fetchone()
            if not membership:
                raise TeamPermissionDenied("You are not an active member of this team")
            if membership["team_role"] == "CAPTAIN":
                raise TeamConflict("Captain cannot leave without transferring captain responsibility or archiving the team")
            self._db.execute("UPDATE team_memberships SET left_at = ? WHERE id = ?",
                             (now, membership["id"]))
            self._audit(now, user["id"], "TEAM_MEMBER_LEFT", "team_membership", membership["id"],
                        team_id=team_id)
            return True

    def transfer_captain(self, actor: Principal, team_id: str, new_captain_user_id: str) -> tuple[TeamMember, TeamMember]:
        self._ready()
        with transaction(self._db):
            now = self._now()
            user = self._auth.require_actor(actor, now, player_only=True)
            team_row = self._db.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone()
            if not team_row:
                raise TeamNotFound("Team not found")
            if team_row["status"] == "ARCHIVED":
                raise TeamConflict("Cannot transfer captaincy of an archived team")
            old_cap = self._db.execute(
                "SELECT * FROM team_memberships WHERE team_id = ? AND user_id = ? AND left_at IS NULL AND team_role = 'CAPTAIN'",
                (team_id, user["id"])).fetchone()
            if not old_cap:
                raise TeamPermissionDenied("Only the current Team Captain may transfer captaincy")
            if new_captain_user_id == user["id"]:
                raise TeamConflict("User is already captain of this team")
            new_target = self._db.execute("SELECT * FROM users WHERE id = ?", (new_captain_user_id,)).fetchone()
            if not new_target or new_target["system_role"] != "PLAYER" or new_target["status"] != "ACTIVE":
                raise TeamValidationError("Target user is not an eligible active player")
            new_cap_membership = self._db.execute(
                "SELECT * FROM team_memberships WHERE team_id = ? AND user_id = ? AND left_at IS NULL",
                (team_id, new_captain_user_id)).fetchone()
            if not new_cap_membership or new_cap_membership["team_role"] != "MEMBER":
                raise TeamConflict("Target user must be an active member of this team")
            # Demote old captain first (satisfying UNIQUE captain index), then promote new captain
            self._db.execute("UPDATE team_memberships SET team_role = 'MEMBER' WHERE id = ?", (old_cap["id"],))
            self._db.execute("UPDATE team_memberships SET team_role = 'CAPTAIN' WHERE id = ?", (new_cap_membership["id"],))
            self._db.execute("UPDATE teams SET updated_at = ? WHERE id = ?", (now, team_id))
            self._audit(now, user["id"], "TEAM_CAPTAIN_TRANSFERRED", "team", team_id,
                        old_captain_id=user["id"], new_captain_id=new_captain_user_id)
            demoted = TeamMember(
                id=old_cap["id"], team_id=team_id, user_id=user["id"],
                username=user["username"], display_name=user["display_name"],
                team_role="MEMBER", joined_at=old_cap["joined_at"], left_at=None)
            promoted = TeamMember(
                id=new_cap_membership["id"], team_id=team_id, user_id=new_captain_user_id,
                username=new_target["username"], display_name=new_target["display_name"],
                team_role="CAPTAIN", joined_at=new_cap_membership["joined_at"], left_at=None)
            return demoted, promoted

    def admin_list_teams(self, actor: Principal) -> list[Team]:
        self._ready()
        now = self._now()
        self._auth.require_actor(actor, now, admin=True, touch=False)
        rows = self._db.execute("SELECT * FROM teams ORDER BY created_at DESC").fetchall()
        return [self._team_dto(row) for row in rows]

    def admin_get_team(self, actor: Principal, team_id: str) -> dict:
        self._ready()
        now = self._now()
        self._auth.require_actor(actor, now, admin=True, touch=False)
        team_row = self._db.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone()
        if not team_row:
            raise TeamNotFound("Team not found")
        team_dto = self._team_dto(team_row)
        members = self.list_members(actor, team_id, include_history=True)
        invitations = self._db.execute("""
            SELECT i.id, i.team_id, t.slug as team_slug, t.display_name as team_display_name,
                   i.invited_user_id, u_target.username as invited_username,
                   i.invited_by, u_inviter.username as invited_by_username,
                   i.status, i.created_at, i.expires_at, i.responded_at
            FROM team_invitations i
            JOIN teams t ON i.team_id = t.id
            JOIN users u_target ON i.invited_user_id = u_target.id
            JOIN users u_inviter ON i.invited_by = u_inviter.id
            WHERE i.team_id = ?
            ORDER BY i.created_at DESC
        """, (team_id,)).fetchall()
        inv_dtos = [
            TeamInvitation(
                id=row["id"], team_id=row["team_id"], team_slug=row["team_slug"],
                team_display_name=row["team_display_name"], invited_user_id=row["invited_user_id"],
                invited_username=row["invited_username"], invited_by=row["invited_by"],
                invited_by_username=row["invited_by_username"], status=row["status"],
                created_at=row["created_at"], expires_at=row["expires_at"],
                responded_at=row["responded_at"])
            for row in invitations
        ]
        return {"team": team_dto, "members": members, "invitations": inv_dtos}

    def admin_transfer_captain(self, actor: Principal, team_id: str, new_captain_user_id: str) -> tuple[TeamMember | None, TeamMember]:
        self._ready()
        with transaction(self._db):
            now = self._now()
            admin = self._auth.require_actor(actor, now, admin=True)
            team_row = self._db.execute("SELECT * FROM teams WHERE id = ?", (team_id,)).fetchone()
            if not team_row:
                raise TeamNotFound("Team not found")
            if team_row["status"] == "ARCHIVED":
                raise TeamConflict("Cannot modify an archived team")
            new_target = self._db.execute("SELECT * FROM users WHERE id = ?", (new_captain_user_id,)).fetchone()
            if not new_target or new_target["system_role"] != "PLAYER" or new_target["status"] != "ACTIVE":
                raise TeamValidationError("Target user is not an eligible active player")
            new_cap_membership = self._db.execute(
                "SELECT * FROM team_memberships WHERE team_id = ? AND user_id = ? AND left_at IS NULL",
                (team_id, new_captain_user_id)).fetchone()
            if not new_cap_membership or new_cap_membership["team_role"] != "MEMBER":
                raise TeamConflict("Target user must be an active member of this team")
            old_cap = self._db.execute(
                "SELECT * FROM team_memberships WHERE team_id = ? AND left_at IS NULL AND team_role = 'CAPTAIN'",
                (team_id,)).fetchone()
            if old_cap:
                captain = self._db.execute("SELECT status, system_role FROM users WHERE id=?", (old_cap["user_id"],)).fetchone()
                if captain and captain["status"] == "ACTIVE" and captain["system_role"] == "PLAYER":
                    raise TeamConflict("Active Captain does not require Admin recovery")
            demoted = None
            if old_cap:
                self._db.execute("UPDATE team_memberships SET team_role = 'MEMBER' WHERE id = ?", (old_cap["id"],))
                old_user = self._db.execute("SELECT * FROM users WHERE id = ?", (old_cap["user_id"],)).fetchone()
                demoted = TeamMember(
                    id=old_cap["id"], team_id=team_id, user_id=old_cap["user_id"],
                    username=old_user["username"] if old_user else "unknown",
                    display_name=old_user["display_name"] if old_user else "unknown",
                    team_role="MEMBER", joined_at=old_cap["joined_at"], left_at=None)
            self._db.execute("UPDATE team_memberships SET team_role = 'CAPTAIN' WHERE id = ?", (new_cap_membership["id"],))
            self._db.execute("UPDATE teams SET updated_at = ? WHERE id = ?", (now, team_id))
            self._audit(now, admin["id"], "ADMIN_TEAM_RECOVERY_TRANSFER", "team", team_id,
                        old_captain_id=old_cap["user_id"] if old_cap else None,
                        new_captain_id=new_captain_user_id)
            promoted = TeamMember(
                id=new_cap_membership["id"], team_id=team_id, user_id=new_captain_user_id,
                username=new_target["username"], display_name=new_target["display_name"],
                team_role="CAPTAIN", joined_at=new_cap_membership["joined_at"], left_at=None)
            return demoted, promoted
