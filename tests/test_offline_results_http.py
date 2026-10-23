"""Account-only HTTP regression for signed offline tournament publication.

Uses an isolated TestClient and a fake completed local event. No AWS services,
real participants or Docker Engine are needed for these API boundary tests.
"""
from copy import deepcopy

import pytest

from backend.offline_results import export_package
from test_team_http import csrf, login, room
from test_offline_results import complete_event
from test_team_tournament_http import create_elimination_tournament


@pytest.fixture
def signed_file(monkeypatch):
    monkeypatch.setenv("ARENA_OFFLINE_SITE_ID", "school-lab-test")
    monkeypatch.setenv("ARENA_OFFLINE_RESULTS_KEY", "test-only-offline-results-key-" + "z" * 40)
    return export_package(complete_event())


def test_offline_preview_and_publish_require_admin_and_csrf(room, signed_file):
    endpoint = "/api/admin/offline-results/preview"
    publish = "/api/admin/offline-results/import"

    assert room.client.get("/api/public/standings").json()["offline_tournaments"] == []
    assert room.client.post(endpoint, json={"package": signed_file}).status_code in (401, 403)
    login(room, "player", "alice")
    assert room.client.post(endpoint, json={"package": signed_file},
                            headers=csrf(room, "player")).status_code in (401, 403)

    login(room, "admin", "admin")
    assert room.client.post(endpoint, json={"package": signed_file}).status_code == 403
    headers = csrf(room, "admin")
    preview = room.client.post(endpoint, json={"package": signed_file}, headers=headers)
    assert preview.status_code == 200, preview.text
    assert preview.json()["preview"]["teams"] == 2
    assert preview.json()["preview"]["source"] == "school-lab-test"
    assert room.client.get("/api/public/standings").json()["offline_tournaments"] == []

    # Preview never writes, import without explicit consent never publishes.
    declined = room.client.post(publish, json={"package": signed_file, "confirm_publish": False},
                                headers=headers)
    assert declined.status_code == 422
    assert room.client.post(publish, json={"package": signed_file, "confirm_publish": True}).status_code == 403
    published = room.client.post(publish, json={"package": signed_file, "confirm_publish": True},
                                 headers=headers)
    assert published.status_code == 200, published.text
    assert published.json()["publication"]["already_imported"] is False
    again = room.client.post(publish, json={"package": signed_file, "confirm_publish": True},
                             headers=headers)
    assert again.status_code == 200
    assert again.json()["publication"]["already_imported"] is True

    public = room.client.get("/api/public/standings").json()
    assert public["tournaments"] == []
    assert len(public["offline_tournaments"]) == 1
    data = public["offline_tournaments"][0]
    assert data["offline"] is True and data["source"] == "school-lab-test"
    assert data["standings"][0]["team_name"] == "Đội A"
    assert "team_id" not in str(data)
    assert "private-match-id" not in str(data)


def test_offline_http_rejects_modified_and_conflicting_signed_results(room, signed_file):
    login(room, "admin", "admin")
    headers = csrf(room, "admin")
    path = "/api/admin/offline-results/import"
    tampered = deepcopy(signed_file)
    tampered["payload"]["tournament"]["standings"][0]["points"] = 900
    assert room.client.post(path, json={"package": tampered, "confirm_publish": True},
                            headers=headers).status_code == 422
    assert room.client.get("/api/public/standings").json()["offline_tournaments"] == []

    assert room.client.post(path, json={"package": signed_file, "confirm_publish": True},
                            headers=headers).status_code == 200
    # Another correctly signed revision of the same event must not overwrite a publication.
    updated = complete_event()
    updated["standings"][0]["points"] = 11
    conflict = export_package(updated)
    refused = room.client.post(path, json={"package": conflict, "confirm_publish": True},
                               headers=headers)
    assert refused.status_code == 422
    assert room.client.get("/api/public/standings").json()["offline_tournaments"][0]["standings"][0]["points"] == 3


def test_offline_export_denied_until_tournament_completed(room, signed_file):
    _, tournament = create_elimination_tournament(room, ["alice", "bob"])
    # Fixture has not run; exporting a partial event would mislead public readers.
    export = room.client.get(f"/api/admin/team-tournaments/{tournament['id']}/offline-export")
    assert export.status_code == 422
    assert "hoàn thành" in export.text
