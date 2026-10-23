"""Account-only round rule publication and spectator permission regression."""
from test_team_http import room, login, csrf
from test_team_tournament_http import create_elimination_tournament


def create_game(room):
    _, tour = create_elimination_tournament(room, ["alice", "bob"])
    fixture = tour["fixtures"][0]
    return tour["id"], fixture


def test_round_rules_are_atomic_and_lock_official_schedule(room):
    tournament, fixture = create_game(room)
    stage, number = fixture["stage"], fixture["round_number"]
    endpoint = f"/api/admin/team-tournaments/{tournament}/rounds/{stage}/{number}"
    rules = {"map_size": 15, "initial_hp": 150, "damage": 23, "max_turns": 75}
    payload = {"rules": rules, "editing_minutes": 20}

    # Without Admin CSRF the policy cannot be mutated.
    assert room.client.put(endpoint + "/rules", json=payload).status_code == 403
    draft = room.client.put(endpoint + "/rules", json=payload, headers=csrf(room, "admin"))
    assert draft.status_code == 200, draft.text
    stored = draft.json()["tournament"]["round_rules"]
    assert len(stored) == 1 and stored[0]["status"] == "DRAFT"

    login(room, "player", "alice")
    player = room.client.get(f"/api/player/team-tournaments/{tournament}")
    assert player.status_code == 200
    assert player.json()["tournament"]["round_rules"] == []  # Confidential until publication.

    login(room, "admin", "admin")
    path = f"/api/admin/team-tournaments/{tournament}/fixtures/{fixture['id']}/schedule"
    result = room.client.post(path, json={
        "bot_lock_at": room.clock.now + 60, "scheduled_at": room.clock.now + 120
    }, headers=csrf(room, "admin"))
    assert result.status_code == 409  # Cannot bypass the draft.

    published = room.client.post(endpoint + "/publish", json={}, headers=csrf(room, "admin"))
    assert published.status_code == 200, published.text
    policy = published.json()["tournament"]["round_rules"][0]
    assert policy["status"] == "PUBLISHED"
    assert policy["bot_lock_at"] == room.clock.now + 1200
    assert policy["rules"] == rules
    assert room.client.put(endpoint + "/rules", json=payload,
                           headers=csrf(room, "admin")).status_code == 409

    early = room.client.post(path, json={
        "bot_lock_at": room.clock.now + 1199, "scheduled_at": room.clock.now + 1400
    }, headers=csrf(room, "admin"))
    assert early.status_code == 409
    good = room.client.post(path, json={
        "bot_lock_at": room.clock.now + 1200, "scheduled_at": room.clock.now + 1450
    }, headers=csrf(room, "admin"))
    assert good.status_code == 201, good.text
    request = good.json()["request"]
    assert request["rules_snapshot"] == rules
    assert room.client.put(endpoint + "/rules", json=payload,
                           headers=csrf(room, "admin")).status_code == 409
    assert room.client.post(f"/api/admin/official-matches/{request['id']}/cancel",
                            json={}, headers=csrf(room, "admin")).status_code == 200
    assert room.client.put(endpoint + "/rules", json=payload,
                           headers=csrf(room, "admin")).status_code == 409


def test_scoreboard_privacy_and_public_api_are_independent_of_participation(room):
    tournament, fixture = create_game(room)
    public_api = "/api/public/standings"
    assert room.client.get(public_api).json()["tournaments"] == []
    assert room.client.get("/results").status_code == 200

    login(room, "player", "charlie")
    response = room.client.get(f"/api/player/team-tournaments/{tournament}")
    assert response.status_code == 404
    listing = room.client.get("/api/player/team-tournaments").json()["tournaments"]
    assert all(t["id"] != tournament for t in listing)

    login(room, "admin", "admin")
    vis = f"/api/admin/team-tournaments/{tournament}/visibility"
    assert room.client.put(vis, json={"visibility": "PUBLIC"}).status_code == 403
    assert room.client.put(vis, json={"visibility": "PUBLIC"},
                           headers=csrf(room, "admin")).status_code == 200
    public = room.client.get(public_api).json()["tournaments"]
    assert len(public) == 1
    assert set(public[0]) == {"id","name","game_id","status","format","standings","groups"}
    assert "fixtures" not in public[0] and "bracket" not in public[0]

    login(room, "player", "charlie")
    assert room.client.get(f"/api/player/team-tournaments/{tournament}").status_code == 200
    login(room, "admin", "admin")
    assert room.client.put(vis, json={"visibility": "SIGNED_IN"},
                           headers=csrf(room,"admin")).status_code == 200
    assert room.client.get(public_api).json()["tournaments"] == []
    login(room, "player", "charlie")
    assert room.client.get(f"/api/player/team-tournaments/{tournament}").status_code == 200
    login(room, "admin", "admin")
    assert room.client.put(vis, json={"visibility":"PRIVATE"},
                           headers=csrf(room,"admin")).status_code == 200
    login(room, "player", "charlie")
    assert room.client.get(f"/api/player/team-tournaments/{tournament}").status_code == 404
