import os

import pytest


@pytest.fixture(autouse=True)
def configured_admin_code(monkeypatch):
    # Test-only credential; production reads the user's environment, never this file.
    monkeypatch.setenv("ARENA_ADMIN_CODE", "neon-test-organizer-code")


@pytest.fixture
def authorize_organizer():
    def authorize(client):
        response = client.post("/api/session/organizer", json={"code": os.environ["ARENA_ADMIN_CODE"]})
        assert response.status_code == 200, response.text
        assert response.json()["role"] == "organizer"
    return authorize
