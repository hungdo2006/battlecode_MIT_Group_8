"""B1 remote HTTP boundary: machine secret, no browser cookies, no Docker fallback."""
import pytest
from fastapi.testclient import TestClient

from backend.auth_http import HTTPAuthSettings
from backend.main import create_app
from test_team_http import Clock, ORIGIN, PASSWORD, seed_accounts


@pytest.fixture
def remote_room(tmp_path, monkeypatch):
    key = "qa-outbound-runner-key-" + "y" * 48
    monkeypatch.setenv("ARENA_RUNNER", "remote_sandbox")
    monkeypatch.setenv("ARENA_REMOTE_RUNNER_KEY", key)
    clock = Clock()
    seed_accounts(tmp_path, clock)
    settings = HTTPAuthSettings(enabled=True, account_only=True,
                                origins=(ORIGIN,), clock=clock, rate_clock=clock)
    app = create_app(tmp_path, account_http=settings)
    with TestClient(app, base_url=ORIGIN, client=("127.0.0.1", 51000)) as client:
        client.headers["Origin"] = ORIGIN
        yield app, client, key


def test_remote_agent_auth_boundary_and_one_worker_session(remote_room):
    app, client, key = remote_room
    path = "/api/remote-runner/"
    assert client.post(path + "connect", json={}).status_code == 401
    assert client.post(path + "connect", json={},
                       headers={"Authorization": "Bearer wrong"}).status_code == 401

    headers = {"Authorization": "Bearer " + key}
    first = client.post(path + "connect", json={}, headers=headers)
    assert first.status_code == 200, first.text
    session = first.json()["session"]
    assert len(session) == 48
    assert "set-cookie" not in first.headers
    assert client.post(path + "connect", json={}, headers=headers).status_code == 409

    # Never trust a browser cookie or an invalid/old worker session.
    assert client.post(path + "disconnect", json={}, headers=headers).status_code == 409
    connected = {**headers, "X-Arena-Runner-Session": session}
    disconnected = client.post(path + "disconnect", json={}, headers=connected)
    assert disconnected.status_code == 200
    assert client.post(path + "connect", json={}, headers=headers).status_code == 200


def test_remote_runner_not_ready_without_real_pc(remote_room):
    app, client, key = remote_room
    assert app.state.runner.mode == "sandbox"  # Official scheduling remains sandbox-only.
    assert app.state.runner.health()["ready"] is False
    # A public player must never see a fake healthy runner.
    unavailable = client.get("/api/health")
    assert unavailable.status_code == 503


def test_remote_http_rejects_large_and_unauthenticated_payloads(remote_room):
    app, client, key = remote_room
    path = "/api/remote-runner/respond"
    # Check authorization and size before JSON parsing or side effects.
    response = client.post(path, content=b"x" * 100,
                           headers={"Content-Type": "application/json"})
    assert response.status_code == 401
    response = client.post(path, content=b"{}", headers={
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
        "Content-Length": str(18 * 1024 * 1024),
    })
    assert response.status_code in (400, 413)
