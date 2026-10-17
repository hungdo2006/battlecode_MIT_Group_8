"""HTTP auth QA on disposable data; no real server, ports or account secrets."""
from concurrent.futures import ThreadPoolExecutor
import asyncio
from contextlib import contextmanager
from dataclasses import replace
import hashlib
import json
import sqlite3
import threading
from types import SimpleNamespace

import anyio

import pytest
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from backend import passwords
from backend.account_database import AccountDatabase, SchemaError, transaction
from backend.admin_cli import bootstrap_admin
from backend.auth_http import HTTPAuthSettings, MAX_BODY, cookie_name, cookie_path
from backend.auth_limits import AuthRateLimited, AuthRateLimiter, RateLimits
from backend.auth_service import AuthService, AuthPolicy, SessionTTL, _PASSWORD_WORK
from backend.main import create_app
from backend.network import NetworkSettings
from backend.writer_lock import WriterLock, WriterAlreadyRunning


PASSWORD = "test-only http authentication passphrase 93"
ORIGIN = "https://testserver"


class Clock:
    def __init__(self):
        self.now = 2_000_000_000

    def __call__(self):
        return self.now


def seed(base, clock):
    data = base / "data"
    bootstrap_admin(data, "admin", PASSWORD)
    with WriterLock(data) as writer, AccountDatabase(data).writer_connection(writer) as connection:
        service = AuthService(connection, writer, clock=clock, login_limiter=AuthRateLimiter())
        actor = service.login("admin", PASSWORD, audience="ADMIN", source_key="seed").principal
        invitation = service.issue_invitation(actor, "alice")
        service.activate(invitation.token, PASSWORD)


@pytest.fixture
def http_env(tmp_path):
    clock = Clock()
    seed(tmp_path, clock)
    settings = HTTPAuthSettings(enabled=True, origins=(ORIGIN,), clock=clock, rate_clock=clock)
    app = create_app(tmp_path, account_http=settings)
    with TestClient(app, base_url=ORIGIN, client=("127.0.0.1", 50000)) as client:
        client.headers["Origin"] = ORIGIN
        yield SimpleNamespace(client=client, app=app, settings=settings, clock=clock, base=tmp_path)


