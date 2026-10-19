"""Disposable HTTPS Account-Only tests for username-only signup and Admin-assisted recovery."""
import pytest
from fastapi.testclient import TestClient

from backend.account_database import AccountDatabase
from backend.admin_cli import bootstrap_admin, enroll_admin_totp
from backend.auth_http import HTTPAuthSettings
from backend.main import create_app
from backend.network import NetworkSettings
from backend import totp

PASSWORD = "disposable-username-signup-password 17"
NEW_PASSWORD = "replacement-username-signup-password 18"
DOMAIN = "arena.example.org"
ORIGIN = "https://" + DOMAIN
SECRET = "test-edge-only-" + "x" * 50


class Clock:
    def __init__(self):
        self.now = 2_000_000_000

    def __call__(self):
        return self.now


def headers(**extra):
    return {"Host": DOMAIN, "Origin": ORIGIN,
            "X-Arena-Proxy-Secret": SECRET, "X-Arena-HTTPS": "1",
            "X-Arena-Client-IP": "198.51.100.3", **extra}


def settings(clock, *, enabled=True):
    return HTTPAuthSettings(
        enabled=True, account_only=True, self_registration=enabled,
        require_admin_totp=True, public_https=True, allow_public_username_signup=True,
        gateway_secret=SECRET, origins=(ORIGIN,), clock=clock, rate_clock=clock)


def create_client(tmp_path, clock):
    network = NetworkSettings(allowed_hosts=(DOMAIN,), public_gateway=True)
    return TestClient(create_app(tmp_path, network=network, account_http=settings(clock)),
                      base_url="http://" + DOMAIN, client=("127.0.0.1", 54200))


def test_public_username_signup_is_opt_in_and_does_not_require_smtp():
    clock = Clock()
    with pytest.raises(ValueError, match="delivered email verification or explicit"):
        HTTPAuthSettings(enabled=True, account_only=True, self_registration=True,
                         require_admin_totp=True, public_https=True,
                         gateway_secret=SECRET, origins=(ORIGIN,), clock=clock)
    with pytest.raises(ValueError, match="HTTPS Account-Only"):
        HTTPAuthSettings(enabled=True, account_only=True, origins=("https://testserver",),
                         allow_public_username_signup=True)


