import os

import pytest


@pytest.fixture(autouse=True)
def configured_admin_code(monkeypatch):
    # Account HTTP is opt-in. Native regression must not inherit an operator's gate.
    monkeypatch.setenv("ARENA_ACCOUNT_AUTH", "0")
    # Native regression suite deliberately exercises legacy; sandbox has separate
    # real-Engine probes. Never inherit an operator's runner setting accidentally.
    monkeypatch.setenv("ARENA_RUNNER", "legacy")
    # Test-only credential; production reads the user's environment, never this file.
    monkeypatch.setenv("ARENA_ADMIN_CODE", "neon-test-organizer-code")


@pytest.fixture
def authorize_organizer():
    def authorize(client):
        response = client.post("/api/session/organizer", json={"code": os.environ["ARENA_ADMIN_CODE"]})
        assert response.status_code == 200, response.text
        assert response.json()["role"] == "organizer"
        client.app.state._regression_organizer = client
    return authorize


@pytest.fixture
def open_competition():
    def open_room(client, game_id="robot_battle", rules=None):
        state = client.get("/api/competition").json()
        if state["competition_locked"]:
            assert client.post("/api/competition/close").status_code == 200
        assert client.put("/api/games/selected", json={"game_id": game_id}).status_code == 200
        if rules is not None:
            assert client.put(f"/api/games/{game_id}/rules", json=rules).status_code == 200
        response = client.post("/api/competition/open")
        assert response.status_code == 200, response.text
        return response.json()
    return open_room


@pytest.fixture
def stop_backend():
    def stop(client):
        # Real restart: close sockets and the first lifespan BEFORE opening the
        # replacement. Fixture ExitStacks are idempotent at final teardown.
        sockets = getattr(client, '_test_socket_stack', None)
        if sockets is not None:
            sockets.close()
        client.__exit__(None, None, None)
    return stop