def login(env, audience="PLAYER", username=None):
    response = env.client.post(cookie_path(audience) + "/login",
                               json={"username": username or ("admin" if audience == "ADMIN" else "alice"), "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response


def csrf(env, audience="ADMIN"):
    response = env.client.get(cookie_path(audience) + "/csrf")
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def invite(env, username="bobby"):
    login(env, "ADMIN")
    response = env.client.post("/api/auth/admin/invitations", json={"username": username}, headers=csrf(env))
    assert response.status_code == 201, response.text
    return response.json()


@contextmanager
def other_client(env, *, base_url=ORIGIN, peer="127.0.0.1", app=None):
    client = TestClient(app or env.app, base_url=base_url, client=(peer, 50001))
    client.portal = env.client.portal
    try:
        yield client
    finally:
        client.close()


def test_gate_off_preserves_legacy_without_opening_sqlite(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Feature OFF must not open SQLite")
    monkeypatch.setattr(AccountDatabase, "_connect", forbidden)
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/api/auth/player/me").status_code == 404
        assert client.get("/api/session").json()["role"] == "player"
        assert client.post("/api/session/organizer", json={"code": "neon-test-organizer-code"}).json()["role"] == "organizer"
    assert not (tmp_path / "data/arena.sqlite3").exists()


@pytest.mark.parametrize("case", ["missing", "version", "fingerprint"])
def test_gate_on_missing_or_incompatible_database_fails_before_store(tmp_path, case):
    data = tmp_path / "data"
    data.mkdir()
    marker = data / "bots.json"
    marker.write_bytes(b'{"preserve":"must not initialize Store"}')
    if case != "missing":
        AccountDatabase(data).migrate()
        with sqlite3.connect(data / "arena.sqlite3") as connection:
            connection.execute("PRAGMA user_version=999" if case == "version" else "ALTER TABLE users ADD COLUMN unauthorized TEXT")
    db_before = (data / "arena.sqlite3").read_bytes() if case != "missing" else None
    settings = HTTPAuthSettings(enabled=True, origins=(ORIGIN,))
    with pytest.raises((SchemaError, sqlite3.OperationalError)):
        with TestClient(create_app(tmp_path, account_http=settings)):
            pass
    assert marker.read_bytes() == b'{"preserve":"must not initialize Store"}'
    assert not (data / "sessions.json").exists()
    if db_before is not None:
        assert (data / "arena.sqlite3").read_bytes() == db_before
    else:
        assert not (data / "arena.sqlite3").exists()
    with WriterLock(data):
        pass  # failed startup released the lock


def test_gate_environment_is_explicit_and_rejects_public_origins(tmp_path, monkeypatch):
    monkeypatch.setenv("ARENA_ACCOUNT_AUTH", "1")
    with pytest.raises(ValueError, match="ORIGINS"):
        create_app(tmp_path)
    monkeypatch.setenv("ARENA_AUTH_ORIGINS", ORIGIN)
    assert HTTPAuthSettings.from_environment().enabled
    for origins in [("https://public.example",), ("https://testserver/path",), ("http://127.0.0.1",)]:
        with pytest.raises(ValueError):
            HTTPAuthSettings(enabled=True, origins=origins)
    with pytest.raises(ValueError, match="read-only"):
        create_app(tmp_path, account_http=HTTPAuthSettings(enabled=True, origins=(ORIGIN,)), network=NetworkSettings(read_only=True))


def test_player_admin_login_cookies_and_me(http_env):
    for audience, username in [("PLAYER", "alice"), ("ADMIN", "admin")]:
        response = login(http_env, audience)
        cookie = response.headers["set-cookie"]
        assert cookie_name(audience) + "=" in cookie
        for attribute in ("HttpOnly", "Secure", "SameSite=strict", "Path=" + cookie_path(audience)):
            assert attribute.lower() in cookie.lower()
        assert "domain=" not in cookie.lower()
        raw_token = http_env.client.cookies[cookie_name(audience)]
        assert raw_token not in response.text
        assert "session_id" not in response.text and "auth_version" not in response.text
        assert response.json()["scope"] == "account_auth_only"
        assert response.json()["legacy_api_account_rbac"] is False
        assert http_env.client.get(cookie_path(audience) + "/me").json()["account"]["username"] == username
    assert "arena_session" not in http_env.client.cookies
    assert not (http_env.base / "data/sessions.json").exists()


def test_admin_invitation_activation_and_replay(http_env):
    invitation = invite(http_env)
    assert "url" not in invitation and "password" not in invitation
    assert invitation["account"]["system_role"] == "PLAYER"
    activated = http_env.client.post("/api/auth/activate", json={"token": invitation["token"], "password": PASSWORD})
    assert activated.status_code == 200
    assert activated.json()["account"]["status"] == "ACTIVE"
    assert invitation["token"] not in activated.text
    assert http_env.client.post("/api/auth/activate", json={"token": invitation["token"], "password": PASSWORD}).status_code == 400
    assert http_env.client.post("/api/auth/player/login", json={"username": "bobby", "password": PASSWORD}).status_code == 200


def test_invitation_reissue_revoke_expired_and_wrong_token(http_env):
    first = invite(http_env)
    path = "/api/auth/admin/invitations/" + first["invitation_id"]
    second = http_env.client.post(path + "/reissue", json={}, headers=csrf(http_env)).json()
    assert http_env.client.post("/api/auth/activate", json={"token": first["token"], "password": PASSWORD}).status_code == 400
    second_path = "/api/auth/admin/invitations/" + second["invitation_id"]
    assert http_env.client.post(second_path + "/revoke", json={}, headers=csrf(http_env)).status_code == 200
    assert http_env.client.post("/api/auth/activate", json={"token": second["token"], "password": PASSWORD}).status_code == 400
    third = http_env.client.post(path + "/reissue", json={}, headers=csrf(http_env)).json()
    http_env.clock.now = third["expires_at"]
    assert http_env.client.post("/api/auth/activate", json={"token": third["token"], "password": PASSWORD}).status_code == 400
    assert http_env.client.post("/api/auth/activate", json={"token": "z" * 43, "password": PASSWORD}).status_code == 400


@pytest.mark.parametrize("case", ["missing", "player", "legacy_organizer", "forged_role"])
def test_admin_endpoints_require_real_admin_session(http_env, case):
    if case == "player":
        login(http_env)
    elif case == "legacy_organizer":
        assert http_env.client.post("/api/session/organizer", json={"code": "neon-test-organizer-code"}).status_code == 200
    elif case == "forged_role":
        http_env.client.cookies.set(cookie_name("ADMIN"), "z" * 43, path=cookie_path("ADMIN"))
    response = http_env.client.post("/api/auth/admin/invitations", json={"username": "evil", "role": "ADMIN"}, headers={"X-CSRF-Token": "0" * 64})
    assert response.status_code in {401, 403, 422}
    # Valid DTO cannot bypass either; no invitation is created.
    assert http_env.client.post("/api/auth/admin/invitations", json={"username": "evil"}, headers={"X-CSRF-Token": "0" * 64}).status_code in {401, 403}


def test_validation_never_echoes_secrets_or_accepts_privileged_fields(http_env):
    for data in [
        {"username": "alice", "password": PASSWORD, "role": "ADMIN"},
        {"username": "alice", "password": PASSWORD, "user_id": "forged"},
        {"username": "alice", "password": PASSWORD, "auth_version": 7},
        {"username": "alice", "password": PASSWORD, "session_id": "forged"},
        {"username": "a" * 100, "password": PASSWORD},
    ]:
        response = http_env.client.post("/api/auth/player/login", json=data)
        assert response.status_code == 422
        assert PASSWORD not in response.text and "input" not in response.text
    bad = http_env.client.post("/api/auth/activate", json={"token": "sensitive-invalid-token", "password": PASSWORD})
    assert bad.status_code == 422 and "sensitive-invalid-token" not in bad.text


def test_generic_login_failures(http_env):
    results = [http_env.client.post("/api/auth/player/login", json={"username": name, "password": PASSWORD + "wrong"})
               for name in ("alice", "unknown")]
    assert [result.status_code for result in results] == [401, 401]
    assert results[0].json() == results[1].json()


@pytest.mark.parametrize("state", ["idle", "absolute", "revoked", "disabled", "version"])
def test_invalidated_session_denied_over_http(http_env, state):
    login(http_env)
    if state == "idle":
        http_env.clock.now += 3600
    elif state == "absolute":
        for _ in range(15):
            http_env.clock.now += 1800
            assert http_env.client.get("/api/auth/player/me").status_code == 200
        http_env.clock.now += 1800
    else:
        # Simulate an authorized account-management commit on the same writer.
        runtime = http_env.app.state.account_http
        with runtime.database.writer_connection(runtime.writer) as connection, transaction(connection):
            if state == "revoked":
                connection.execute("UPDATE auth_sessions SET revoked_at=created_at WHERE audience='PLAYER'")
            elif state == "disabled":
                connection.execute("UPDATE users SET status='DISABLED' WHERE username='alice'")
            else:
                connection.execute("UPDATE users SET auth_version=auth_version+1 WHERE username='alice'")
    assert http_env.client.get("/api/auth/player/me").status_code == 401


def test_logout_clears_matching_cookie_and_revokes_session(http_env):
    login(http_env)
    raw = http_env.client.cookies[cookie_name("PLAYER")]
    response = http_env.client.post("/api/auth/player/logout", json={}, headers=csrf(http_env, "PLAYER"))
    assert response.status_code == 200
    deletion = response.headers["set-cookie"].lower()
    assert "max-age=0" in deletion and "path=/api/auth/player" in deletion
    assert "httponly" in deletion and "secure" in deletion and "samesite=strict" in deletion
    assert cookie_name("PLAYER") not in http_env.client.cookies
    http_env.client.cookies.set(cookie_name("PLAYER"), raw, path=cookie_path("PLAYER"))
    assert http_env.client.get("/api/auth/player/me").status_code == 401


def test_csrf_missing_wrong_cross_session_and_valid(http_env):
    login(http_env, "ADMIN")
    old_csrf = csrf(http_env)
    for headers in ({}, {"X-CSRF-Token": "0" * 64}, {"X-CSRF-Token": "bad"}):
        assert http_env.client.post("/api/auth/admin/invitations", json={"username": "bobby"}, headers=headers).status_code == 403
    login(http_env, "ADMIN")  # rotate session; prior CSRF cannot authorize this cookie
    assert http_env.client.post("/api/auth/admin/invitations", json={"username": "bobby"}, headers=old_csrf).status_code == 403
    assert http_env.client.post("/api/auth/admin/invitations", json={"username": "bobby"}, headers=csrf(http_env)).status_code == 201


@pytest.mark.parametrize("origin", [None, "null", "https://evil.test", "https://testserver.evil.test", "http://testserver", "https://testserver:444", "https://testserver/"])
def test_origin_required_exactly_for_login_and_activation(http_env, origin):
    with other_client(http_env) as client:
        headers = {} if origin is None else {"Origin": origin}
        for path, body in [("/api/auth/player/login", {"username": "alice", "password": PASSWORD}),
                           ("/api/auth/activate", {"token": "z" * 43, "password": PASSWORD})]:
            assert client.post(path, json=body, headers=headers).status_code == 403


def test_cross_audience_and_legacy_privilege_separation(http_env):
    login(http_env, "ADMIN")
    admin_token = http_env.client.cookies[cookie_name("ADMIN")]
    assert http_env.client.get("/api/session").json()["role"] == "player"
    assert http_env.client.post("/api/competition/open").status_code == 403
    # Explicitly replaying the account token in another cookie cannot grant rights.
    with other_client(http_env) as client:
        client.cookies.set(cookie_name("PLAYER"), admin_token, path=cookie_path("PLAYER"))
        assert client.get("/api/auth/player/me").status_code == 401
        client.cookies.set("arena_session", admin_token)
        assert client.get("/api/session").json()["role"] == "player"
        assert client.post("/api/competition/open", json={}).status_code == 403
    with http_env.client.websocket_connect("wss://testserver/ws/competition", headers={"Origin": ORIGIN}) as ws:
        payload = ws.receive_json()
        serialized = json.dumps(payload)
        assert payload["role"] == "player"
        assert admin_token not in serialized and "account" not in payload and "auth_version" not in serialized


@pytest.mark.parametrize("headers", [
    {"Host": "evil.test"}, {"Host": "192.168.1.10"}, {"X-Forwarded-For": "127.0.0.1"},
    {"X-Forwarded-Proto": "https"}, {"X-Forwarded-Host": "testserver"}, {"Forwarded": "for=127.0.0.1"},
])
def test_host_and_forwarded_header_spoofing_rejected(http_env, headers):
    response = http_env.client.post("/api/auth/player/login", json={"username": "alice", "password": PASSWORD}, headers=headers)
    assert response.status_code == 403
    assert response.headers["cache-control"] == "no-store"


def test_public_peer_and_even_proxy_rewritten_scope_cannot_bypass(http_env):
    with other_client(http_env, peer="8.8.8.8") as client:
        assert client.get("/api/auth/player/me").status_code == 403
    wrapped = ProxyHeadersMiddleware(http_env.app, trusted_hosts="*")  # deliberately unsafe outside adapter
    with other_client(http_env, peer="8.8.8.8", app=wrapped) as client:
        response = client.post("/api/auth/player/login", json={"username": "alice", "password": PASSWORD},
                               headers={"Origin": ORIGIN, "X-Forwarded-For": "127.0.0.1"})
        assert response.status_code == 403


def test_bruteforce_by_account_and_source_and_retry_after(http_env):
    runtime = http_env.app.state.account_http
    runtime.limiter = AuthRateLimiter(replace(http_env.settings.limits, login_account=2, login_source=3), clock=http_env.clock)
    for _ in range(2):
        assert http_env.client.post("/api/auth/player/login", json={"username": "alice", "password": "wrong"}).status_code == 401
    blocked = http_env.client.post("/api/auth/player/login", json={"username": "alice", "password": PASSWORD})
    assert blocked.status_code == 429 and blocked.headers["retry-after"] == "60"
    # Changing remote source does not clear the account bucket.
    with other_client(http_env, peer="192.168.1.12") as other:
        assert other.post("/api/auth/player/login", json={"username": "alice", "password": PASSWORD}, headers={"Origin": ORIGIN}).status_code == 429
    assert http_env.client.post("/api/auth/player/login", json={"username": "unknown", "password": "wrong"}).status_code == 401
    assert http_env.client.post("/api/auth/player/login", json={"username": "another", "password": "wrong"}).status_code == 429
    http_env.clock.now += 60
    login(http_env)


def test_activation_and_session_token_rate_limits(http_env):
    runtime = http_env.app.state.account_http
    runtime.limiter = AuthRateLimiter(replace(http_env.settings.limits, activation_token=2, session_token=2), clock=http_env.clock)
    for _ in range(2):
        assert http_env.client.post("/api/auth/activate", json={"token": "z" * 43, "password": PASSWORD}).status_code == 400
    assert http_env.client.post("/api/auth/activate", json={"token": "z" * 43, "password": PASSWORD}).status_code == 429
    login(http_env)
    assert http_env.client.get("/api/auth/player/me").status_code == 200
    assert http_env.client.get("/api/auth/player/me").status_code == 200
    assert http_env.client.get("/api/auth/player/me").status_code == 429


def test_capacity_rejection_is_503_not_wrong_password(http_env):
    with _PASSWORD_WORK.slot():
        response = http_env.client.post("/api/auth/player/login", json={"username": "alice", "password": PASSWORD})
    assert response.status_code == 503 and response.headers["retry-after"] == "1"


def test_argon2_worker_does_not_block_event_loop_or_cross_thread_connection(http_env, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    loop_threads, worker_threads, connection_threads, query_threads = [], [], [], []
    real_verify = passwords.verify_password
    real_connect = AccountDatabase._connect
    def connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        owner = threading.get_ident()
        connection_threads.append(owner)
        def trace(_):
            query_threads.append((owner, threading.get_ident()))
        connection.set_trace_callback(trace)  # never capture SQL/hash contents
        return connection
    def blocked_verify(*args):
        worker_threads.append(threading.get_ident())
        entered.set()
        assert release.wait(timeout=10)
        return real_verify(*args)
    monkeypatch.setattr(AccountDatabase, "_connect", connect)
    monkeypatch.setattr(passwords, "verify_password", blocked_verify)
    async def loop_probe():
        loop_threads.append(threading.get_ident())
    http_env.client.portal.call(loop_probe)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(http_env.client.post, "/api/auth/player/login", json={"username": "alice", "password": PASSWORD})
        try:
            assert entered.wait(timeout=10)
            assert http_env.client.get("/api/health").status_code == 200
        finally:
            release.set()
        assert future.result(timeout=10).status_code == 200
    assert worker_threads and connection_threads and set(worker_threads).isdisjoint(loop_threads)
    assert set(worker_threads) <= set(connection_threads)
    assert query_threads and all(owner == current for owner, current in query_threads)


def test_responses_no_store_bounded_body_json_only_and_no_query_tokens(http_env):
    for response in [http_env.client.get("/api/auth/player/me"),
                     http_env.client.post("/api/auth/player/login", json={}),
                     http_env.client.get("/api/auth/no-such-endpoint")]:
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert "access-control-allow-origin" not in response.headers
    assert http_env.client.post("/api/auth/player/login", content="x" * (MAX_BODY + 1), headers={"Content-Type": "application/json"}).status_code == 413
    assert http_env.client.post("/api/auth/player/login", content=(b"x" * 1024 for _ in range(5)), headers={"Content-Type": "application/json"}).status_code == 413
    assert http_env.client.post("/api/auth/player/login", data={"username": "alice", "password": PASSWORD}).status_code == 415
    assert http_env.client.get("/api/auth/player/me?token=must-not-use-url").status_code == 400


def test_local_http_requires_opt_in_and_never_disables_https_secure(tmp_path):
    clock = Clock()
    seed(tmp_path, clock)
    origin = "http://127.0.0.1:8000"
    settings = HTTPAuthSettings(enabled=True, origins=(origin, ORIGIN), allow_http=True, clock=clock)
    with TestClient(create_app(tmp_path, account_http=settings), base_url=origin, client=("127.0.0.1", 50000)) as client:
        result = client.post("/api/auth/player/login", json={"username": "alice", "password": PASSWORD}, headers={"Origin": origin})
        assert result.status_code == 200
        assert "secure" not in result.headers["set-cookie"].lower()
        assert "httponly" in result.headers["set-cookie"].lower()
        secure_client = TestClient(client.app, base_url=ORIGIN, client=("127.0.0.1", 50001))
        secure_client.portal = client.portal
        try:
            secure = secure_client.post("/api/auth/player/login", json={"username": "alice", "password": PASSWORD}, headers={"Origin": ORIGIN})
            assert secure.status_code == 200 and "secure" in secure.headers["set-cookie"].lower()
        finally:
            secure_client.close()


@pytest.mark.parametrize("cancel_kind", ["scope", "task"])
def test_cancelled_worker_is_drained_before_shutdown(http_env, cancel_kind):
    runtime = http_env.app.state.account_http
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    tasks = []
    def operation(auth, connection):
        try:
            entered.set()
            assert release.wait(timeout=10)
            with transaction(connection):
                connection.execute("UPDATE users SET updated_at=updated_at WHERE username='alice'")
            return True
        finally:
            finished.set()
    async def background():
        tasks.append(asyncio.current_task())
        return await runtime.run(operation)
    work = http_env.client.portal.start_task_soon(background)
    closing = None
    try:
        assert entered.wait(timeout=10)
        if cancel_kind == "scope":
            work.cancel()
        else:
            http_env.client.portal.call(tasks[0].cancel)
        closing = http_env.client.portal.start_task_soon(runtime.close)
        async def snapshot():
            await anyio.sleep(0)  # scheduling yield, not an expiration sleep
            return runtime._active
        assert http_env.client.portal.call(snapshot) == 1
        assert not closing.done()
        with pytest.raises(WriterAlreadyRunning):
            bootstrap_admin(http_env.base / "data", "blocked-admin", PASSWORD)
    finally:
        release.set()
        assert finished.wait(timeout=10)
    closing.result(timeout=10)
    assert runtime._active == 0


def test_integrity_once_startup_and_writer_lock_preserved(http_env, monkeypatch):
    import backend.account_database as database_module
    monkeypatch.setattr(database_module, "check_integrity", lambda *_: pytest.fail("No full scan per auth HTTP request"))
    login(http_env)
    assert http_env.client.get("/api/auth/player/me").status_code == 200
    with pytest.raises(WriterAlreadyRunning):
        bootstrap_admin(http_env.base / "data", "another-admin", PASSWORD)


def test_player_cookie_cannot_be_relabelled_as_admin_even_with_valid_csrf_mac(http_env):
    login(http_env)
    token = http_env.client.cookies[cookie_name("PLAYER")]
    http_env.client.cookies.set(cookie_name("ADMIN"), token, path=cookie_path("ADMIN"))
    assert http_env.client.get("/api/auth/admin/me").status_code == 401
    # Server-only test knowledge of the CSRF key still cannot replace session auth.
    header = {"X-CSRF-Token": http_env.app.state.account_http.csrf("ADMIN", token)}
    assert http_env.client.post("/api/auth/admin/invitations", json={"username": "evil"}, headers=header).status_code == 401


def test_duplicate_headers_and_non_ascii_csrf_fail_closed(http_env):
    for headers in [[("Host", "testserver"), ("Host", "evil.test")],
                    [("Origin", ORIGIN), ("Origin", ORIGIN)]]:
        response = http_env.client.post("/api/auth/player/login", json={"username": "alice", "password": PASSWORD}, headers=headers)
        assert response.status_code == 403
    login(http_env, "ADMIN")
    assert http_env.client.post("/api/auth/admin/logout", json={}, headers={"X-CSRF-Token": b"\xff"}).status_code == 403


def test_activation_source_limit_and_bounded_limiter_state(http_env):
    runtime = http_env.app.state.account_http
    runtime.limiter = AuthRateLimiter(replace(http_env.settings.limits, activation_source=2), clock=http_env.clock)
    for token in ("x" * 43, "y" * 43):
        assert http_env.client.post("/api/auth/activate", json={"token": token, "password": PASSWORD}).status_code == 400
    assert http_env.client.post("/api/auth/activate", json={"token": "z" * 43, "password": PASSWORD}).status_code == 429
    limiter = AuthRateLimiter(RateLimits(max_keys=2), clock=http_env.clock)
    limiter.request("source-a")
    limiter.request("source-b")
    with pytest.raises(AuthRateLimited):
        limiter.request("source-c")
    # No live key is evicted to admit new ones; capacity recovers by expiry.
    http_env.clock.now += 60
    limiter.request("source-c")


def test_sqlite_failure_is_503_and_never_exposes_internal_detail(http_env, monkeypatch):
    def unavailable(*args, **kwargs):
        raise sqlite3.OperationalError("sensitive infrastructure detail")
    monkeypatch.setattr(AccountDatabase, "_connect", unavailable)
    result = http_env.client.post("/api/auth/player/login", json={"username": "alice", "password": PASSWORD})
    assert result.status_code == 503
    assert "sensitive" not in result.text and PASSWORD not in result.text


def test_http_paths_never_log_or_persist_raw_credentials(http_env, caplog):
    invitation = invite(http_env)
    login(http_env)
    token = http_env.client.cookies[cookie_name("PLAYER")]
    with http_env.app.state.account_http.database.read() as connection:
        hashed = connection.execute("SELECT token_hash FROM auth_sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()[0]
    for secret in (PASSWORD, invitation["token"], token, hashed):
        assert secret not in caplog.text
    content = (http_env.base / "data/arena.sqlite3").read_bytes()
    for secret in (PASSWORD, invitation["token"], token):
        assert secret.encode() not in content
