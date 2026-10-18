from backend.engine import create_registry
from backend.storage import Store


def test_standings_include_filtered_win_rate_and_last_five_results(tmp_path):
    store = Store(tmp_path, create_registry())
    outcomes = ["W", "L", "D", "W", "W", "L", "W"]

    # Save newest first to prove form follows result timestamps, not JSON order.
    for index in reversed(range(len(outcomes))):
        outcome = outcomes[index]
        winner = "A" if outcome == "W" else "B" if outcome == "L" else None
        store.save_match({
            "id": f"robot-{index}", "game_id": "robot_battle", "status": "completed",
            "created_at": f"2025-01-{index + 1:02d}T10:00:00+00:00",
            "finished_at": f"2025-01-{index + 1:02d}T10:01:00+00:00",
            "player_a_id": "player", "player_b_id": f"opponent-{index}",
            "player_a_name_snapshot": "Player", "player_b_name_snapshot": f"Opponent {index}",
            "participants": {"A": {"name": "Player"}, "B": {"name": f"Opponent {index}"}},
            "result": {"winner": winner},
        })

    # A different game and Official Team results must not affect this leaderboard.
    store.save_match({
        "id": "ott-result", "game_id": "ott_v2", "status": "completed",
        "player_a_id": "player", "player_b_id": "other",
        "participants": {"A": {"name": "Player"}, "B": {"name": "Other"}},
        "result": {"winner": "A"},
    })
    store.save_match({
        "id": "official-result", "game_id": "robot_battle", "status": "completed",
        "official_request_id": "official-1", "player_a_id": "player", "player_b_id": "team",
        "participants": {"A": {"name": "Player"}, "B": {"name": "Team"}},
        "result": {"winner": "A"},
    })

    player = next(row for row in store.get_standings("robot_battle") if row["player_id"] == "player")
    assert (player["played"], player["wins"], player["draws"], player["losses"]) == (7, 4, 1, 2)
    assert player["win_rate"] == 57.1
    assert player["form"] == ["D", "W", "W", "L", "W"]


def test_draw_only_players_have_zero_win_rate_and_draw_form(tmp_path):
    store = Store(tmp_path, create_registry())
    store.save_match({
        "id": "draw", "game_id": "robot_battle", "status": "completed",
        "finished_at": "2025-01-01T10:00:00+00:00",
        "player_a_id": "a", "player_b_id": "b",
        "participants": {"A": {"name": "A"}, "B": {"name": "B"}},
        "result": {"winner": None},
    })

    standings = store.get_standings()
    assert all(row["played"] == 1 and row["win_rate"] == 0.0 and row["form"] == ["D"]
               for row in standings)
