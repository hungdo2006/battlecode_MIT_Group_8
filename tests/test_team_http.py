"""Integration tests for Phase 4.2C1 Team HTTP endpoints.

Tests REST API surface under AccountAuthBoundary, CSRF enforcement,
Origin/Host filtering, RBAC/IDOR guards, session lifetimes,
full lifecycle flows, and backward compatibility.
"""
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient

from backend.account_database import AccountDatabase
from backend.admin_cli import bootstrap_admin
from backend.auth_http import HTTPAuthSettings, account_cookie_name
from backend.auth_limits import AuthRateLimiter
from backend.auth_service import AuthService
from backend.main import create_app
from backend.writer_lock import WriterLock


PASSWORD = "team-http test passphrase 84"
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
        admin_actor = service.login("admin", PASSWORD, audience="ADMIN", source_key="seed").principal
        for name in ["alice", "bob", "charlie"]:
            invitation = service.issue_invitation(admin_actor, name, name=name.title())
            service.activate(invitation.token, PASSWORD)


@pytest.fixture
def room(tmp_path):
    clock = Clock()
    seed_accounts(tmp_path, clock)
    settings = HTTPAuthSettings(enabled=True, account_only=True, origins=(ORIGIN,),
                                clock=clock, rate_clock=clock)
    app = create_app(tmp_path, account_http=settings)
    with TestClient(app, base_url=ORIGIN, client=("127.0.0.1", 51000)) as client:
        client.headers["Origin"] = ORIGIN
        yield SimpleNamespace(client=client, app=app, base=tmp_path, clock=clock, settings=settings)


def login(room, audience="player", username="alice"):
    res = room.client.post(f"/api/{audience}/auth/login", json={
        "username": username,
        "password": PASSWORD,
    })
    assert res.status_code == 200, res.text
    return res


def csrf(room, audience="player"):
    res = room.client.get(f"/api/{audience}/auth/csrf")
    assert res.status_code == 200, res.text
    return {"X-CSRF-Token": res.json()["csrf_token"]}


# --- Security & Boundary Negative Tests ---

def test_unauthenticated_team_requests_rejected(room):
    # No session cookie
    res = room.client.get("/api/player/team")
    assert res.status_code == 401
    res = room.client.post("/api/player/teams", json={"slug": "knights", "display_name": "Knights"})
    assert res.status_code == 401


def test_csrf_protection_on_mutations(room):
    login(room, "player", "alice")
    # Missing CSRF
    res = room.client.post("/api/player/teams", json={"slug": "knights", "display_name": "Knights"})
    assert res.status_code == 403
    assert "CSRF" in res.text

    # Bad CSRF
    headers = {"X-CSRF-Token": "0" * 64}
    res = room.client.post("/api/player/teams", json={"slug": "knights", "display_name": "Knights"}, headers=headers)
    assert res.status_code == 403


def test_origin_and_proxy_header_guards(room):
    login(room, "player", "alice")
    c_hdr = csrf(room, "player")

    # Wrong Origin
    bad_origin = dict(c_hdr)
    room.client.headers["Origin"] = "https://evil.attacker.com"
    res = room.client.post("/api/player/teams", json={"slug": "knights", "display_name": "Knights"}, headers=bad_origin)
    assert res.status_code == 403
    room.client.headers["Origin"] = ORIGIN

    # Forbidden proxy header
    headers = {**c_hdr, "X-Forwarded-For": "1.2.3.4"}
    res = room.client.post("/api/player/teams", json={"slug": "knights", "display_name": "Knights"}, headers=headers)
    assert res.status_code == 403


def test_audience_separation_and_extra_fields(room):
    login(room, "admin", "admin")
    c_hdr = csrf(room, "admin")

    # Admin session cookie used on player endpoint
    res = room.client.post("/api/player/teams", json={"slug": "knights", "display_name": "Knights"}, headers=c_hdr)
    assert res.status_code in (401, 403)

    # Extra fields in request body rejected (StrictBody forbid)
    login(room, "player", "alice")
    p_hdr = csrf(room, "player")
    res = room.client.post("/api/player/teams", json={"slug": "knights", "display_name": "Knights", "extra": "forbidden"}, headers=p_hdr)
    assert res.status_code == 422


# --- Full Team Lifecycle & Membership Flow ---

