"""Account-only cutover tests use disposable directories and in-process clients."""
import json
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.account_database import AccountDatabase, SchemaError, transaction
from backend.admin_cli import bootstrap_admin, invalidate_restored_auth
from backend.auth_http import (HTTPAuthSettings, account_cookie_name,
                               account_cookie_path)
from backend.auth_limits import AuthRateLimiter, RateLimits
from backend.auth_service import AuthService, InvalidInvitation, InvalidSession
from backend.main import create_app
from backend.writer_lock import WriterLock


PASSWORD = "account-only disposable test passphrase 93"
ORIGIN = "https://testserver"


class Clock:
    def __init__(self):
        self.now = 2_000_000_000

    def __call__(self):
        return self.now


def seed_accounts(base, clock):
    data = base / "data"
    bootstrap_admin(data, "admin", PASSWORD, "Arena Admin")
    with WriterLock(data) as writer, AccountDatabase(data).writer_connection(writer) as connection:
        service = AuthService(connection, writer, clock=clock, login_limiter=AuthRateLimiter())
        actor = service.login("admin", PASSWORD, audience="ADMIN", source_key="seed").principal
        invitation = service.issue_invitation(actor, "alice", name="Alice Player")
        service.activate(invitation.token, PASSWORD)


@pytest.fixture
def account_room(tmp_path):
    clock = Clock()
    seed_accounts(tmp_path, clock)
    settings = HTTPAuthSettings(enabled=True, account_only=True, origins=(ORIGIN,),
                                clock=clock, rate_clock=clock)
    app = create_app(tmp_path, account_http=settings)
    with TestClient(app, base_url=ORIGIN, client=("127.0.0.1", 51000)) as client:
        client.headers["Origin"] = ORIGIN
        yield SimpleNamespace(client=client, app=app, base=tmp_path, clock=clock, settings=settings)


def login(room, audience="player", username=None):
    response = room.client.post(f"/api/{audience}/auth/login", json={
        "username": username or ("admin" if audience == "admin" else "alice"),
        "password": PASSWORD,
    })
    assert response.status_code == 200, response.text
    return response


def csrf(room, audience="admin"):
    response = room.client.get(f"/api/{audience}/auth/csrf")
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def test_mode_matrix_and_missing_database_fail_before_store(tmp_path):
    with pytest.raises(ValueError, match="ACCOUNT_AUTH"):
        HTTPAuthSettings(enabled=False, account_only=True)
    settings = HTTPAuthSettings(enabled=True, account_only=True, origins=(ORIGIN,))
    with pytest.raises((SchemaError, sqlite3.OperationalError)):
        with TestClient(create_app(tmp_path, account_http=settings), base_url=ORIGIN):
            pass
    assert not (tmp_path / "data/bots.json").exists()
    assert not (tmp_path / "data/sessions.json").exists()


def test_cutover_refuses_open_legacy_competition_but_restart_is_stable(tmp_path, authorize_organizer):
    clock = Clock()
    seed_accounts(tmp_path, clock)
    with TestClient(create_app(tmp_path)) as legacy:
        legacy.get("/api/session")
        authorize_organizer(legacy)
        assert legacy.post("/api/competition/open").status_code == 200
    settings = HTTPAuthSettings(enabled=True, account_only=True, origins=(ORIGIN,), clock=clock)
    with pytest.raises(RuntimeError, match="competition is still open"):
        with TestClient(create_app(tmp_path, account_http=settings), base_url=ORIGIN):
            pass

    # Complete the explicit legacy drain, then perform the first cutover.
    with TestClient(create_app(tmp_path)) as legacy:
        legacy.get("/api/session")
        authorize_organizer(legacy)
        assert legacy.post("/api/competition/close").status_code == 200
    with TestClient(create_app(tmp_path, account_http=settings), base_url=ORIGIN,
                    client=("127.0.0.1", 51001)) as first:
        first.headers["Origin"] = ORIGIN
        assert first.post("/api/admin/auth/login", json={"username": "admin", "password": PASSWORD}).status_code == 200
        token = first.get("/api/admin/auth/csrf").json()["csrf_token"]
        assert first.post("/api/admin/competition/open", json={}, headers={"X-CSRF-Token": token}).status_code == 200
    # A normal account-only restart is not mistaken for a new authority cutover.
    with TestClient(create_app(tmp_path, account_http=settings), base_url=ORIGIN,
                    client=("127.0.0.1", 51002)) as restarted:
        assert restarted.get("/api/health").json()["account_only"] is True


