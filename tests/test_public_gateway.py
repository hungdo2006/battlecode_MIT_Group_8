"""Phase 4.3 pre-AWS gateway: no direct trust, even with a public Host."""
import pytest
from fastapi.testclient import TestClient

from backend.auth_http import HTTPAuthSettings
from backend.main import create_app
from backend.network import NetworkSettings

from backend.account_database import AccountDatabase
from backend.admin_cli import bootstrap_admin
from backend.auth_limits import AuthRateLimiter
from backend.auth_service import AuthService
from backend.writer_lock import WriterLock

PASSWORD = "public-gateway disposable test passphrase 84"


class Clock:
    def __init__(self):
        self.now = 2_000_000_000
    def __call__(self):
        return self.now


def seed_accounts(base, clock):
    data = base / "data"
    bootstrap_admin(data, "admin", PASSWORD)
    with WriterLock(data) as writer, AccountDatabase(data).writer_connection(writer) as conn:
        service = AuthService(conn, writer, clock=clock, login_limiter=AuthRateLimiter())
        actor = service.login("admin", PASSWORD, audience="ADMIN", source_key="seed").principal
        invitation = service.issue_invitation(actor, "alice")
        service.activate(invitation.token, PASSWORD)

DOMAIN = "arena.example.org"
ORIGIN = "https://" + DOMAIN
SECRET = "unit-test-private-gateway-proof-" + "a" * 48


def gateway_settings(clock):
    return HTTPAuthSettings(enabled=True, account_only=True,
                            require_admin_totp=True, public_https=True,
                            gateway_secret=SECRET, origins=(ORIGIN,),
                            clock=clock, rate_clock=clock)


def gateway_headers(**extra):
    return {"Host": DOMAIN, "Origin": ORIGIN,
            "X-Arena-Proxy-Secret": SECRET, "X-Arena-Client-IP": "198.51.100.3",
            "X-Arena-HTTPS": "1", **extra}


def test_public_gateway_validates_edge_secret_origin_source_and_secure_cookies(tmp_path):
    clock = Clock()
    seed_accounts(tmp_path, clock)
    settings = gateway_settings(clock)
    network = NetworkSettings(allowed_hosts=(DOMAIN,), public_gateway=True)
    with TestClient(create_app(tmp_path, network=network, account_http=settings),
                    base_url="http://" + DOMAIN,
                    client=("127.0.0.1", 50150)) as client:
        path = "/api/account/auth/login"
        credentials = {"username": "alice", "password": PASSWORD}
        assert client.post(path, json=credentials, headers=gateway_headers()).status_code == 200
        granted = client.post(path, json=credentials, headers=gateway_headers())
        assert granted.status_code == 200, granted.text
        cookie = granted.headers["set-cookie"].lower()
        assert "secure" in cookie and "httponly" in cookie and "samesite=strict" in cookie
        assert "path=/api/player" in cookie
        assert client.post(path, json=credentials, headers={
            "Host": DOMAIN, "Origin": ORIGIN
        }).status_code == 403
        assert client.post(path, json=credentials, headers=gateway_headers(
            **{"X-Arena-Proxy-Secret": "wrong"})).status_code == 403
        assert client.post(path, json=credentials, headers=gateway_headers(
            **{"X-Arena-Client-IP": "not-a-client-ip"})).status_code == 403
        assert client.post(path, json=credentials, headers=gateway_headers(
            **{"X-Forwarded-For": "198.51.100.4"})).status_code == 403
        assert client.post(path, json=credentials, headers=gateway_headers(
            **{"Origin": "https://evil.example"})).status_code == 403
        assert client.post(path, json=credentials, headers=gateway_headers(
            **{"Host": "evil.example"})).status_code == 403
        assert client.post(path, json=credentials, headers=gateway_headers(
            **{"X-Arena-HTTPS": "0"})).status_code == 403


