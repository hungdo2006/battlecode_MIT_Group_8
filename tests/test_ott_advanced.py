"""Variant isolation, sliding geometry and 9x9 backward compatibility."""
import pytest
from pydantic import ValidationError

from backend.engine import create_registry
from backend.engine.base import InvalidAction
from backend.engine.ott_advanced import OTTAdvancedAdapter
from backend.engine.ott import OTTAdapter


ADV = OTTAdvancedAdapter()


def move(fr, fc, tr, tc):
    return {"action":"move","from":{"row":fr,"col":fc},"to":{"row":tr,"col":tc}}


def test_both_games_registered_and_original_rules_untouched():
    registry = create_registry()
    assert "ott_v2" in registry.ids()
    assert "ott_advanced" in registry.ids()
    assert OTTAdapter().validate_rules() == {"max_turns":100,"rounds":1}
    with pytest.raises(ValidationError):
        OTTAdapter().validate_rules({"board_size":11})


@pytest.mark.parametrize("size", [7,9,11])
def test_board_size_dynamic_goals_and_counts(size):
    state = ADV.create_initial_state(ADV.validate_rules({"board_size":size,"max_move_distance":2}))
    assert len(state["board"]) == size
    assert all(len(row)==size for row in state["board"])
    assert state["goals"] == {"A":{"row":size-1,"col":size-1},"B":{"row":0,"col":0}}
    assert all(state["counts"][team] == {"rock":3,"paper":3,"scissors":3} for team in ("A","B"))
    observation = ADV.get_observation(state,"A")
    assert observation["board_size"] == size and observation["goals"] == state["goals"]
    assert observation["game_id"] == "ott_advanced"
    for action in observation["legal_actions"]:
        assert ADV.validate_action(state, "A", action)


def test_multiple_cells_require_clear_path_and_bounded_distance():
    state = ADV.create_initial_state(ADV.validate_rules({"max_move_distance":3}))
    state["board"][4][4]={"id":"probe","owner":"A","type":"rock"}
    assert ADV.validate_action(state,"A",move(4,4,4,7))
    assert ADV.validate_action(state,"A",move(4,4,6,6))
    for bad in (move(4,4,4,8),move(4,4,6,7),move(4,4,4,4)):
        with pytest.raises(InvalidAction):
            ADV.validate_action(state,"A",bad)
    state["board"][4][5]={"id":"stop","owner":"B","type":"scissors"}
    with pytest.raises(InvalidAction):
        ADV.validate_action(state,"A",move(4,4,4,7))
    assert ADV.validate_action(state,"A",move(4,4,4,5))


def test_turn_limit_and_round_reset_use_advanced_size_and_goals():
    state = ADV.create_initial_state(ADV.validate_rules({
        "board_size":7,"max_move_distance":3,"max_turns":1,"rounds":2}))
    initial_board = state["board"]
    one = ADV.apply_action(state, {"A": ADV.legal_actions(state,"A")[0]})
    assert one["pending_round"] and one["round_result"]["reason"]=="turn_limit"
    two = ADV.apply_action(one, {})
    assert two["round"] == 2 and two["board"] == initial_board
    assert len(two["board"]) == 7
    assert two["goals"]["A"] == {"row":6,"col":6}


def test_goal_detection_on_nonstandard_size():
    state = ADV.create_initial_state(ADV.validate_rules({"board_size":11}))
    state["board"][10][9] = {"id":"runner","owner":"A","type":"paper"}
    result = ADV.apply_action(state, {"A":move(10,9,10,10)})
    assert result["result"]["winner"] == "A"
    assert result["result"]["reason"] == "goal"


@pytest.mark.parametrize("rules", [
    {"board_size":8}, {"board_size":12}, {"max_move_distance":0},
    {"max_move_distance":4}, {"max_move_distance":True}, {"unknown":"field"}])
def test_rejects_unknown_and_out_of_bounds_rules(rules):
    with pytest.raises(ValidationError):
        ADV.validate_rules(rules)
