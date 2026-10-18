from backend.tournament_draws import tournament_standings


def make_tournament(player_ids, fixtures):
    participants = [{"player_id": player_id, "nickname": player_id} for player_id in player_ids]
    matches = []
    for index, (a, b, winner, score_a, score_b) in enumerate(fixtures):
        matches.append({
            "id": f"fixture-{index}", "bracket": "round_robin", "status": "completed",
            "match_id": f"game-{index}",
            "player_a": {"player_id": a, "nickname": a},
            "player_b": {"player_id": b, "nickname": b},
            "winner_id": winner,
            "result": {"scores": {"A": score_a, "B": score_b}},
        })
    return {"participants": participants, "rounds": [{"matches": matches}]}


def test_total_points_precede_head_to_head_result():
    tournament = make_tournament(
        ["A", "B", "C", "D"],
        [
            ("A", "B", "B", 0, 100), ("A", "C", "A", 1, 0),
            ("A", "D", "A", 1, 0), ("B", "C", "C", 0, 1),
            ("B", "D", "D", 0, 1), ("C", "D", None, 0, 0),
        ],
    )

    standings = tournament_standings(tournament)
    assert standings[0]["player_id"] == "A"
    assert standings[0]["points"] == 6
    assert standings[1]["player_id"] == "C"
    assert standings[0]["score_difference"] < standings[1]["score_difference"]


def test_head_to_head_precedes_better_overall_score_difference():
    tournament = make_tournament(
        ["A", "B", "C", "D"],
        [
            ("A", "B", "A", 1, 0), ("A", "C", "C", 0, 10),
            ("A", "D", "A", 10, 0), ("B", "C", "B", 10, 0),
            ("B", "D", "B", 10, 0), ("C", "D", None, 0, 0),
        ],
    )

    standings = tournament_standings(tournament)
    assert [row["player_id"] for row in standings] == ["A", "B", "C", "D"]
    assert standings[0]["score_difference"] < standings[1]["score_difference"]


def test_score_difference_resolves_equal_points_and_head_to_head_mini_table():
    tournament = make_tournament(
        ["A", "B", "C", "D"],
        [
            ("A", "B", "A", 1, 0), ("B", "C", "B", 5, 0),
            ("C", "A", "C", 10, 0), ("A", "D", "A", 1, 0),
            ("B", "D", "B", 1, 0), ("C", "D", "C", 1, 0),
        ],
    )

    standings = tournament_standings(tournament)
    assert [row["player_id"] for row in standings] == ["C", "B", "A", "D"]
    assert standings[0]["head_to_head"] == standings[1]["head_to_head"] == standings[2]["head_to_head"]


def test_number_of_wins_breaks_ties_after_points_head_to_head_and_difference():
    tournament = make_tournament(
        ["A", "B", "C", "D", "E", "F"],
        [
            ("A", "B", None, 0, 0), ("A", "C", "A", 1, 0),
            ("A", "D", None, 0, 0), ("A", "E", None, 0, 0),
            ("A", "F", None, 0, 0), ("B", "C", "B", 3, 0),
            ("B", "D", "B", 3, 0), ("B", "E", "E", 0, 3),
            ("B", "F", "F", 0, 2),
        ],
    )

    standings = tournament_standings(tournament)
    by_id = {row["player_id"]: row for row in standings}
    assert by_id["A"]["points"] == by_id["B"]["points"] == 7
    assert by_id["A"]["head_to_head"] == by_id["B"]["head_to_head"] == 1
    assert by_id["A"]["score_difference"] == by_id["B"]["score_difference"] == 1
    assert by_id["B"]["rank"] < by_id["A"]["rank"]