def test_full_team_lifecycle_and_rbac(room):
    # 1. Alice creates team
    login(room, "player", "alice")
    h_alice = csrf(room, "player")
    res = room.client.post("/api/player/teams", json={"slug": "neon-knights", "display_name": "Neon Knights"}, headers=h_alice)
    assert res.status_code == 201, res.text
    team_data = res.json()["team"]
    team_id = team_data["id"]
    assert team_data["slug"] == "neon-knights"
    assert team_data["status"] == "DRAFT"

    # 2. Alice gets my-team
    res = room.client.get("/api/player/team")
    assert res.status_code == 200
    assert res.json()["my_role"] == "CAPTAIN"
    assert res.json()["team"]["id"] == team_id

    # 3. Alice updates team display name
    res = room.client.patch(f"/api/player/teams/{team_id}", json={"display_name": "Neon Knights Elite"}, headers=h_alice)
    assert res.status_code == 200
    assert res.json()["team"]["display_name"] == "Neon Knights Elite"

    # 4. Alice activates team
    res = room.client.post(f"/api/player/teams/{team_id}/activate", json={}, headers=h_alice)
    assert res.status_code == 200
    assert res.json()["team"]["status"] == "ACTIVE"

    # 5. Alice invites Bob
    res = room.client.post(f"/api/player/teams/{team_id}/invitations", json={"username": "bob"}, headers=h_alice)
    assert res.status_code == 201
    inv_id = res.json()["invitation"]["id"]

    # 6. Bob logs in and checks invitations
    login(room, "player", "bob")
    h_bob = csrf(room, "player")
    res = room.client.get("/api/player/team-invitations")
    assert res.status_code == 200
    invitations = res.json()["invitations"]
    assert len(invitations) == 1
    assert invitations[0]["id"] == inv_id

    # 7. Charlie cannot accept Bob's invitation (IDOR)
    login(room, "player", "charlie")
    h_charlie = csrf(room, "player")
    res = room.client.post(f"/api/player/team-invitations/{inv_id}/accept", json={}, headers=h_charlie)
    assert res.status_code == 403

    # 8. Bob accepts invitation
    login(room, "player", "bob")
    h_bob = csrf(room, "player")
    res = room.client.post(f"/api/player/team-invitations/{inv_id}/accept", json={}, headers=h_bob)
    assert res.status_code == 200, res.text
    assert res.json()["my_role"] == "MEMBER"

    # 9. Bob cannot perform Captain actions (RBAC)
    res = room.client.patch(f"/api/player/teams/{team_id}", json={"display_name": "Hacked"}, headers=h_bob)
    assert res.status_code == 403
    res = room.client.post(f"/api/player/teams/{team_id}/invitations", json={"username": "charlie"}, headers=h_bob)
    assert res.status_code == 403

    # 10. List members
    res = room.client.get(f"/api/player/teams/{team_id}/members")
    assert res.status_code == 200
    members = res.json()["members"]
    assert len(members) == 2

    # 11. Charlie (outsider) cannot view members (IDOR)
    login(room, "player", "charlie")
    res = room.client.get(f"/api/player/teams/{team_id}/members")
    assert res.status_code == 403

    # 12. Alice transfers captaincy to Bob
    login(room, "player", "alice")
    h_alice = csrf(room, "player")
    bob_user_id = next(m["user_id"] for m in members if m["username"] == "bob")
    res = room.client.post(f"/api/player/teams/{team_id}/captain-transfer",
                            json={"new_captain_user_id": bob_user_id}, headers=h_alice)
    assert res.status_code == 200
    assert res.json()["transferred"] is True
    assert res.json()["promoted"]["user_id"] == bob_user_id
    assert res.json()["promoted"]["team_role"] == "CAPTAIN"

    # 13. Alice is now Member, leaves team
    res = room.client.post(f"/api/player/teams/{team_id}/leave", json={}, headers=h_alice)
    assert res.status_code == 200
    assert res.json()["left"] is True

    # 14. Bob archives team
    login(room, "player", "bob")
    h_bob = csrf(room, "player")
    res = room.client.post(f"/api/player/teams/{team_id}/archive", json={}, headers=h_bob)
    assert res.status_code == 200
    assert res.json()["team"]["status"] == "ARCHIVED"


# --- Admin Inspection and Recovery ---

def test_admin_team_endpoints(room):
    # Setup a team with Alice and Bob
    login(room, "player", "alice")
    h_alice = csrf(room, "player")
    res = room.client.post("/api/player/teams", json={"slug": "alpha-squad", "display_name": "Alpha Squad"}, headers=h_alice)
    team_id = res.json()["team"]["id"]
    res = room.client.post(f"/api/player/teams/{team_id}/invitations", json={"username": "bob"}, headers=h_alice)
    inv_id = res.json()["invitation"]["id"]
    login(room, "player", "bob")
    h_bob = csrf(room, "player")
    room.client.post(f"/api/player/team-invitations/{inv_id}/accept", json={}, headers=h_bob)

    # Admin lists teams
    login(room, "admin", "admin")
    h_admin = csrf(room, "admin")
    res = room.client.get("/api/admin/teams")
    assert res.status_code == 200
    assert len(res.json()["teams"]) >= 1

    # Admin inspects team details
    res = room.client.get(f"/api/admin/teams/{team_id}")
    assert res.status_code == 200
    detail = res.json()
    assert detail["team"]["slug"] == "alpha-squad"
    assert len(detail["members"]) == 2

    # An active Captain cannot be overridden by Admin recovery.
    bob_id = next(m["user_id"] for m in detail["members"] if m["username"] == "bob")
    res = room.client.post(f"/api/admin/teams/{team_id}/captain-transfer",
                            json={"new_captain_user_id": bob_id}, headers=h_admin)
    assert res.status_code == 409

    # Disable the Captain before performing audited recovery.
    from backend.account_database import transaction
    runtime = room.app.state.account_http
    with runtime.database.writer_connection(runtime.writer) as connection, transaction(connection):
        connection.execute("UPDATE users SET status='DISABLED' WHERE username='alice'")

    res = room.client.post(f"/api/admin/teams/{team_id}/captain-transfer",
                            json={"new_captain_user_id": bob_id}, headers=h_admin)
    assert res.status_code == 200, res.text
    assert res.json()["promoted"]["user_id"] == bob_id

    # Admin recovery archive
    res = room.client.post(f"/api/admin/teams/{team_id}/archive", json={}, headers=h_admin)
    assert res.status_code == 200
    assert res.json()["team"]["status"] == "ARCHIVED"