def test_legacy_authority_and_side_effects_are_blocked(account_room, monkeypatch):
    room = account_room
    # The namespace policy authenticates before FastAPI parses even malformed
    # bodies, so a blocked caller cannot reach business handlers.
    assert room.client.post(
        "/api/admin/competition/open", content=b"{not-json",
        headers={"Content-Type": "application/json"}).status_code == 401
    assert room.client.get("/api/admin/unclassified-operation").status_code == 401
    assert room.client.get("/api/session").status_code == 410
    assert room.client.post("/api/session/organizer", json={"code": "neon-test-organizer-code"}).status_code == 410
    assert room.client.post("/api/auth/admin/login", json={"username": "admin", "password": PASSWORD}).status_code == 410
    room.client.cookies.set("arena_session", "known-legacy-cookie")
    monkeypatch.setattr(room.app.state.runner, "prepare", lambda *_: pytest.fail("blocked upload reached compiler"))
    assert room.client.post("/api/bots", files={"file": ("bot.py", b"print(1)")},
                            data={"name": "bad", "game_id": "robot_battle"}).status_code == 410
    assert room.client.post("/api/invitations", json={"player_a_id": "a", "player_b_id": "b"}).status_code == 410
    login(room)
    assert room.client.post("/api/player/bots", files={"file": ("bot.py", b"print(1)")},
                            data={"name": "bad", "game_id": "robot_battle"}).status_code == 403
    # CSRF is checked before content type; valid CSRF cannot bypass JSON-only.
    assert room.client.post("/api/player/bots", files={"file": ("bot.py", b"print(1)")},
                            data={"name": "bad", "game_id": "robot_battle"},
                            headers=csrf(room, "player")).status_code == 415
    assert room.client.post("/api/player/bots", json={}, headers=csrf(room, "player")).status_code == 422
    assert room.client.get("/api/session/").status_code == 410
    assert room.client.head("/api/bots").status_code == 410
    assert room.client.options("/api/invitations").status_code == 410
    assert room.app.state.sessions is None and room.app.state.lobby is None
    assert not (room.base / "data/sessions.json").exists()


def test_namespaces_csrf_cross_audience_and_admin_rest(account_room):
    room = account_room
    assert room.client.post("/api/player/auth/login", json={"username": "alice", "password": PASSWORD},
                            headers={"Origin": "https://evil.test"}).status_code == 403
    assert room.client.post("/api/player/auth/login", json={"username": "alice", "password": PASSWORD},
                            headers={"X-Forwarded-For": "127.0.0.1"}).status_code == 403
    player_login = login(room)
    player_cookie = player_login.headers["set-cookie"].lower()
    assert "path=/api/player" in player_cookie and "httponly" in player_cookie and "samesite=strict" in player_cookie
    assert room.client.get("/api/player/games").status_code == 200
    assert room.client.put("/api/player/rules", json={}).status_code == 403
    assert room.client.get("/api/player/matches").status_code == 403

    token = room.client.cookies[account_cookie_name("PLAYER")]
    room.client.cookies.set(account_cookie_name("ADMIN"), token, path=account_cookie_path("ADMIN"))
    assert room.client.get("/api/admin/auth/me").status_code == 401
    room.client.cookies.delete(account_cookie_name("ADMIN"), path=account_cookie_path("ADMIN"))

    login(room, "admin")
    assert room.client.post("/api/admin/competition/open", json={}).status_code == 403
    header = csrf(room)
    assert room.client.put("/api/admin/games/selected", json={"game_id": "ott_v2"}, headers=header).status_code == 200
    opened = room.client.post("/api/admin/competition/open", json={}, headers=header)
    assert opened.status_code == 200 and opened.json()["selected_game_id"] == "ott_v2"
    assert room.client.put("/api/admin/games/robot_battle/rules", json={}, headers=header).status_code == 409


