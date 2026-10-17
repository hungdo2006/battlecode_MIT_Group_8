"""Phase B.2: trusted in-process account/session core, NO HTTP integration.

Inject a checked SQLite connection and its already-held WriterLock. Principals
must come from server-side session validation, never from request JSON. Methods
re-read their session/account authorization under the mutation transaction.
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import lru_cache
import hashlib
import json
import math
import re
import secrets
import sqlite3
import threading
import time
from typing import Protocol
import uuid

from .account_database import require_writer, transaction, validate_service_connection
from .account_identity import display_name, normalize_username
from . import passwords


class AuthenticationFailed(ValueError):
    def __init__(self):
        super().__init__("Invalid credentials")


class InvalidSession(ValueError):
    def __init__(self):
        super().__init__("Invalid session")


class InvalidInvitation(ValueError):
    def __init__(self):
        super().__init__("Invalid or unavailable invitation")


class PermissionDenied(ValueError):
    def __init__(self):
        super().__init__("Not authorized")


class AccountConflict(ValueError):
    pass


class AuthenticationBusy(RuntimeError):
    """Capacity/rate limit failure is not a wrong password or a bot fault."""


def _positive_seconds(value):
    if type(value) is not int or not 0 < value <= 365 * 86400:
        raise ValueError("TTL must be an integer from 1 second to 365 days")
    return value


@dataclass(frozen=True)
class SessionTTL:
    absolute: int
    idle: int

    def __post_init__(self):
        _positive_seconds(self.absolute)
        _positive_seconds(self.idle)
        if self.idle > self.absolute:
            raise ValueError("Idle TTL must not exceed absolute TTL")


@dataclass(frozen=True)
class AuthPolicy:
    # Review defaults, not a production configuration approved for Internet use.
    player: SessionTTL = SessionTTL(8 * 3600, 3600)
    admin: SessionTTL = SessionTTL(4 * 3600, 15 * 60)
    invitation_seconds: int = 24 * 3600

    def __post_init__(self):
        if not isinstance(self.player, SessionTTL) or not isinstance(self.admin, SessionTTL):
            raise ValueError("Player/Admin TTL must be SessionTTL")
        _positive_seconds(self.invitation_seconds)

    def session_ttl(self, audience):
        return {"PLAYER": self.player, "ADMIN": self.admin}[audience]


@dataclass(frozen=True)
class Account:
    id: str
    username: str
    display_name: str
    system_role: str
    status: str
    auth_version: int


@dataclass(frozen=True)
class Principal:
    account: Account
    audience: str
    session_id: str = field(repr=False)
    # Not serializable proof of server-side validation. A DTO reconstructed from
    # request fields is not an authenticated actor, even with a real session ID.
    _proof: object = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class SessionGrant:
    principal: Principal
    expires_at: int
    token: str = field(repr=False)


@dataclass(frozen=True)
class InvitationGrant:
    account: Account
    invitation_id: str
    expires_at: int
    token: str = field(repr=False)


@dataclass(frozen=True)
class LoginAttempt:
    username_key: str  # SHA-256 of canonical username, not password or token
    source_key: str    # MUST be supplied by trusted server/proxy integration
    audience: str


class LoginLimiter(Protocol):
    """B.3 must inject a real limiter; there is deliberately no allow-all default.

    check() raises AuthenticationBusy when limited. record() must not raise and
    must never receive credentials. Use trusted source + username + audience.
    """
    def check(self, attempt: LoginAttempt) -> None: ...
    def record(self, attempt: LoginAttempt, *, succeeded: bool) -> None: ...


class PasswordWorkLimiter:
    """Shared process capacity, no unbounded waiting queue for expensive Argon2."""
    def __init__(self, max_parallel=1):
        if type(max_parallel) is not int or max_parallel < 1:
            raise ValueError("Password parallelism must be a positive integer")
        self._slots = threading.BoundedSemaphore(max_parallel)

    @contextmanager
    def slot(self):
        if not self._slots.acquire(blocking=False):
            raise AuthenticationBusy("Password verification capacity unavailable")
        try:
            yield
        finally:
            self._slots.release()


_PASSWORD_WORK = PasswordWorkLimiter()
_PRINCIPAL_PROOF = object()


@lru_cache(maxsize=1)
def _dummy_hash():
    # Lazy, under the same work limiter; no hashing/database IO at module import.
    # Only for timing equalization. This password is never an account credential.
    with _PASSWORD_WORK.slot():
        return passwords.hash_password("Timing equalization only; never an account password")


def _token_hash(token):
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        return None
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _account(row):
    return Account(*(row[key] for key in ("id", "username", "display_name", "system_role", "status", "auth_version")))


class AuthService:
    def __init__(self, connection, writer_lock, *, login_limiter: LoginLimiter,
                 policy=None, clock=time.time, password_work=None):
        validate_service_connection(connection, writer_lock)
        if not callable(getattr(login_limiter, "check", None)) or not callable(getattr(login_limiter, "record", None)):
            raise ValueError("An explicit LoginLimiter is required")
        connection.row_factory = sqlite3.Row
        self._db, self._writer = connection, writer_lock
        self._data_dir = writer_lock.path.parent
        self.policy = AuthPolicy() if policy is None else policy
        if not isinstance(self.policy, AuthPolicy):
            raise ValueError("policy must be AuthPolicy")
        self._clock, self._limiter = clock, login_limiter
        self._work = password_work or _PASSWORD_WORK
        # Cached initialization must not make validation/logout wait for an
        # unrelated password verification when B.3 uses per-thread connections.
        self._dummy = _dummy_hash()

    def _ready(self):
        require_writer(self._writer, self._data_dir)
        if self._db.in_transaction:
            raise RuntimeError("AuthService must not run inside a caller transaction")
        if self._db.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            raise RuntimeError("AuthService connection must keep foreign keys enabled")

    def _now(self):
        now = self._clock()
        if type(now) not in (int, float) or not math.isfinite(now) or not 0 <= now < 2 ** 62:
            raise RuntimeError("Invalid server clock")
        return int(now)

    def _user(self, user_id):
        return self._db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    def get_account(self, user_id):
        self._ready()
        row = self._user(user_id)
        return _account(row) if row else None

    def get_account_by_username(self, username):
        self._ready()
        row = self._db.execute("SELECT * FROM users WHERE username = ?", (normalize_username(username),)).fetchone()
        return _account(row) if row else None

    def _audit(self, now, actor_id, action, target_type, target_id, **details):
        self._db.execute("""INSERT INTO audit_events (
            occurred_at, actor_user_id, action, target_type, target_id, details_json)
            VALUES (?, ?, ?, ?, ?, ?)""", (now, actor_id, action, target_type, target_id, json.dumps(details)))

    def _session(self, session_id, audience, now):
        session = self._db.execute("SELECT * FROM auth_sessions WHERE id = ?", (session_id,)).fetchone()
        user = self._user(session["user_id"]) if session else None
        if (not session or not user or audience not in ("PLAYER", "ADMIN")
                or session["audience"] != audience or user["system_role"] != audience
                or user["status"] != "ACTIVE" or session["auth_version"] != user["auth_version"]
                or session["revoked_at"] is not None):
            raise InvalidSession()
        seen = session["last_seen_at"] if session["last_seen_at"] is not None else session["created_at"]
        if (now < session["created_at"] or now < seen or now >= session["expires_at"]
                or now >= seen + session["idle_timeout_seconds"]):
            raise InvalidSession()
        return session, user

    def _require_actor(self, actor, now, *, admin=False):
        if (not isinstance(actor, Principal) or not isinstance(actor.account, Account)
                or actor._proof is not _PRINCIPAL_PROOF):
            raise PermissionDenied()
        try:
            session, user = self._session(actor.session_id, actor.audience, now)
        except InvalidSession:
            raise PermissionDenied() from None
        # Claimed role/status in a DTO grant no rights. Re-query the real account.
        if user["id"] != actor.account.id or (admin and user["system_role"] != "ADMIN"):
            raise PermissionDenied()
        self._db.execute("UPDATE auth_sessions SET last_seen_at = ? WHERE id = ?", (now, session["id"]))
        return user

    def issue_invitation(self, actor, username, *, name=None, ttl_seconds=None):
        self._ready()
        username = normalize_username(username)
        name = display_name(name if name is not None else username)
        ttl = _positive_seconds(ttl_seconds if ttl_seconds is not None else self.policy.invitation_seconds)
        with transaction(self._db):
            now = self._now()
            admin = self._require_actor(actor, now, admin=True)
            if self._db.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
                raise AccountConflict("Username is already reserved")
            user_id = uuid.uuid4().hex
            self._db.execute("""INSERT INTO users (id, username, display_name, system_role,
                status, created_at, updated_at) VALUES (?, ?, ?, 'PLAYER', 'INVITED', ?, ?)""",
                (user_id, username, name, now, now))
            return self._issue_invitation(admin["id"], user_id, now, ttl)

    def _issue_invitation(self, admin_id, user_id, now, ttl):
        token, token_id = secrets.token_urlsafe(32), uuid.uuid4().hex
        self._db.execute("""INSERT INTO account_tokens (
            id, token_hash, purpose, user_id, created_by, created_at, expires_at)
            VALUES (?, ?, 'ACCOUNT_INVITE', ?, ?, ?, ?)""",
            (token_id, _token_hash(token), user_id, admin_id, now, now + ttl))
        self._audit(now, admin_id, "ACCOUNT_INVITED", "user", user_id, invitation_id=token_id)
        return InvitationGrant(_account(self._user(user_id)), token_id, now + ttl, token)

    def reissue_invitation(self, actor, user_id, *, ttl_seconds=None):
        self._ready()
        ttl = _positive_seconds(ttl_seconds if ttl_seconds is not None else self.policy.invitation_seconds)
        with transaction(self._db):
            now = self._now()
            admin = self._require_actor(actor, now, admin=True)
            user = self._user(user_id)
            if not user or user["status"] != "INVITED" or user["system_role"] != "PLAYER":
                raise InvalidInvitation()
            self._db.execute("""UPDATE account_tokens SET revoked_at = ? WHERE user_id = ?
                AND purpose = 'ACCOUNT_INVITE' AND consumed_at IS NULL AND revoked_at IS NULL""", (now, user_id))
            return self._issue_invitation(admin["id"], user_id, now, ttl)

    def revoke_invitation(self, actor, invitation_id):
        self._ready()
        with transaction(self._db):
            now = self._now()
            admin = self._require_actor(actor, now, admin=True)
            row = self._db.execute("""SELECT * FROM account_tokens WHERE id = ?
                AND purpose = 'ACCOUNT_INVITE'""", (invitation_id,)).fetchone()
            if not row:
                raise InvalidInvitation()
            if row["consumed_at"] is not None or row["revoked_at"] is not None:
                return False
            self._db.execute("UPDATE account_tokens SET revoked_at = ? WHERE id = ?", (now, invitation_id))
            self._audit(now, admin["id"], "ACCOUNT_INVITATION_REVOKED", "account_token", invitation_id)
            return True

    def _invited_user(self, digest, now):
        row = self._db.execute("""SELECT * FROM account_tokens WHERE token_hash = ?
            AND purpose = 'ACCOUNT_INVITE'""", (digest,)).fetchone()
        user = self._user(row["user_id"]) if row else None
        if (not row or not user or row["consumed_at"] is not None or row["revoked_at"] is not None
                or now < row["created_at"] or now >= row["expires_at"]
                or user["status"] != "INVITED" or user["system_role"] != "PLAYER"):
            raise InvalidInvitation()
        return row, user

    def activate(self, token, password):
        self._ready()
        digest = _token_hash(token)
        if digest is None:
            raise InvalidInvitation()
        original_token, original_user = self._invited_user(digest, self._now())
        # No SQLite transaction while hashing. Consume/re-check after Argon2.
        with self._work.slot():
            encoded = passwords.hash_password(password)
        self._ready()
        with transaction(self._db):
            now = self._now()
            invitation, user = self._invited_user(digest, now)
            if (invitation["id"] != original_token["id"] or user["id"] != original_user["id"]
                    or user["auth_version"] != original_user["auth_version"]):
                raise InvalidInvitation()
            self._db.execute("UPDATE account_tokens SET consumed_at = ? WHERE id = ?", (now, invitation["id"]))
            self._db.execute("""UPDATE users SET status = 'ACTIVE', password_hash = ?,
                auth_version = auth_version + 1, updated_at = ?, password_changed_at = ? WHERE id = ?""",
                (encoded, now, now, user["id"]))
            self._audit(now, user["id"], "ACCOUNT_ACTIVATED", "user", user["id"])
            return _account(self._user(user["id"]))

    def login(self, username, password, *, audience, source_key):
        self._ready()
        if audience not in ("PLAYER", "ADMIN"):
            raise AuthenticationFailed()
        if not isinstance(source_key, str) or not 1 <= len(source_key) <= 256:
            raise ValueError("A trusted source_key is required")
        try:
            canonical = normalize_username(username)
        except ValueError:
            canonical = None
        attempt = LoginAttempt(hashlib.sha256((canonical or "<invalid>").encode()).hexdigest(), source_key, audience)
        self._limiter.check(attempt)
        try:
            grant = self._login(canonical, password, audience)
        except AuthenticationFailed:
            self._limiter.record(attempt, succeeded=False)
            raise
        self._limiter.record(attempt, succeeded=True)
        return grant

    def _login(self, username, password, audience):
        original = self._db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        eligible = original and original["status"] == "ACTIVE" and original["system_role"] == audience
        with self._work.slot():
            verified = passwords.verify_password(original["password_hash"] if eligible else self._dummy, password)
        if not verified or not eligible:
            raise AuthenticationFailed()
        self._ready()
        with transaction(self._db):
            now = self._now()
            user = self._user(original["id"])
            if (not user or user["status"] != "ACTIVE" or user["system_role"] != audience
                    or user["auth_version"] != original["auth_version"]
                    or user["password_hash"] != original["password_hash"] or now < user["created_at"]):
                raise AuthenticationFailed()
            token, session_id = secrets.token_urlsafe(32), uuid.uuid4().hex
            ttl = self.policy.session_ttl(audience)
            self._db.execute("""INSERT INTO auth_sessions (id, token_hash, user_id, audience,
                auth_version, created_at, expires_at, last_seen_at, idle_timeout_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", (session_id, _token_hash(token), user["id"], audience,
                user["auth_version"], now, now + ttl.absolute, now, ttl.idle))
            self._audit(now, user["id"], "SESSION_CREATED", "auth_session", session_id, audience=audience)
            return SessionGrant(Principal(_account(user), audience, session_id, _PRINCIPAL_PROOF), now + ttl.absolute, token)

    def validate_session(self, token, *, audience, touch=True):
        self._ready()
        digest = _token_hash(token)
        if digest is None:
            raise InvalidSession()
        with transaction(self._db):
            now = self._now()
            row = self._db.execute("SELECT id FROM auth_sessions WHERE token_hash = ?", (digest,)).fetchone()
            if not row:
                raise InvalidSession()
            session, user = self._session(row["id"], audience, now)
            if touch:
                self._db.execute("UPDATE auth_sessions SET last_seen_at = ? WHERE id = ?", (now, session["id"]))
            return Principal(_account(user), audience, session["id"], _PRINCIPAL_PROOF)

    def logout(self, token, *, audience):
        self._ready()
        digest = _token_hash(token)
        if digest is None:
            return False
        with transaction(self._db):
            row = self._db.execute("""SELECT * FROM auth_sessions WHERE token_hash = ?
                AND audience = ? AND revoked_at IS NULL""", (digest, audience)).fetchone()
            if not row:
                return False
            now = max(self._now(), row["created_at"])
            self._db.execute("UPDATE auth_sessions SET revoked_at = ? WHERE id = ?", (now, row["id"]))
            self._audit(now, row["user_id"], "SESSION_LOGOUT", "auth_session", row["id"])
            return True

    def revoke_all(self, actor, *, user_id=None):
        self._ready()
        with transaction(self._db):
            now = self._now()
            caller = self._require_actor(actor, now)
            target = user_id if user_id is not None else caller["id"]
            if target != caller["id"] and caller["system_role"] != "ADMIN":
                raise PermissionDenied()
            if not self._user(target):
                raise AccountConflict("Account is unavailable")
            self._invalidate_user(target, now)
            self._audit(now, caller["id"], "USER_SESSIONS_REVOKED", "user", target)

    def _invalidate_user(self, user_id, now):
        self._db.execute("""UPDATE users SET auth_version = auth_version + 1,
            updated_at = ? WHERE id = ?""", (now, user_id))
        self._db.execute("UPDATE auth_sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL", (now, user_id))

    def disable_account(self, actor, user_id):
        self._ready()
        with transaction(self._db):
            now = self._now()
            admin = self._require_actor(actor, now, admin=True)
            user = self._user(user_id)
            if not user:
                raise AccountConflict("Account is unavailable")
            if user["status"] == "DISABLED":
                return False
            self._invalidate_user(user_id, now)
            self._db.execute("UPDATE users SET status = 'DISABLED' WHERE id = ?", (user_id,))
            self._db.execute("""UPDATE account_tokens SET revoked_at = ? WHERE user_id = ?
                AND consumed_at IS NULL AND revoked_at IS NULL""", (now, user_id))
            self._audit(now, admin["id"], "ACCOUNT_DISABLED", "user", user_id)
            return True
