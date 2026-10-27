"""Account service tests: temp datasets, injected clocks, no HTTP/real secrets."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import hashlib
import os
from pathlib import Path
import sqlite3
import secrets
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from backend import account_database, passwords
from backend.account_database import AccountDatabase, SchemaError, check_integrity, transaction
from backend.admin_cli import bootstrap_admin
from backend.auth_service import (
    AccountConflict, AuthenticationBusy, AuthenticationFailed, AuthPolicy, AuthService,
    InvalidInvitation, InvalidSession, PasswordWorkLimiter, PermissionDenied, Principal, SessionTTL,
)
from backend.writer_lock import WriterAlreadyRunning, WriterLock


PASSWORD = "test-only player account passphrase 73"


class Clock:
    def __init__(self):
        self.now = 2_000_000_000

    def __call__(self):
        return self.now


class TestLimiter:
    __test__ = False

    def __init__(self):
        self.checked, self.results = [], []
        self.block = False

    def check(self, attempt):
        self.checked.append(attempt)
        if self.block:
            raise AuthenticationBusy("Test rate limit reached")

    def record(self, attempt, *, succeeded):
        self.results.append((attempt, succeeded))


@pytest.fixture
def env(tmp_path):
    data = tmp_path / "data"
    admin_id = bootstrap_admin(data, "admin", PASSWORD)
    clock, limiter = Clock(), TestLimiter()
    database = AccountDatabase(data)
    with WriterLock(data) as writer:
        with database.writer_connection(writer) as connection:
            service = AuthService(connection, writer, clock=clock, login_limiter=limiter)
            admin = service.login("admin", PASSWORD, audience="ADMIN", source_key="test-server-peer").principal
            yield SimpleNamespace(service=service, connection=connection, writer=writer, clock=clock,
                                  database=database, limiter=limiter, admin=admin, admin_id=admin_id)


def player(env, name="alice"):
    invitation = env.service.issue_invitation(env.admin, name)
    account = env.service.activate(invitation.token, PASSWORD)
    return account


def login_player(env, name="alice"):
    return env.service.login(name, PASSWORD, audience="PLAYER", source_key="test-server-peer")


def test_issue_and_activate_bound_player_invitation(env):
    invitation = env.service.issue_invitation(env.admin, " Alice ", name="Alice Team Member")
    account = env.service.get_account(invitation.account.id)
    assert account.status == "INVITED" and account.system_role == "PLAYER"
    assert account.username == "alice"
    assert env.service.get_account_by_username("ALICE") == account
    assert env.service.get_account("missing") is None
    assert env.service.get_account_by_username("not-found") is None
    activated = env.service.activate(invitation.token, PASSWORD)
    assert activated.id == account.id and activated.status == "ACTIVE"
    assert activated.system_role == "PLAYER" and activated.auth_version == account.auth_version + 1
    stored = env.connection.execute("SELECT * FROM account_tokens WHERE id=?", (invitation.invitation_id,)).fetchone()
    assert stored["consumed_at"] == env.clock.now
    actions = {row[0] for row in env.connection.execute("SELECT action FROM audit_events")}
    assert {"ACCOUNT_INVITED", "ACCOUNT_ACTIVATED"} <= actions


@pytest.mark.parametrize("failure", ["invalid", "malformed", "expired", "revoked", "consumed", "disabled"])
def test_invitation_rejected_in_all_invalid_states(env, failure):
    invitation = env.service.issue_invitation(env.admin, "alice", ttl_seconds=10)
    token = invitation.token
    if failure == "invalid":
        token = "z" * 43
    elif failure == "malformed":
        token = "not-a-token"
    elif failure == "expired":
        env.clock.now += 10  # exact expiry boundary, no sleep
    elif failure == "revoked":
        assert env.service.revoke_invitation(env.admin, invitation.invitation_id)
    elif failure == "consumed":
        env.service.activate(token, PASSWORD)
    else:
        env.service.disable_account(env.admin, invitation.account.id)
    with pytest.raises(InvalidInvitation, match="Invalid or unavailable invitation"):
        env.service.activate(token, PASSWORD)
    assert env.connection.execute("SELECT count(*) FROM users WHERE username='alice'").fetchone()[0] == 1


def test_reissue_is_admin_only_and_invalidates_previous_tokens(env):
    first = env.service.issue_invitation(env.admin, "alice")
    assert env.service.revoke_invitation(env.admin, first.invitation_id)
    assert not env.service.revoke_invitation(env.admin, first.invitation_id)
    second = env.service.reissue_invitation(env.admin, first.account.id)
    third = env.service.reissue_invitation(env.admin, first.account.id)
    assert third.account.id == first.account.id
    for old in (first, second):
        with pytest.raises(InvalidInvitation):
            env.service.activate(old.token, PASSWORD)
    env.service.activate(third.token, PASSWORD)
    with pytest.raises(InvalidInvitation):
        env.service.reissue_invitation(env.admin, first.account.id)


def test_duplicate_usernames_and_role_escalation_are_blocked(env):
    invitation = env.service.issue_invitation(env.admin, "alice")
    for name in ("ALICE", "admin"):
        with pytest.raises(AccountConflict):
            env.service.issue_invitation(env.admin, name)
    with pytest.raises(TypeError):
        env.service.issue_invitation(env.admin, "other", role="ADMIN")
    with pytest.raises(TypeError):
        env.service.activate(invitation.token, PASSWORD, role="ADMIN", user_id=env.admin_id)
    account = env.service.activate(invitation.token, PASSWORD)
    member = login_player(env).principal
    fake = replace(member, account=replace(member.account, system_role="ADMIN", status="ACTIVE"))
    for actor in (None, {"user_id": env.admin_id, "role": "ADMIN"}, member, fake,
                  replace(member, account=env.admin.account), replace(member, audience="ADMIN"),
                  Principal(env.admin.account, "ADMIN", env.admin.session_id)):
        with pytest.raises(PermissionDenied):
            env.service.issue_invitation(actor, "other")
    assert account.system_role == "PLAYER"
    assert env.connection.execute("SELECT count(*) FROM users WHERE system_role='ADMIN'").fetchone()[0] == 1


def test_stale_admin_principal_cannot_administer_accounts(env):
    env.service.revoke_all(env.admin)
    with pytest.raises(PermissionDenied):
        env.service.issue_invitation(env.admin, "alice")


def test_all_admin_account_operations_reject_player_actors(env):
    pending = env.service.issue_invitation(env.admin, "pending")
    player(env)
    actor = login_player(env).principal
    for operation in (
        lambda: env.service.reissue_invitation(actor, pending.account.id),
        lambda: env.service.revoke_invitation(actor, pending.invitation_id),
        lambda: env.service.disable_account(actor, env.admin_id),
    ):
        with pytest.raises(PermissionDenied):
            operation()
    assert env.service.get_account(pending.account.id).status == "INVITED"
    assert env.service.get_account(env.admin_id).status == "ACTIVE"


@pytest.mark.parametrize("binding", ["admin", "wrong_purpose"])
def test_activation_never_promotes_admin_or_consumes_other_token_purposes(env, binding):
    pending = env.service.issue_invitation(env.admin, "pending")
    token = secrets.token_urlsafe(32)
    target = env.admin_id if binding == "admin" else pending.account.id
    purpose = "ACCOUNT_INVITE" if binding == "admin" else "PASSWORD_RESET"
    if binding == "admin":
        env.connection.execute("UPDATE users SET status='INVITED' WHERE id=?", (target,))
    env.connection.execute("""INSERT INTO account_tokens (
        id, token_hash, purpose, user_id, created_at, expires_at) VALUES ('foreign', ?, ?, ?, ?, ?)""",
        (hashlib.sha256(token.encode()).hexdigest(), purpose, target, env.clock.now, env.clock.now + 60))
    with pytest.raises(InvalidInvitation):
        env.service.activate(token, PASSWORD)
    assert env.connection.execute("SELECT consumed_at FROM account_tokens WHERE id='foreign'").fetchone()[0] is None


@pytest.mark.parametrize("case", ["wrong_password", "unknown", "invited", "disabled", "invalid_username", "wrong_audience"])
def test_generic_credential_failure(env, case):
    invitation = env.service.issue_invitation(env.admin, "alice")
    if case != "invited":
        env.service.activate(invitation.token, PASSWORD)
    if case == "disabled":
        env.service.disable_account(env.admin, invitation.account.id)
    username, password, audience = "alice", PASSWORD, "PLAYER"
    if case == "unknown":
        username = "unknown"
    elif case == "invalid_username":
        username = "invalid username!"
    elif case == "wrong_password":
        password = PASSWORD + "wrong"
    elif case == "wrong_audience":
        audience = "ADMIN"
    before = env.connection.execute("SELECT count(*) FROM auth_sessions").fetchone()[0]
    with pytest.raises(AuthenticationFailed) as error:
        env.service.login(username, password, audience=audience, source_key="test-peer")
    assert str(error.value) == "Invalid credentials"
    assert env.limiter.results[-1][1] is False
    assert env.connection.execute("SELECT count(*) FROM auth_sessions").fetchone()[0] == before


def test_sessions_are_opaque_and_audience_bound(env):
    account = player(env)
    grant = login_player(env)
    assert len(grant.token) == 43 and "." not in grant.token
    principal = env.service.validate_session(grant.token, audience="PLAYER")
    assert principal.account == account
    assert grant.expires_at == env.clock.now + 8 * 3600
    row = env.connection.execute("SELECT * FROM auth_sessions WHERE id=?", (principal.session_id,)).fetchone()
    assert row["idle_timeout_seconds"] == 3600
    with pytest.raises(InvalidSession):
        env.service.validate_session(grant.token, audience="ADMIN")
    with pytest.raises(AuthenticationFailed):
        env.service.login("admin", PASSWORD, audience="PLAYER", source_key="peer")
    admin = env.service.login("admin", PASSWORD, audience="ADMIN", source_key="peer")
    assert admin.expires_at == env.clock.now + 8 * 3600
    assert env.service.validate_session(admin.token, audience="ADMIN").account.id == env.admin_id
    assert env.connection.execute("SELECT idle_timeout_seconds FROM auth_sessions WHERE id=?", (admin.principal.session_id,)).fetchone()[0] == 3600


@pytest.mark.parametrize("case", ["idle", "absolute", "revoked", "version", "disabled", "role", "clock_rewind"])
def test_invalid_session_states(env, case):
    player(env)
    grant = login_player(env)
    if case == "idle":
        env.clock.now += 3600
    elif case == "absolute":
        # Keep idle fresh so this isolates the absolute deadline.
        for _ in range(8 * 2):
            env.clock.now += 1800
            if env.clock.now < grant.expires_at:
                env.service.validate_session(grant.token, audience="PLAYER")
    elif case == "revoked":
        env.connection.execute("UPDATE auth_sessions SET revoked_at=created_at WHERE id=?", (grant.principal.session_id,))
    elif case == "version":
        env.connection.execute("UPDATE users SET auth_version=auth_version+1 WHERE id=?", (grant.principal.account.id,))
    elif case == "disabled":
        env.service.disable_account(env.admin, grant.principal.account.id)
    elif case == "role":
        env.connection.execute("UPDATE users SET system_role='ADMIN' WHERE id=?", (grant.principal.account.id,))
    else:
        env.clock.now -= 1
    with pytest.raises(InvalidSession, match="Invalid session"):
        env.service.validate_session(grant.token, audience="PLAYER")


def test_session_touch_extends_idle_but_never_absolute_deadline(env):
    player(env)
    grant = login_player(env)
    env.clock.now += 3599
    env.service.validate_session(grant.token, audience="PLAYER")
    env.clock.now += 3599
    env.service.validate_session(grant.token, audience="PLAYER", touch=False)
    env.clock.now += 1  # no-touch validation must not extend idle
    with pytest.raises(InvalidSession):
        env.service.validate_session(grant.token, audience="PLAYER")


def test_logout_and_revoke_all_are_persistent_and_permission_checked(env):
    alice, bobby = player(env), player(env, "bobby")
    first, second = login_player(env), login_player(env)
    assert not env.service.logout(first.token, audience="ADMIN")
    assert env.service.logout(first.token, audience="PLAYER")
    assert not env.service.logout(first.token, audience="PLAYER")
    with pytest.raises(InvalidSession):
        env.service.validate_session(first.token, audience="PLAYER")
    with pytest.raises(PermissionDenied):
        env.service.revoke_all(second.principal, user_id=bobby.id)
    env.service.revoke_all(second.principal)  # self-service revocation
    with pytest.raises(InvalidSession):
        env.service.validate_session(second.token, audience="PLAYER")
    third, fourth = login_player(env), login_player(env)
    env.service.revoke_all(env.admin, user_id=alice.id)
    for grant in (third, fourth):
        with pytest.raises(InvalidSession):
            env.service.validate_session(grant.token, audience="PLAYER")
    assert env.service.get_account(alice.id).auth_version == alice.auth_version + 2


def test_no_plaintext_or_raw_token_is_persisted_or_logged(env, caplog, capsys):
    invitation = env.service.issue_invitation(env.admin, "alice")
    env.service.activate(invitation.token, PASSWORD)
    session = login_player(env)
    stored_invitation = env.connection.execute("SELECT token_hash FROM account_tokens WHERE id=?", (invitation.invitation_id,)).fetchone()[0]
    stored_session = env.connection.execute("SELECT token_hash FROM auth_sessions WHERE id=?", (session.principal.session_id,)).fetchone()[0]
    assert stored_invitation == hashlib.sha256(invitation.token.encode()).hexdigest()
    assert stored_session == hashlib.sha256(session.token.encode()).hexdigest()
    output = capsys.readouterr()
    text = output.out + output.err + caplog.text + repr(session) + repr(invitation) + repr(asdict(session.principal.account))
    raw_db = env.database.path.read_bytes()
    for secret in (invitation.token, session.token, PASSWORD, stored_session, stored_invitation):
        assert secret not in text
    for secret in (invitation.token, session.token, PASSWORD):
        assert secret.encode() not in raw_db
    assert not hasattr(session.principal.account, "password_hash")


def test_persistence_and_pinned_idle_policy_across_reopen(env):
    player(env)
    grant = login_player(env)
    with env.database.writer_connection(env.writer) as reopened:
        changed_policy = AuthPolicy(player=SessionTTL(24 * 3600, 8 * 3600))
        restored = AuthService(reopened, env.writer, clock=env.clock, login_limiter=TestLimiter(), policy=changed_policy)
        assert restored.validate_session(grant.token, audience="PLAYER").account.username == "alice"
        env.clock.now += 3600  # old session retains its original one-hour idle limit
        with pytest.raises(InvalidSession):
            restored.validate_session(grant.token, audience="PLAYER")


def test_weak_activation_password_does_not_consume_invitation(env):
    invitation = env.service.issue_invitation(env.admin, "alice")
    with pytest.raises(ValueError):
        env.service.activate(invitation.token, "short")
    assert env.service.get_account(invitation.account.id).status == "INVITED"
    assert env.connection.execute("SELECT consumed_at FROM account_tokens WHERE id=?", (invitation.invitation_id,)).fetchone()[0] is None
    assert env.service.activate(invitation.token, PASSWORD).status == "ACTIVE"


@pytest.mark.parametrize("mutation", ["invite", "activate", "login", "logout", "revoke_all", "disable"])
def test_audit_failure_rolls_back_entire_mutation(env, mutation):
    invitation = env.service.issue_invitation(env.admin, "alice")
    if mutation not in ("invite", "activate"):
        env.service.activate(invitation.token, PASSWORD)
    session = login_player(env) if mutation in ("logout", "revoke_all", "disable") else None
    def snapshot():
        return {table: [tuple(row) for row in env.connection.execute(f"SELECT * FROM {table} ORDER BY id")]
                for table in ("users", "account_tokens", "auth_sessions", "audit_events")}
    before = snapshot()
    env.connection.execute("""CREATE TEMP TRIGGER reject_audit BEFORE INSERT ON audit_events
        BEGIN SELECT RAISE(ABORT, 'test audit unavailable'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        if mutation == "invite":
            env.service.issue_invitation(env.admin, "bobby")
        elif mutation == "activate":
            env.service.activate(invitation.token, PASSWORD)
        elif mutation == "login":
            login_player(env)
        elif mutation == "logout":
            env.service.logout(session.token, audience="PLAYER")
        elif mutation == "revoke_all":
            env.service.revoke_all(env.admin, user_id=invitation.account.id)
        else:
            env.service.disable_account(env.admin, invitation.account.id)
    assert not env.connection.in_transaction
    assert snapshot() == before


def test_limiter_contract_and_no_password_work_when_rate_limited(env, monkeypatch):
    env.limiter.block = True
    monkeypatch.setattr(passwords, "verify_password", lambda *_: pytest.fail("Limited login must not calculate Argon2"))
    with pytest.raises(AuthenticationBusy):
        env.service.login("missing", PASSWORD, audience="PLAYER", source_key="trusted-peer")
    attempt = env.limiter.checked[-1]
    assert attempt.source_key == "trusted-peer"
    assert attempt.username_key == hashlib.sha256(b"missing").hexdigest()
    assert PASSWORD not in repr(attempt)


def test_password_work_capacity_is_bounded_and_recovers(env):
    work = PasswordWorkLimiter(1)
    service = AuthService(env.connection, env.writer, clock=env.clock, login_limiter=TestLimiter(), password_work=work)
    with work.slot():
        with pytest.raises(AuthenticationBusy):
            service.login("admin", PASSWORD, audience="ADMIN", source_key="trusted-peer")
    assert service.login("admin", PASSWORD, audience="ADMIN", source_key="trusted-peer").principal.account.id == env.admin_id


@pytest.mark.parametrize("mutation", ["disable", "version", "password"])
def test_login_rechecks_credentials_after_argon2_without_open_transaction(env, monkeypatch, mutation):
    account = player(env)
    real_verify = passwords.verify_password
    def verify(encoded, password):
        assert not env.connection.in_transaction
        result = real_verify(encoded, password)
        replacement = passwords.hash_password(PASSWORD + "changed") if mutation == "password" else None
        # Another server operation commits while this login computes its hash.
        with env.database.writer_connection(env.writer) as other:
            with transaction(other):
                if mutation == "disable":
                    other.execute("UPDATE users SET status='DISABLED' WHERE id=?", (account.id,))
                elif mutation == "version":
                    other.execute("UPDATE users SET auth_version=auth_version+1 WHERE id=?", (account.id,))
                else:
                    other.execute("UPDATE users SET password_hash=? WHERE id=?", (replacement, account.id))
        return result
    monkeypatch.setattr(passwords, "verify_password", verify)
    with pytest.raises(AuthenticationFailed):
        login_player(env)
    assert env.connection.execute("SELECT count(*) FROM auth_sessions WHERE user_id=?", (account.id,)).fetchone()[0] == 0


def test_competing_activations_consume_once_on_independent_connections(env, monkeypatch):
    invitation = env.service.issue_invitation(env.admin, "alice")
    barrier, real_hash = threading.Barrier(2), passwords.hash_password
    def hash_after_rendezvous(password, **kwargs):
        barrier.wait(timeout=10)
        return real_hash(password, **kwargs)
    monkeypatch.setattr(passwords, "hash_password", hash_after_rendezvous)
    work = PasswordWorkLimiter(2)  # test two concurrent hashes; production default is one
    def activate():
        with env.database.writer_connection(env.writer) as connection:
            service = AuthService(connection, env.writer, clock=env.clock, login_limiter=TestLimiter(), password_work=work)
            try:
                return service.activate(invitation.token, PASSWORD).id
            except InvalidInvitation:
                return "rejected"
    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = executor.submit(activate), executor.submit(activate)
        outcomes = [first.result(timeout=15), second.result(timeout=15)]
    assert sorted(outcomes) == sorted([invitation.account.id, "rejected"])
    assert env.service.get_account(invitation.account.id).status == "ACTIVE"
    assert env.connection.execute("SELECT count(*) FROM users WHERE username='alice'").fetchone()[0] == 1
    assert env.connection.execute("SELECT count(*) FROM audit_events WHERE action='ACCOUNT_ACTIVATED'").fetchone()[0] == 1


def test_activation_rechecks_token_after_hashing(env, monkeypatch):
    invitation = env.service.issue_invitation(env.admin, "alice")
    real_hash = passwords.hash_password
    def revoke_during_hash(password, **kwargs):
        assert not env.connection.in_transaction
        result = real_hash(password, **kwargs)
        env.service.revoke_invitation(env.admin, invitation.invitation_id)
        return result
    monkeypatch.setattr(passwords, "hash_password", revoke_during_hash)
    with pytest.raises(InvalidInvitation):
        env.service.activate(invitation.token, PASSWORD)
    assert env.service.get_account(invitation.account.id).status == "INVITED"


def test_activation_token_expiring_during_argon2_is_not_consumed(env, monkeypatch):
    invitation = env.service.issue_invitation(env.admin, "alice", ttl_seconds=10)
    real_hash = passwords.hash_password
    def late_hash(password, **kwargs):
        assert not env.connection.in_transaction
        encoded = real_hash(password, **kwargs)
        env.clock.now += 10
        return encoded
    monkeypatch.setattr(passwords, "hash_password", late_hash)
    with pytest.raises(InvalidInvitation):
        env.service.activate(invitation.token, PASSWORD)
    assert env.service.get_account(invitation.account.id).status == "INVITED"
    assert env.connection.execute("SELECT consumed_at FROM account_tokens WHERE id=?", (invitation.invitation_id,)).fetchone()[0] is None


def test_service_uses_existing_lock_without_nested_acquisition_and_refuses_stale_lock(env):
    with pytest.raises(WriterAlreadyRunning):
        env.database.migrate()
    with env.database.writer_connection(env.writer) as connection:
        service = AuthService(connection, env.writer, clock=env.clock, login_limiter=TestLimiter())
        assert service.get_account(env.admin_id).id == env.admin_id
    unlocked = WriterLock(env.database.data_dir)
    with pytest.raises(RuntimeError, match="active WriterLock"):
        AuthService(env.connection, unlocked, login_limiter=TestLimiter())
    with WriterLock(env.database.data_dir.parent / "different-data") as wrong_lock:
        with pytest.raises(RuntimeError, match="active WriterLock"):
            AuthService(env.connection, wrong_lock, login_limiter=TestLimiter())


def test_missing_database_and_import_never_initialize_accounts(tmp_path):
    data = tmp_path / "missing"
    db = AccountDatabase(data)
    code = """
import sqlite3
def forbidden(*args, **kwargs):
    raise AssertionError('Database connection opened during import/startup construction')
sqlite3.connect = forbidden
import backend.auth_service
from backend.main import create_app
create_app()
"""
    root = Path(__file__).resolve().parents[1]
    child = subprocess.run([sys.executable, "-B", "-c", code], cwd=tmp_path,
                           env={**os.environ, "PYTHONPATH": str(root)}, capture_output=True, text=True, timeout=10)
    assert child.returncode == 0, child.stderr
    assert list(tmp_path.iterdir()) == []
    assert not data.exists()
    with WriterLock(data) as writer:
        with pytest.raises(sqlite3.OperationalError):
            with db.writer_connection(writer):
                pass
        assert not db.path.exists()


def test_service_cannot_be_used_after_its_outer_lock_is_released(env):
    env.writer.__exit__()
    with pytest.raises(RuntimeError, match="active WriterLock"):
        env.service.get_account(env.admin_id)


def test_core_does_not_modify_legacy_sessions_bots_or_replays(env):
    files = {"sessions.json": b'{"legacy":"keep"}', "bots.json": b'{"bot":"keep"}',
             "players.json": b'{}', "invitations.json": b'{"old":"invite"}',
             "rules.json": b'{"game":"keep"}', "matches.json": b'{"history":"keep"}',
             "replays/old.jsonl": b'{"turn":0}\n{"turn":1}\n'}
    for name, value in files.items():
        path = env.database.data_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    invitation = env.service.issue_invitation(env.admin, "alice")
    env.service.activate(invitation.token, PASSWORD)
    grant = login_player(env)
    env.service.validate_session(grant.token, audience="PLAYER")
    env.service.logout(grant.token, audience="PLAYER")
    env.service.disable_account(env.admin, invitation.account.id)
    assert all((env.database.data_dir / name).read_bytes() == value for name, value in files.items())
    assert env.connection.execute("SELECT count(*) FROM submission_ownership").fetchone()[0] == 0


def test_credential_change_contract_invalidates_old_sessions(env):
    account = player(env)
    old = login_player(env)
    encoded = passwords.hash_password(PASSWORD + "changed")  # outside transaction
    with transaction(env.connection):
        env.connection.execute("UPDATE users SET password_hash=?, auth_version=auth_version+1 WHERE id=?", (encoded, account.id))
    with pytest.raises(InvalidSession):
        env.service.validate_session(old.token, audience="PLAYER")
    with pytest.raises(AuthenticationFailed):
        login_player(env)
    new = env.service.login("alice", PASSWORD + "changed", audience="PLAYER", source_key="peer")
    assert env.service.validate_session(new.token, audience="PLAYER").account.id == account.id


def test_service_refuses_caller_transaction_or_foreign_keys_off(env):
    with transaction(env.connection):
        with pytest.raises(RuntimeError, match="caller transaction"):
            env.service.login("admin", PASSWORD, audience="ADMIN", source_key="peer")
    env.connection.execute("PRAGMA foreign_keys=OFF")
    try:
        with pytest.raises(SchemaError, match="foreign keys"):
            AuthService(env.connection, env.writer, login_limiter=TestLimiter())
    finally:
        env.connection.execute("PRAGMA foreign_keys=ON")


def test_session_ttls_are_configurable_and_checked(env):
    policy = AuthPolicy(player=SessionTTL(120, 20), admin=SessionTTL(60, 10), invitation_seconds=30)
    service = AuthService(env.connection, env.writer, clock=env.clock, login_limiter=TestLimiter(), policy=policy)
    admin = service.login("admin", PASSWORD, audience="ADMIN", source_key="peer")
    assert admin.expires_at == env.clock.now + 60
    invitation = service.issue_invitation(admin.principal, "short-ttl")
    assert invitation.expires_at == env.clock.now + 30
    env.clock.now += 10
    with pytest.raises(InvalidSession):
        service.validate_session(admin.token, audience="ADMIN")
    for args in [(0, 1), (1, 2), (True, 1), (2, 0)]:
        with pytest.raises(ValueError):
            SessionTTL(*args)


def test_v1_upgrade_preserves_accounts_and_revokes_only_unbounded_legacy_sql_sessions(tmp_path, monkeypatch):
    db = AccountDatabase(tmp_path)
    v1 = account_database.MIGRATIONS[:1]
    with monkeypatch.context() as patch:
        patch.setattr(account_database, "MIGRATIONS", v1)
        patch.setattr(account_database, "SCHEMA_VERSION", 1)
        admin_id = bootstrap_admin(tmp_path, "admin", PASSWORD)
        with db.maintenance() as connection:
            before_user = tuple(connection.execute("SELECT * FROM users").fetchone())
            before_ledger = tuple(connection.execute("SELECT * FROM schema_migrations").fetchone())
            connection.execute("""INSERT INTO auth_sessions VALUES (
                'manual', ?, ?, 'ADMIN', 1, 100, 9999999999, NULL, NULL)""", ("a" * 64, admin_id))
    with WriterLock(tmp_path) as writer:
        with pytest.raises(SchemaError, match="migration is required"):
            with db.writer_connection(writer):
                pass
    db.migrate()
    db.migrate()
    with db.read() as connection:
        assert tuple(connection.execute("SELECT * FROM users").fetchone()) == before_user
        assert tuple(connection.execute("SELECT * FROM schema_migrations WHERE version=1").fetchone()) == before_ledger
        manual = connection.execute("SELECT * FROM auth_sessions WHERE id='manual'").fetchone()
        assert manual["revoked_at"] is not None and manual["idle_timeout_seconds"] == 1
        assert connection.execute("PRAGMA user_version").fetchone()[0] == account_database.SCHEMA_VERSION
        check_integrity(connection)


def test_player_eight_character_policy_does_not_weaken_admin_passwords(env):
    short, valid = "seven77", "eight888"
    # Admin CLI uses the default strong policy even when Players can use 8.
    with pytest.raises(ValueError, match="at least 15"):
        passwords.hash_password(valid)
    with pytest.raises(ValueError, match="at least 8"):
        env.service.register_player("alice", None, None, short)
    assert env.service.get_account_by_username("alice") is None

    account = env.service.register_player("alice", None, None, valid)
    assert account.system_role == "PLAYER" and account.status == "ACTIVE"
    assert env.service.login("alice", valid, audience="PLAYER",
                             source_key="test-peer").principal.account.id == account.id

    invitation = env.service.issue_invitation(env.admin, "bob")
    with pytest.raises(ValueError, match="at least 8"):
        env.service.activate(invitation.token, short)
    assert env.service.activate(invitation.token, valid).status == "ACTIVE"

    grant = env.service.issue_player_recovery(env.admin, "alice")
    with pytest.raises(ValueError, match="at least 8"):
        env.service.reset_player_password(grant["token"], short)
    assert env.service.reset_player_password(grant["token"], "newpass8").id == account.id
    with pytest.raises(AuthenticationFailed):
        env.service.login("alice", valid, audience="PLAYER", source_key="test-peer")
    assert env.service.login("alice", "newpass8", audience="PLAYER",
                             source_key="test-peer").principal.account.id == account.id


def test_self_password_change_requires_current_password_and_revokes_all_sessions(env):
    player(env)
    first = login_player(env)
    second = login_player(env)
    with pytest.raises(AccountConflict, match="Mật khẩu hiện tại"):
        env.service.change_own_password(first.principal, "wrong current password", "new-player-password-24")
    assert env.service.validate_session(first.token, audience="PLAYER")
    assert env.service.change_own_password(first.principal, PASSWORD, "new-player-password-24")
    for grant in (first, second):
        with pytest.raises(InvalidSession):
            env.service.validate_session(grant.token, audience="PLAYER")
    with pytest.raises(AuthenticationFailed):
        env.service.login("alice", PASSWORD, audience="PLAYER", source_key="test-server-peer")
    assert env.service.login("alice", "new-player-password-24", audience="PLAYER",
                             source_key="test-server-peer").principal.account.username == "alice"


def test_admin_self_password_change_accepts_eight_character_minimum(env):
    with pytest.raises(ValueError, match="at least 8"):
        env.service.change_own_password(env.admin, PASSWORD, "seventh")
    assert env.service.change_own_password(env.admin, PASSWORD, "newpass8")
    with pytest.raises(PermissionDenied):
        env.service.require_actor(env.admin)
    assert env.service.login("admin", "newpass8", audience="ADMIN",
                             source_key="test-server-peer").principal.account.system_role == "ADMIN"