def test_account_namespace_rate_limit_is_shared_with_auth_core(account_room):
    room = account_room
    room.app.state.account_http.limiter = AuthRateLimiter(
        RateLimits(login_account=1), clock=room.clock)
    assert room.client.post("/api/player/auth/login", json={
        "username": "alice", "password": "wrong"}).status_code == 401
    blocked = room.client.post("/api/player/auth/login", json={
        "username": "alice", "password": PASSWORD})
    assert blocked.status_code == 429 and blocked.headers["retry-after"] == "60"


def test_activation_logout_duplicate_cookie_and_safe_serializers(account_room):
    room = account_room
    login(room, "admin")
    invitation = room.client.post("/api/admin/auth/invitations", json={"username": "bobby"},
                                  headers=csrf(room)).json()
    assert room.client.post("/api/player/auth/activate", json={
        "token": invitation["token"], "password": PASSWORD}).status_code == 200

    room.app.state.store.save_bot({
        "id": "private-bot", "name": "Private", "filename": "bot.py", "language": "py",
        "game_id": "robot_battle", "status": "ready", "created_at": "now",
        "execution_backend": "sandbox", "logs": "private compiler output", "folder": "D:/secret",
        "command": ["secret"], "artifact_id": "secret-artifact", "artifact_digest": "secret-digest",
        "owner": {"id": "legacy", "name": "Legacy"},
    })
    room.app.state.store.save_match({
        "id": "legacy-match", "game_id": "robot_battle", "game": "robot_battle",
        "game_name": "Robot Battle", "game_version": "1", "status": "completed",
        "created_at": "now", "created_by": {"id": "legacy-secret"}, "rules_snapshot": {},
        "turn": 0, "result": {"winner": None, "reason": "draw", "faults": {}}, "winner": None,
        "bots": {"A": {"id": "private-bot", "name": "Private", "language": "py",
                        "owner": {"id": "legacy"}}},
    })
    room.app.state.store.start_replay("legacy-match", {"game_id": "robot_battle", "turn": 0, "events": []})
    bots = room.client.get("/api/admin/bots").json()
    serialized = json.dumps(bots)
    assert "private-bot" in serialized
    for secret in ("private compiler output", "D:/secret", "secret-artifact", "secret-digest", "command", "owner"):
        assert secret not in serialized
    match = room.client.get("/api/admin/matches/legacy-match").json()
    assert "created_by" not in match and "owner" not in json.dumps(match)

    name = account_cookie_name("ADMIN")
    assert room.client.get("/api/admin/auth/me", headers={"Cookie": f"{name}=one; {name}=two"}).status_code == 400
    raw = room.client.cookies[name]
    result = room.client.post("/api/admin/auth/logout", json={}, headers=csrf(room))
    assert result.status_code == 200 and "path=/api/admin" in result.headers["set-cookie"].lower()
    room.client.cookies.set(name, raw, path=account_cookie_path("ADMIN"))
    assert room.client.get("/api/admin/auth/me").status_code == 401


def test_account_websocket_auth_logout_and_idle_expiry(account_room):
    room = account_room
    with pytest.raises(WebSocketDisconnect):
        with room.client.websocket_connect("wss://testserver/api/admin/ws/competition",
                                           headers={"Origin": ORIGIN}):
            pass
    login(room, "admin")
    with pytest.raises(WebSocketDisconnect):
        with room.client.websocket_connect("wss://testserver/api/admin/ws/competition",
                                           headers={"Origin": "https://evil.test"}):
            pass
    with pytest.raises(WebSocketDisconnect):
        with room.client.websocket_connect(
                "wss://testserver/api/admin/ws/competition?token=not-a-session",
                headers={"Origin": ORIGIN}):
            pass
    with pytest.raises(WebSocketDisconnect):
        with room.client.websocket_connect(
                "wss://testserver/api/admin/ws/competition",
                headers={"Origin": ORIGIN}, subprotocols=["bearer.not-a-session"]):
            pass
    with pytest.raises(WebSocketDisconnect):
        with room.client.websocket_connect(
                "wss://testserver/api/admin/ws/matches/missing?after=0&after=1",
                headers={"Origin": ORIGIN}):
            pass

    with room.client.websocket_connect("wss://testserver/api/admin/ws/competition",
                                       headers={"Origin": ORIGIN}) as ws:
        assert ws.receive_json()["type"] == "competition"
        assert room.client.post("/api/admin/auth/logout", json={}, headers=csrf(room)).status_code == 200
        messages = []
        with pytest.raises(WebSocketDisconnect) as closed:
            while True:
                messages.append(ws.receive_json())
        assert closed.value.code == 4401

    login(room, "admin")
    with room.client.websocket_connect("wss://testserver/api/admin/ws/competition",
                                       headers={"Origin": ORIGIN}) as ws:
        assert ws.receive_json()["type"] == "competition"
        room.clock.now += 15 * 60
        with pytest.raises(WebSocketDisconnect) as closed:
            while True:
                ws.receive_json()
        assert closed.value.code == 4401