def test_public_gateway_fails_closed_on_bad_flags_or_mismatched_host(tmp_path):
    clock = Clock()
    with pytest.raises(ValueError, match="Public Gateway requires Account-Only and Admin TOTP"):
        HTTPAuthSettings(enabled=True, account_only=True, origins=(ORIGIN,),
                         public_https=True, gateway_secret=SECRET)
    with pytest.raises(ValueError, match="random secret"):
        HTTPAuthSettings(enabled=True, account_only=True, require_admin_totp=True,
                         public_https=True, gateway_secret="weak", origins=(ORIGIN,))
    with pytest.raises(ValueError, match="Public Gateway forbids HTTP"):
        HTTPAuthSettings(enabled=True, account_only=True, require_admin_totp=True,
                         public_https=True, gateway_secret=SECRET, origins=(ORIGIN,), allow_http=True)
    settings = gateway_settings(clock)
    with pytest.raises(ValueError, match="settings must agree"):
        create_app(tmp_path, account_http=settings, network=NetworkSettings())
    with pytest.raises(ValueError, match="allowed hosts must exactly match"):
        create_app(tmp_path, account_http=settings, network=NetworkSettings(
            allowed_hosts=("another.example.org",), public_gateway=True))
    with pytest.raises(ValueError, match="Named/public hosts"):
        NetworkSettings(allowed_hosts=(DOMAIN,), read_only=False)


def test_https_gateway_font_origin_is_validated_at_the_authenticated_edge(tmp_path):
    # Browser font requests include Origin even on same-site GET. Caddy's
    # upstream is HTTP, but its authenticated public origin is HTTPS.
    clock = Clock()
    seed_accounts(tmp_path, clock)
    network = NetworkSettings(allowed_hosts=(DOMAIN,), public_gateway=True)
    with TestClient(create_app(tmp_path, network=network,
                               account_http=gateway_settings(clock)),
                    base_url="http://" + DOMAIN,
                    client=("127.0.0.1", 50150)) as client:
        path = "/static/fonts/InterVariable.woff2"
        response = client.get(path, headers=gateway_headers())
        assert response.status_code == 200
        assert response.content[:4] == b"wOF2"
        for changes in (
            {"Origin": "https://evil.example"},
            {"Origin": "http://" + DOMAIN},
            {"Origin": ORIGIN + ":8443"},
            {"Host": "evil.example"},
            {"X-Arena-Proxy-Secret": "wrong"},
            {"X-Arena-Client-IP": "not-an-ip"},
            {"X-Arena-HTTPS": "0"},
            {"X-Forwarded-Proto": "https"},
            {"Forwarded": "proto=https"},
            {"X-Real-IP": "198.51.100.4"},
        ):
            assert client.get(path, headers=gateway_headers(**changes)).status_code == 403
        assert client.get(path, headers={"Host": DOMAIN, "Origin": ORIGIN}).status_code == 403
        assert client.get(path, headers=[*gateway_headers().items(),
                                        ("Origin", "https://evil.example")]).status_code == 403
        for name, value in (("Host", DOMAIN), ("X-Arena-Proxy-Secret", SECRET),
                            ("X-Arena-HTTPS", "1"), ("X-Arena-Client-IP", "198.51.100.3")):
            assert client.get(path, headers=[*gateway_headers().items(),
                                            (name, value)]).status_code == 403


def test_font_gateway_metadata_does_not_authorize_a_public_backend_peer(tmp_path):
    clock = Clock()
    seed_accounts(tmp_path, clock)
    network = NetworkSettings(allowed_hosts=(DOMAIN,), public_gateway=True)
    with TestClient(create_app(tmp_path, network=network,
                               account_http=gateway_settings(clock)),
                    base_url="http://" + DOMAIN,
                    client=("203.0.113.12", 50150)) as client:
        assert client.get("/static/fonts/InterVariable.woff2",
                          headers=gateway_headers()).status_code == 403