# --- C1 Boundaries: 403 Team Bot / Active Bot placeholders ---

def test_team_bots_require_membership(room):
    login(room, "player", "alice")
    h_alice = csrf(room, "player")
    assert room.client.get("/api/player/bots").status_code == 403
    assert room.client.get("/api/player/active-bot?game_id=robot_battle").status_code == 403
    assert room.client.put("/api/player/active-bot", json={"game_id":"robot_battle","bot_id":"unknown"}, headers=h_alice).status_code == 403


# --- Gate OFF Compatibility ---

def test_gates_off_preserves_legacy_application(tmp_path):
    settings = HTTPAuthSettings(enabled=False, account_only=False)
    app = create_app(tmp_path, account_http=settings)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        # Legacy health endpoint
        res = client.get("/api/health")
        assert res.status_code == 200
        assert res.json()["account_auth"] is False
        assert res.json()["account_only"] is False

        # Team endpoints are not available when gate is OFF
        res = client.get("/api/player/team")
        assert res.status_code in (404, 403)


def test_session_expiry_and_revocation_on_team_http(room):
    login(room, "player", "alice")
    h_alice = csrf(room, "player")

    # Valid request
    res = room.client.get("/api/player/team")
    assert res.status_code == 200 and res.json()["team"] is None  # No Team yet

    # Expire session by advancing clock past absolute TTL
    room.clock.now += 8 * 3600 + 1
    res = room.client.get("/api/player/team")
    assert res.status_code == 401


def test_disabled_account_cannot_call_team_endpoints(room):
    login(room, "player", "alice")

    # Disable Alice's account using the runtime's existing writer
    runtime = room.app.state.account_http
    from backend.account_database import transaction
    with runtime.database.writer_connection(runtime.writer) as connection, transaction(connection):
        connection.execute("UPDATE users SET status='DISABLED' WHERE username='alice'")

    # Alice's subsequent requests must fail with 401
    res = room.client.get("/api/player/team")
    assert res.status_code == 401


def test_duplicate_team_slug_and_player_in_two_teams_http(room):
    login(room, "player", "alice")
    h_alice = csrf(room, "player")
    res = room.client.post("/api/player/teams", json={"slug": "unique-squad", "display_name": "Unique Squad"}, headers=h_alice)
    assert res.status_code == 201

    # Alice attempts to create second team -> 409
    res = room.client.post("/api/player/teams", json={"slug": "second-squad", "display_name": "Second Squad"}, headers=h_alice)
    assert res.status_code == 409
    assert "already has an active team" in res.text

    # Bob attempts to create team with duplicate slug -> 409
    login(room, "player", "bob")
    h_bob = csrf(room, "player")
    res = room.client.post("/api/player/teams", json={"slug": "unique-squad", "display_name": "Another Squad"}, headers=h_bob)
    assert res.status_code == 409
    assert "slug is already in use" in res.text


def test_get_team_does_not_extend_idle_session(room):
    login(room, "player", "alice")
    h = csrf(room, "player")
    assert room.client.post("/api/player/teams", json={"slug":"idle-qa", "display_name":"Idle QA"}, headers=h).status_code == 201
    runtime = room.app.state.account_http
    with runtime.database.writer_connection(runtime.writer) as conn:
        since = conn.execute("SELECT s.last_seen_at FROM auth_sessions s JOIN users u ON s.user_id=u.id WHERE u.username='alice' ORDER BY s.created_at DESC LIMIT 1").fetchone()[0]
    for seconds in (20, 40, 80):
        room.clock.now = since + seconds
        assert room.client.get("/api/player/team").status_code == 200
    with runtime.database.writer_connection(runtime.writer) as conn:
        assert conn.execute("SELECT s.last_seen_at FROM auth_sessions s JOIN users u ON s.user_id=u.id WHERE u.username='alice' ORDER BY s.created_at DESC LIMIT 1").fetchone()[0] == since
