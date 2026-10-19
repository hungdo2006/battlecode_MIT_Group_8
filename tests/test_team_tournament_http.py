"""Account-only Team tournament bracket and tie-break flows."""
from backend.account_database import transaction
from backend.official_service import OfficialSchedule
from backend.team_tournament_service import advance_single_elimination
from test_team_http import csrf, login, room


GAME = "robot_battle"


def create_active_team(room, username, slug):
    login(room, "player", username)
    headers = csrf(room, "player")
    created = room.client.post("/api/player/teams", json={
        "slug": slug, "display_name": slug.title()
    }, headers=headers)
    assert created.status_code == 201, created.text
    team_id = created.json()["team"]["id"]
    activated = room.client.post(f"/api/player/teams/{team_id}/activate", json={}, headers=headers)
    assert activated.status_code == 200, activated.text
    return team_id


def create_elimination_tournament(room, users):
    teams = [create_active_team(room, username, f"{username}-knockout") for username in users]
    login(room, "admin", "admin")
    created = room.client.post("/api/admin/team-tournaments", json={
        "name": "Knockout QA", "game_id": GAME, "team_ids": teams,
        "format": "single_elimination",
    }, headers=csrf(room, "admin"))
    assert created.status_code == 201, created.text
    tournament = created.json()["tournament"]
    started = room.client.post(f"/api/admin/team-tournaments/{tournament['id']}/start",
                               json={}, headers=csrf(room, "admin"))
    assert started.status_code == 200, started.text
    return teams, started.json()["tournament"]


def test_single_elimination_bye_and_winner_advance(room):
    teams, tournament = create_elimination_tournament(room, ["alice", "bob", "charlie"])
    assert tournament["format"] == "single_elimination"
    assert len(tournament["bracket"]) == 3
    first_round = [slot for slot in tournament["bracket"] if slot["round_number"] == 1]
    ready = [slot for slot in first_round if slot["status"] == "READY"]
    byes = [slot for slot in first_round if slot["status"] == "BYE"]
    assert len(ready) == len(byes) == 1
    final = next(slot for slot in tournament["bracket"] if slot["round_number"] == 2)
    assert final["status"] == "PENDING"
    bye_winner = byes[0]["winner_team_id"]

    runtime = room.app.state.account_http
    with runtime.database.writer_connection(runtime.writer) as connection, transaction(connection):
        connection.execute("""UPDATE team_tournament_bracket_slots
            SET status='COMPLETED',winner_team_id=? WHERE id=?""",
            (ready[0]["team_a_id"], ready[0]["id"]))
        advance_single_elimination(connection, tournament["id"], room.clock.now)

    refreshed = room.client.get(f"/api/admin/team-tournaments/{tournament['id']}").json()["tournament"]
    final = next(slot for slot in refreshed["bracket"] if slot["round_number"] == 2)
    assert final["status"] == "READY"
    assert set((final["team_a_id"], final["team_b_id"])) == {ready[0]["team_a_id"], bye_winner}
    assert len(refreshed["fixtures"]) == 2
    assert set(teams) == {entry["team_id"] for entry in refreshed["teams"]}


def test_elimination_draws_auto_schedule_two_rematches_then_admin_resolves(room):
    teams, tournament = create_elimination_tournament(room, ["alice", "bob"])
    fixture = tournament["fixtures"][0]
    now = room.clock.now
    scheduled = room.client.post(
        f"/api/admin/team-tournaments/{tournament['id']}/fixtures/{fixture['id']}/schedule",
        json={"bot_lock_at": now + 120, "scheduled_at": now + 180},
        headers=csrf(room, "admin"),
    )
    assert scheduled.status_code == 201, scheduled.text

    runtime = room.app.state.account_http
    with runtime.database.writer_connection(runtime.writer) as connection:
        auth = runtime._service(connection)
        service = OfficialSchedule(connection, runtime.writer, auth, room.app.state.store,
                                    room.app.state.registry)
        for _ in range(3):
            with transaction(connection):
                request_row = connection.execute("""SELECT r.* FROM official_match_requests r
                    JOIN team_tournament_fixtures f ON f.official_request_id=r.id WHERE f.id=?""",
                    (fixture["id"],)).fetchone()
                connection.execute("""UPDATE official_match_requests
                    SET status='COMPLETED',locked_at=?,match_id=?,started_at=?,finished_at=?
                    WHERE id=?""",
                    (now, f"test-match-{_}", now, now, request_row["id"]))
                service._handle_team_tournament_result(request_row, {"winner_team_id": None}, now)

        assert connection.execute("""SELECT count(*) FROM team_tournament_fixture_matches
            WHERE fixture_id=?""", (fixture["id"],)).fetchone()[0] == 3
        slot = connection.execute("""SELECT b.status FROM team_tournament_bracket_slots b
            WHERE b.fixture_id=?""", (fixture["id"],)).fetchone()
        assert slot["status"] == "TIE"

    resolved = room.client.post(
        f"/api/admin/team-tournaments/{tournament['id']}/fixtures/{fixture['id']}/resolve-tie",
        json={"winner_team_id": teams[0]}, headers=csrf(room, "admin"),
    )
    assert resolved.status_code == 200, resolved.text
    final = resolved.json()["tournament"]
    assert final["status"] == "COMPLETED"
    assert final["bracket"][0]["winner_team_id"] == teams[0]