@pytest.mark.parametrize("state", ["revoked", "disabled", "version"])
def test_account_websocket_polls_persistent_revocation(account_room, state):
    room = account_room
    login(room, "admin")
    with room.client.websocket_connect("wss://testserver/api/admin/ws/competition",
                                       headers={"Origin": ORIGIN}) as ws:
        assert ws.receive_json()["type"] == "competition"
        runtime = room.app.state.account_http
        with runtime.database.writer_connection(runtime.writer) as connection, transaction(connection):
            if state == "revoked":
                connection.execute("""UPDATE auth_sessions SET revoked_at=created_at
                    WHERE audience='ADMIN' AND revoked_at IS NULL""")
            elif state == "disabled":
                connection.execute("UPDATE users SET status='DISABLED' WHERE username='admin'")
            else:
                connection.execute("UPDATE users SET auth_version=auth_version+1 WHERE username='admin'")
        with pytest.raises(WebSocketDisconnect) as closed:
            while True:
                ws.receive_json()
        assert closed.value.code == 4401

def test_restore_fence_revokes_sessions_and_tokens(tmp_path):
    clock = Clock()
    seed_accounts(tmp_path, clock)
    data = tmp_path / "data"
    with WriterLock(data) as writer, AccountDatabase(data).writer_connection(writer) as connection:
        service = AuthService(connection, writer, clock=clock, login_limiter=AuthRateLimiter())
        grant = service.login("alice", PASSWORD, audience="PLAYER", source_key="restore-test")
        admin = service.login("admin", PASSWORD, audience="ADMIN", source_key="restore-test").principal
        invitation = service.issue_invitation(admin, "carol")
    result = invalidate_restored_auth(data)
    assert result["sessions_revoked"] >= 2 and result["tokens_revoked"] >= 1
    with WriterLock(data) as writer, AccountDatabase(data).writer_connection(writer) as connection:
        service = AuthService(connection, writer, clock=clock, login_limiter=AuthRateLimiter())
        with pytest.raises(InvalidSession):
            service.validate_session(grant.token, audience="PLAYER")
        with pytest.raises(InvalidInvitation):
            service.activate(invitation.token, PASSWORD)


