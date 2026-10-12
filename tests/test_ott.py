import json
from copy import deepcopy
from pathlib import Path
import pytest
from pydantic import ValidationError
from backend.engine.ott import OTTAdapter, BEATS, GOALS, OTTRules, TYPES
from backend.engine.base import InvalidAction

ROOT = Path(__file__).resolve().parent.parent
GAME = OTTAdapter()


def initial(**rules):
    return GAME.create_initial_state(GAME.validate_rules(rules))


def move(fr, fc, tr, tc):
    return {"action": "move", "from": {"row": fr, "col": fc}, "to": {"row": tr, "col": tc}}


def test_formation_matches_reference_configuration_exactly():
    reference = json.loads((ROOT / "docs/reference/ottv2/config/rules/standard-9x9.json").read_text(encoding="utf-8"))
    state = initial()
    for player, reference_player in (("A", "P1"), ("B", "P2")):
        assert state["counts"][player] == dict.fromkeys(TYPES, 3)
        assert GOALS[player] == reference["goals"][reference_player]
        for index, piece in enumerate(reference["startingPieces"][reference_player], 1):
            actual = state["board"][piece["row"]][piece["col"]]
            assert actual == {"id": f"{player.lower()}-{piece['type']}-{index}", "owner": player, "type": piece["type"]}
    assert state["board"][0][0] is None and state["board"][8][8] is None
    assert state["current_player"] == "A"


@pytest.mark.parametrize("dr,dc", [(r, c) for r in (-1, 0, 1) for c in (-1, 0, 1) if r or c])
def test_one_cell_all_eight_directions(dr, dc):
    state = initial()
    state["board"][4][4] = {"id": "center", "owner": "A", "type": "rock"}
    assert GAME.validate_action(state, "A", move(4, 4, 4 + dr, 4 + dc))


@pytest.mark.parametrize("kind,prey", list(BEATS.items()))
def test_capture_cycle_and_serialized_capture_event(kind, prey):
    state = initial()
    state["board"][4][4] = {"id": "hunter", "owner": "A", "type": kind}
    state["board"][5][5] = {"id": "prey", "owner": "B", "type": prey}
    updated = GAME.apply_action(state, {"A": move(4, 4, 5, 5)})
    assert updated["board"][4][4] is None
    assert updated["board"][5][5]["id"] == "hunter"
    assert updated["events"][1]["type"] == "capture"
    assert updated["events"][1]["piece"]["type"] == prey
    assert state["board"][5][5]["id"] == "prey"  # Original frame is immutable.


@pytest.mark.parametrize("owner,kind", [("A", "paper"), ("B", "rock"), ("B", "paper")])
def test_friendly_equal_and_stronger_pieces_block(owner, kind):
    state = initial()
    state["board"][4][4] = {"id": "a", "owner": "A", "type": "rock"}
    state["board"][5][5] = {"id": "b", "owner": owner, "type": kind}
    with pytest.raises(InvalidAction):
        GAME.validate_action(state, "A", move(4, 4, 5, 5))


@pytest.mark.parametrize("action", [move(1, 3, 3, 3), move(1, 3, 1, 3), move(1, 3, -1, 3),
                                    move(True, 3, 2, 4), move(1.0, 3, 2, 4),
                                    {"type": "wait"}, {"action": "move", "from": {}, "to": {}}])
def test_invalid_actions(action):
    with pytest.raises(InvalidAction):
        GAME.validate_action(initial(), "A", action)


def test_ownership_turn_and_state_injection_rejected():
    state = initial()
    for player, action in [("B", move(7, 3, 6, 3)), ("A", move(7, 3, 6, 3))]:
        with pytest.raises(InvalidAction):
            GAME.validate_action(state, player, action)
    with pytest.raises(InvalidAction):
        GAME.validate_action(state, "A", {**move(1, 3, 2, 4), "winner": "A"})
    after = GAME.apply_action(state, {"A": move(1, 3, 2, 4)})
    assert GAME.get_players_to_act(after) == ("B",)
    with pytest.raises(InvalidAction):
        GAME.apply_action(after, {"A": move(2, 4, 3, 5)})


@pytest.mark.parametrize("player,source,destination", [("A", (7, 7), (8, 8)), ("B", (1, 1), (0, 0))])
def test_goal_wins_for_both_players(player, source, destination):
    state = initial()
    state["current_player"] = player
    state["board"][source[0]][source[1]] = {"id": "runner", "owner": player, "type": "paper"}
    after = GAME.apply_action(state, {player: move(*source, *destination)})
    assert after["result"]["winner"] == player and after["result"]["reason"] == "goal"


def test_eliminating_one_type_wins_and_goal_has_priority():
    state = initial()
    for row in state["board"]:
        for col, piece in enumerate(row):
            if piece and piece["owner"] == "B" and piece["type"] == "scissors":
                row[col] = None
    state["board"][4][4] = {"id": "a", "owner": "A", "type": "rock"}
    state["board"][5][5] = {"id": "last", "owner": "B", "type": "scissors"}
    after = GAME.apply_action(state, {"A": move(4, 4, 5, 5)})
    assert after["result"]["reason"] == "elimination" and after["result"]["eliminated_type"] == "scissors"
    assert GAME.detect_winner(after, "A", GOALS["A"])["reason"] == "goal"


def test_move_limit_round_count_and_auto_phase_actually_apply():
    state = initial(max_turns=1, rounds=3)
    original = deepcopy(state)
    for round_index in (1, 2, 3):
        state = GAME.apply_action(state, {"A": GAME.legal_actions(state, "A")[0]})
        assert state["round_result"]["reason"] == "turn_limit"
        if round_index < 3:
            assert not GAME.is_game_over(state) and GAME.get_players_to_act(state) == ()
            state = GAME.apply_action(state, {})
            assert state["board"] == original["board"] and state["round"] == round_index + 1
    assert state["turn"] == 5 and state["result"]["winner"] is None
    assert len(state["round_results"]) == 3


def test_round_scores_and_game_result():
    state = initial(rounds=2)
    for index in (1, 2):
        state["board"][7][7] = {"id": "runner", "owner": "A", "type": "paper"}
        state = GAME.apply_action(state, {"A": move(7, 7, 8, 8)})
        if index == 1:
            state = GAME.apply_action(state, {})
    assert state["result"]["winner"] == "A" and state["result"]["scores"] == {"A": 2, "B": 0}


def test_observation_is_detached_and_legal_list_is_valid():
    state = initial()
    observation = GAME.get_observation(state, "A")
    assert observation["game_id"] == "ott_v2" and observation["legal_actions"]
    for action in observation["legal_actions"]:
        GAME.validate_action(state, "A", action)
    observation["board"][0][1]["owner"] = "B"
    assert state["board"][0][1]["owner"] == "A"


@pytest.mark.parametrize("rules", [{"map_size": 5}, {"damage": 20}, {"rounds": 0}, {"rounds": 6}, {"max_turns": 0}, {"max_turns": 1.5}])
def test_only_supported_rule_fields_are_accepted(rules):
    with pytest.raises(ValidationError):
        OTTRules.model_validate(rules)
