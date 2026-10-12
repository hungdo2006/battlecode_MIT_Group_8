import pytest
from pydantic import ValidationError

from backend.engine.base import InvalidAction
from backend.engine.robot import RobotBattle
from backend.engine.robot import RobotRules as Rules

WAIT = {"type": "wait"}
ATTACK = {"type": "attack"}


def move(direction):
    return {"type": "move", "direction": direction}


def adjacent(game):
    game.robots["A"].update(x=1, y=2)
    game.robots["B"].update(x=2, y=2)


def test_custom_map_hp_and_observation_are_independent():
    game = RobotBattle(Rules(map_size=8, initial_hp=250, damage=17, max_turns=9))
    state = game.observation("B")
    assert state["you"] == {"x": 6, "y": 4, "hp": 250}
    state["you"]["hp"] = 0
    assert game.robots["B"]["hp"] == 250


def test_both_move_and_boundary_is_blocked():
    game = RobotBattle(Rules(map_size=8))
    frame = game.step({"A": move("right"), "B": move("left")})
    assert (frame["robots"]["A"]["x"], frame["robots"]["B"]["x"]) == (2, 5)
    game.robots["A"]["x"] = 0
    frame = game.step({"A": move("left"), "B": WAIT})
    assert frame["robots"]["A"]["x"] == 0
    assert frame["events"][0]["type"] == "blocked"


def test_collision_and_swap_are_blocked():
    game = RobotBattle(Rules(map_size=5))
    frame = game.step({"A": move("right"), "B": move("left")})
    assert [frame["robots"][p]["x"] for p in ("A", "B")] == [1, 3]
    adjacent(game)
    frame = game.step({"A": move("right"), "B": move("left")})
    assert [frame["robots"][p]["x"] for p in ("A", "B")] == [1, 2]


def test_attack_uses_position_after_movement_and_custom_damage():
    game = RobotBattle(Rules(map_size=5, initial_hp=80, damage=31))
    frame = game.step({"A": ATTACK, "B": move("left")})
    assert frame["robots"]["B"]["hp"] == 49
    assert frame["robots"]["A"]["hp"] == 80


def test_distant_attack_misses():
    game = RobotBattle(Rules())
    frame = game.step({"A": ATTACK, "B": WAIT})
    assert frame["robots"]["B"]["hp"] == 100
    assert frame["events"][0]["hit"] is False


def test_simultaneous_knockout_is_draw():
    game = RobotBattle(Rules(initial_hp=20, damage=20))
    adjacent(game)
    frame = game.step({"A": ATTACK, "B": ATTACK})
    assert frame["result"] == {"winner": None, "reason": "knockout", "faults": {}}
    assert game.finished


def test_single_knockout_and_hp_never_negative():
    game = RobotBattle(Rules(initial_hp=10, damage=40))
    adjacent(game)
    frame = game.step({"A": ATTACK, "B": WAIT})
    assert frame["result"]["winner"] == "A"
    assert frame["robots"]["B"]["hp"] == 0
    with pytest.raises(RuntimeError):
        game.step({"A": WAIT, "B": WAIT})


def test_turn_limit_compares_hp_and_can_draw():
    game = RobotBattle(Rules(max_turns=1))
    assert game.step({"A": WAIT, "B": WAIT})["result"]["winner"] is None
    game = RobotBattle(Rules(max_turns=1))
    adjacent(game)
    result = game.step({"A": ATTACK, "B": WAIT})["result"]
    assert result["winner"] == "A" and result["reason"] == "turn_limit"


@pytest.mark.parametrize("action", [None, [], "attack", {"type": "teleport"}, {"type": []},
                                    {"type": "move"}, {"type": "move", "direction": []},
                                    {"type": "move", "direction": "diagonal"},
                                    {"type": "attack", "direction": "up"}])
def test_invalid_actions(action):
    with pytest.raises(InvalidAction):
        RobotBattle(Rules()).validate_action(action)


def test_fault_forfeit_and_double_fault_draw():
    game = RobotBattle(Rules())
    assert game.forfeit({"B": "timeout"})["result"]["winner"] == "A"
    game = RobotBattle(Rules())
    assert game.forfeit({"A": "crash", "B": "crash"})["result"]["winner"] is None


@pytest.mark.parametrize("rule", [{"map_size": 4}, {"initial_hp": 0}, {"damage": -1}, {"max_turns": 1001}, {"damage": 1.5}])
def test_invalid_rules(rule):
    with pytest.raises(ValidationError):
        Rules(**rule)