@pytest.mark.parametrize("persisted_status", ["queued", "running"])
def test_existing_account_only_restart_recovers_claimed_official_match(tmp_path, persisted_status):
    """QA-001: startup must reach Store + dispatcher after an Official crash.

    SQLite claimed Official identity is checked before Store rewrites the
    persisted queued/running JSON as interrupted. No replay is rerun.
    """
    from backend.storage import Store
    clock = Clock()
    seed_accounts(tmp_path, clock)
    data = tmp_path / "data"
    request_id = "f" * 32
    match_id = "o" + request_id[:15]
    with AccountDatabase(data).maintenance() as conn:
        admin_id = conn.execute(
            "SELECT id FROM users WHERE username='admin'").fetchone()["id"]
        for team_id, slug in (("team-a", "qa-alpha"), ("team-b", "qa-beta")):
            conn.execute("""INSERT INTO teams
                (id,slug,display_name,status,created_by,created_at,updated_at)
                VALUES (?,?,?,'ACTIVE',?,100,100)""",
                (team_id, slug, slug, admin_id))
        conn.execute("""INSERT INTO official_match_requests
            (id,created_by,team_a_id,team_b_id,game_id,rules_json,bot_lock_at,
             scheduled_at,created_at,status,locked_at,match_id,started_at)
            VALUES (?,?,?,?,'robot_battle','{}',100,101,100,'RUNNING',100,?,101)""",
            (request_id, admin_id, "team-a", "team-b", match_id))
    Store._write(data / "access_mode.json", {"version": 1, "mode": "account_only"})
    Store._write(data / "matches.json", {match_id: {
        "id": match_id, "official_request_id": request_id,
        "status": persisted_status, "game_id": "robot_battle",
        "result": None, "turn": 2,
    }})
    settings = HTTPAuthSettings(enabled=True, account_only=True, origins=(ORIGIN,),
                                clock=clock)
    with TestClient(create_app(tmp_path, account_http=settings), base_url=ORIGIN) as client:
        assert client.get("/api/health").status_code == 200
        recovered = client.app.state.store.get_match(match_id)
        assert recovered["status"] == "interrupted"
        assert recovered["result"]["winner"] is None
        with AccountDatabase(data).read() as conn:
            row = conn.execute("""SELECT status,status_reason,outcome_json,revision
                FROM official_match_requests WHERE id=?""", (request_id,)).fetchone()
            assert row["status"] == "INTERRUPTED"
            assert row["status_reason"] in ("server_restart", "SERVER_RESTART")
            assert row["outcome_json"] is None
    # Recovery remains idempotent on repeated startup.
    with TestClient(create_app(tmp_path, account_http=settings), base_url=ORIGIN) as client:
        assert client.get("/api/health").status_code == 200
        with AccountDatabase(data).read() as conn:
            same = conn.execute("""SELECT status,revision FROM official_match_requests
                WHERE id=?""", (request_id,)).fetchone()
            assert same["status"] == "INTERRUPTED"
            assert same["revision"] == row["revision"]


@pytest.mark.parametrize("official_id", [None, "f" * 32])
def test_existing_account_only_still_rejects_unclaimed_legacy_or_forged_job(tmp_path, official_id):
    """An Account-Only marker alone cannot bless a rogue queued/running match."""
    from backend.storage import Store
    clock = Clock()
    seed_accounts(tmp_path, clock)
    data = tmp_path / "data"
    Store._write(data / "access_mode.json", {"version": 1, "mode": "account_only"})
    record = {"id": "unknown", "status": "running", "game_id": "robot_battle"}
    if official_id:
        record["official_request_id"] = official_id
    Store._write(data / "matches.json", {"unknown": record})
    settings = HTTPAuthSettings(enabled=True, account_only=True, origins=(ORIGIN,),
                                clock=clock)
    with pytest.raises(RuntimeError, match="match/job\\(s\\) are queued or running"):
        with TestClient(create_app(tmp_path, account_http=settings), base_url=ORIGIN):
            pass
    assert json.loads((data / "matches.json").read_text())["unknown"]["status"] == "running"


def test_unified_login_derives_role_and_uses_separate_session_paths(account_room):
    room = account_room
    for username, role, audience in (("admin", "ADMIN", "admin"),
                                     ("alice", "PLAYER", "player")):
        response = room.client.post("/api/account/auth/login", json={
            "username": username, "password": PASSWORD,
        })
        assert response.status_code == 200, response.text
        assert response.json()["account"]["system_role"] == role
        assert response.json()["audience"] == audience
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=strict" in cookie
        assert "path=/api/" + audience in cookie
        assert room.client.get("/api/" + audience + "/auth/me").status_code == 200
        if audience == "player":
            # The unified login removes any previously retained Admin cookie.
            assert room.client.get("/api/admin/auth/me").status_code == 401
    failed = room.client.post("/api/account/auth/login", json={
        "username": "admin", "password": "incorrect password",
    })
    assert failed.status_code == 401
    escalation = room.client.post("/api/account/auth/login", json={
        "username": "alice", "password": PASSWORD, "audience": "admin",
    })
    assert escalation.status_code == 422


