"""Phase 4.3 pre-AWS gateway: no direct trust, even with a public Host."""
import pytest
from fastapi.testclient import TestClient

from backend.auth_http import HTTPAuthSettings
from backend.main import create_app
from backend.network import NetworkSettings

from tests.test_account_only import Clock, PASSWORD, seed_accounts

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
