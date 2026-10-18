import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from workflow import player_client


@pytest.fixture
def client(tmp_path, authorize_organizer):
    with TestClient(create_app(tmp_path)) as client:
        authorize_organizer(client)
        yield client


def seed_match(client, *, tournament_id=None, official_request_id=None):
    match = {
        "id": "correction-test-match",
        "game_id": "robot_battle",
        "status": "completed",
        "created_at": "2026-01-01T00:00:00+00:00",
        "finished_at": "2026-01-01T00:01:00+00:00",
        "turn": 4,
        "player_a_id": "player-a",
        "player_a_name_snapshot": "Alice",
        "player_b_id": "player-b",
        "player_b_name_snapshot": "Bob",
        "result": {"winner": "B", "reason": "knockout", "faults": {}, "scores": {"A": 2, "B": 4}},
        "tournament_id": tournament_id,
        "official_request_id": official_request_id,
    }
    client.app.state.store.save_match(match)
    return match


def test_organizer_correction_changes_standings_and_appends_audit(client):
    original = seed_match(client)

    response = client.post(
        f"/api/matches/{original['id']}/correct-result",
        json={"winner": "A", "reason": "Trọng tài nhập nhầm bên thắng"},
    )

    assert response.status_code == 200, response.text
    corrected = response.json()
    assert corrected["result"]["winner"] == "A"
    assert corrected["result"]["reason"] == "organizer_correction"
    assert corrected["result"]["scores"] == {"A": 2, "B": 4}
    assert len(corrected["result_corrections"]) == 1
    audit = corrected["result_corrections"][0]
    assert audit["actor"]["id"]
    assert audit["previous_result"]["winner"] == "B"
    assert audit["new_result"]["winner"] == "A"
    assert audit["reason"] == "Trọng tài nhập nhầm bên thắng"

    standings = {row["player_id"]: row for row in client.get("/api/standings?game_id=robot_battle").json()}
    assert standings["player-a"]["wins"] == 1
    assert standings["player-b"]["losses"] == 1

    persisted = client.app.state.store.get_match(original["id"])
    assert persisted["result_corrections"] == corrected["result_corrections"]


def test_non_organizer_cannot_correct_match(client):
    match = seed_match(client)
    player = player_client(client)

    response = player.post(
        f"/api/matches/{match['id']}/correct-result",
        json={"winner": "A", "reason": "Trọng tài nhập nhầm bên thắng"},
    )

    assert response.status_code == 403
    assert client.app.state.store.get_match(match["id"])["result"]["winner"] == "B"


def test_correction_rejects_active_tournament_and_official_matches(client):
    for field, value in (("tournament_id", "tournament-1"), ("official_request_id", "official-1")):
        match = seed_match(client)
        match[field] = value
        client.app.state.store.save_match(match)

        response = client.post(
            f"/api/matches/{match['id']}/correct-result",
            json={"winner": "A", "reason": "Trọng tài nhập nhầm bên thắng"},
        )

        assert response.status_code == 409
        assert client.app.state.store.get_match(match["id"])["result"]["winner"] == "B"


def test_correction_requires_a_reason_and_a_changed_outcome(client):
    match = seed_match(client)

    missing_reason = client.post(
        f"/api/matches/{match['id']}/correct-result",
        json={"winner": "A", "reason": "no"},
    )
    unchanged = client.post(
        f"/api/matches/{match['id']}/correct-result",
        json={"winner": "B", "reason": "Kết quả đã chính xác"},
    )

    assert missing_reason.status_code == 422
    assert unchanged.status_code == 409
    assert client.app.state.store.get_match(match["id"]).get("result_corrections", []) == []