def test_player_self_registration_is_gated_and_never_provisions_admin(tmp_path):
    from backend.storage import Store
    clock = Clock()
    seed_accounts(tmp_path, clock)
    settings = HTTPAuthSettings(enabled=True, account_only=True, origins=(ORIGIN,),
                                clock=clock, rate_clock=clock)
    registration = {
        "username": "new_player", "display_name": "New Player",
        "email": "New.Player@example.org", "password": PASSWORD,
    }
    with TestClient(create_app(tmp_path, account_http=settings), base_url=ORIGIN,
                    client=("127.0.0.1", 51001)) as blocked:
        blocked.headers["Origin"] = ORIGIN
        response = blocked.post("/api/account/auth/register", json=registration)
        assert response.status_code == 404
        assert blocked.get("/api/health").json()["self_registration"] is False
    opened = HTTPAuthSettings(enabled=True, account_only=True, self_registration=True,
                              origins=(ORIGIN,), clock=clock, rate_clock=clock)
    with TestClient(create_app(tmp_path, account_http=opened), base_url=ORIGIN,
                    client=("127.0.0.1", 51002)) as client:
        client.headers["Origin"] = ORIGIN
        assert client.get("/api/health").json()["self_registration"] is True
        created = client.post("/api/account/auth/register", json=registration)
        assert created.status_code == 201, created.text
        assert created.json()["account"]["system_role"] == "PLAYER"
        assert created.json()["email_verified"] is False
        assert "password" not in json.dumps(created.json())
        duplicate = client.post("/api/account/auth/register", json={
            **registration, "username": "another_name", "email": "new.player@example.org",
        })
        assert duplicate.status_code == 409
        duplicate_name = client.post("/api/account/auth/register", json={
            **registration, "email": "new.else@example.org",
        })
        assert duplicate_name.status_code == 409
        with AccountDatabase(tmp_path / "data").read() as connection:
            row = connection.execute("""SELECT u.system_role,u.status,e.email,e.verified_at
                FROM users u JOIN user_emails e ON u.id=e.user_id WHERE u.username=?""",
                ("new_player",)).fetchone()
            assert tuple(row) == ("PLAYER", "ACTIVE", "new.player@example.org", None)
        login = client.post("/api/account/auth/login", json={
            "username": "new_player", "password": PASSWORD,
        })
        assert login.status_code == 200 and login.json()["audience"] == "player"
        assert client.get("/api/player/auth/me").status_code == 200
        # A bad Origin or a spoofed trusted proxy may not create accounts.
        blocked_origin = client.post("/api/account/auth/register", json={
            **registration, "username": "outside", "email": "outside@example.org",
        }, headers={"Origin": "https://evil.example"})
        assert blocked_origin.status_code == 403
        blocked_proxy = client.post("/api/account/auth/register", json={
            **registration, "username": "outside", "email": "outside@example.org",
        }, headers={"X-Forwarded-For": "127.0.0.1"})
        assert blocked_proxy.status_code == 403
        unauthorized = client.post("/api/account/auth/register", json={
            **registration, "username": "hacker", "email": "hacker@example.org", "system_role": "ADMIN",
        })
        assert unauthorized.status_code == 422


def test_registration_validates_email_password_and_rate_limit(tmp_path):
    clock = Clock()
    seed_accounts(tmp_path, clock)
    settings = HTTPAuthSettings(
        enabled=True, account_only=True, self_registration=True, origins=(ORIGIN,),
        clock=clock, rate_clock=clock,
        limits=RateLimits(registration_source=2),
    )
    with TestClient(create_app(tmp_path, account_http=settings), base_url=ORIGIN,
                    client=("127.0.0.1", 51003)) as client:
        client.headers["Origin"] = ORIGIN
        payload = {"username": "tester", "display_name": "Tester",
                   "email": "bad@domain", "password": PASSWORD}
        assert client.post("/api/account/auth/register", json=payload).status_code == 422
        payload["email"] = "tester@example.org"
        payload["password"] = "short"
        assert client.post("/api/account/auth/register", json=payload).status_code == 422
        # Valid character count but >1024 UTF-8 bytes: reaches service
        # and consumes the second registration budget entry.
        payload["password"] = "é" * 513
        assert client.post("/api/account/auth/register", json=payload).status_code == 422
        payload["password"] = PASSWORD
        limited = client.post("/api/account/auth/register", json=payload)
        assert limited.status_code == 429
        assert limited.headers["retry-after"] == "60"
        assert client.get("/api/account/auth/register").status_code in (404, 405)
    with pytest.raises(ValueError, match="Self-registration requires"):
        HTTPAuthSettings(enabled=True, self_registration=True, origins=(ORIGIN,))