def test_username_only_registration_login_recovery_and_session_fencing(tmp_path):
    clock = Clock()
    data_dir = tmp_path / "data"
    bootstrap_admin(data_dir, "teacher.admin", PASSWORD)
    secret = enroll_admin_totp(data_dir, "teacher.admin")

    with create_client(tmp_path, clock) as client:
        # A same-origin browser GET to /api/health omits the Origin header.
        health = client.get("/api/health", headers={"Host": DOMAIN}).json()
        client.headers.update(headers())
        assert health["self_registration"] is True
        assert health["username_only_signup"] is True
        response = client.post("/api/account/auth/register",
                               json={"username": "Student01", "password": PASSWORD})
        assert response.status_code == 201, response.text
        assert response.json()["account"]["username"] == "student01"
        assert response.json()["account"]["system_role"] == "PLAYER"
        assert response.json()["account"]["status"] == "ACTIVE"

        with AccountDatabase(data_dir).read() as connection:
            user = connection.execute("SELECT id FROM users WHERE username='student01'").fetchone()
            assert user is not None
            assert connection.execute("SELECT count(*) FROM user_emails WHERE user_id=?", (user["id"],)).fetchone()[0] == 0

        assert client.post("/api/account/auth/register",
                           json={"username": "STUDENT01", "password": PASSWORD}).status_code == 409
        assert client.post("/api/account/auth/register",
                           json={"username": "second01", "password": "short"}).status_code == 422
        assert client.post("/api/account/auth/request-reset",
                           json={"username": "student01", "email": "a@example.org"}).status_code == 404

        player_login = client.post("/api/account/auth/login",
                                   json={"username": "student01", "password": PASSWORD})
        assert player_login.status_code == 200, player_login.text
        assert player_login.json()["audience"] == "player"
        assert "secure" in player_login.headers["set-cookie"].lower()

        # CSRF and Admin MFA are mandatory even for the recovery issuer.
        denied = client.post("/api/admin/auth/player-recovery",
                             json={"username": "student01"})
        assert denied.status_code in (401, 403)
        otp = totp.code_at(secret, clock.now // 30)
        login = client.post("/api/account/auth/login",
                            json={"username": "teacher.admin", "password": PASSWORD, "otp": otp})
        assert login.status_code == 200, login.text
        admin_token = login.cookies["arena_account_admin_v2"]
        cookie = {"Cookie": "arena_account_admin_v2=" + admin_token}
        csrf_response = client.get("/api/admin/auth/csrf", headers=cookie)
        assert csrf_response.status_code == 200, csrf_response.text
        csrf = csrf_response.json()["csrf_token"]
        assert client.post("/api/admin/auth/player-recovery",
                           headers=cookie, json={"username": "student01"}).status_code == 403
        admin_headers = {**cookie, "X-CSRF-Token": csrf}
        assert client.post("/api/admin/auth/player-recovery",
                           headers=admin_headers, json={"username": "teacher.admin"}).status_code == 409
        issued = client.post("/api/admin/auth/player-recovery",
                             headers=admin_headers, json={"username": "student01"})
        assert issued.status_code == 201, issued.text
        token = issued.json()["token"]
        assert len(token) == 43
        assert issued.json()["expires_at"] == clock.now + 1800
        with AccountDatabase(data_dir).read() as connection:
            audit = [row[0] for row in connection.execute("SELECT details_json FROM audit_events")]
            assert all(token not in detail for detail in audit)

        reset = client.post("/api/account/auth/reset-password",
                            json={"token": token, "password": NEW_PASSWORD})
        assert reset.status_code == 200, reset.text
        assert reset.json()["account"]["system_role"] == "PLAYER"
        assert client.post("/api/account/auth/reset-password",
                           json={"token": token, "password": NEW_PASSWORD}).status_code == 400
        assert client.post("/api/account/auth/login",
                           json={"username": "student01", "password": PASSWORD}).status_code == 401
        assert client.post("/api/account/auth/login",
                           json={"username": "student01", "password": NEW_PASSWORD}).status_code == 200


def test_recovery_token_expiry_and_latest_only(tmp_path):
    clock = Clock()
    data_dir = tmp_path / "data"
    bootstrap_admin(data_dir, "admin", PASSWORD)
    secret = enroll_admin_totp(data_dir, "admin")
    with create_client(tmp_path, clock) as client:
        client.headers.update(headers())
        assert client.post("/api/account/auth/register",
                           json={"username": "alice", "password": PASSWORD}).status_code == 201
        login = client.post("/api/account/auth/login", json={
            "username": "admin", "password": PASSWORD,
            "otp": totp.code_at(secret, clock.now // 30)})
        assert login.status_code == 200, login.text
        admin_cookie = {"Cookie": "arena_account_admin_v2=" + login.cookies["arena_account_admin_v2"]}
        csrf = client.get("/api/admin/auth/csrf", headers=admin_cookie).json()["csrf_token"]
        opts = {**admin_cookie, "X-CSRF-Token": csrf}
        old = client.post("/api/admin/auth/player-recovery", headers=opts,
                          json={"username": "alice"}).json()["token"]
        latest = client.post("/api/admin/auth/player-recovery", headers=opts,
                             json={"username": "alice"}).json()["token"]
        assert old != latest
        assert client.post("/api/account/auth/reset-password",
                           json={"token": old, "password": NEW_PASSWORD}).status_code == 400
        clock.now += 1800
        assert client.post("/api/account/auth/reset-password",
                           json={"token": latest, "password": NEW_PASSWORD}).status_code == 400
