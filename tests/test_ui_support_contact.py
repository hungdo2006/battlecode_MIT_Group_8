"""The recovery contact is public, configurable and restricted to safe URLs."""
import pytest
from fastapi.testclient import TestClient

from backend.auth_http import HTTPAuthSettings
from backend.admin_cli import bootstrap_admin
from backend.main import create_app


@pytest.mark.parametrize("url", ["javascript:alert(1)", "http://example.org", "mailto:", "https://", "mailto:a b@example.org"])
def test_reject_unsafe_or_empty_recovery_contact(url):
    with pytest.raises(ValueError, match="ARENA_SUPPORT_URL"):
        HTTPAuthSettings(support_url=url)


def test_contact_environment_is_exposed_without_login(tmp_path, monkeypatch):
    bootstrap_admin(tmp_path / "data", "qa.admin", "disposable-contact-test-password")
    monkeypatch.setenv("ARENA_ACCOUNT_AUTH", "1")
    monkeypatch.setenv("ARENA_ACCOUNT_ONLY", "1")
    monkeypatch.setenv("ARENA_AUTH_ORIGINS", "http://testserver")
    monkeypatch.setenv("ARENA_AUTH_ALLOW_HTTP", "1")
    monkeypatch.setenv("ARENA_SUPPORT_URL", "https://support.example.org/arena")
    with TestClient(create_app(tmp_path)) as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["support_url"] == "https://support.example.org/arena"
