import json
import random
import shutil
import subprocess
from pathlib import Path
import pytest
from backend.engine.ott import OTTAdapter
from backend.engine.base import InvalidAction


def test_python_moves_and_results_match_original_javascript():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node only needed for source-rule differential test")
    game = OTTAdapter()
    rng = random.Random(1012)
    cases, expected = [], []
    for _ in range(4):
        state = game.create_initial_state(game.validate_rules({"max_turns": 500}))
        for _ in range(40):
            player = state["current_player"]
            legal = game.legal_actions(state, player)
            if not legal or game.is_game_over(state):
                break
            for action in [rng.choice(legal), {"action": "move", "from": {"row": 0, "col": 0}, "to": {"row": 2, "col": 2}}]:
                cases.append({"state": state, "player": player, "action": action})
                try:
                    game.validate_action(state, player, action)
                    next_state = game.apply_action(state, {player: action})
                    expected.append({"ok": True, "winner": next_state["result"]["winner"] if next_state["result"] else None,
                                     "board": next_state["board"]})
                except InvalidAction:
                    expected.append({"ok": False})
            state = game.apply_action(state, {player: rng.choice(legal)})
    root = Path(__file__).resolve().parent.parent
    result = subprocess.run([node, str(root / "tests/reference_ott.mjs")], input=json.dumps(cases),
                            text=True, capture_output=True, timeout=15, check=True)
    assert len(cases) > 50
    assert json.loads(result.stdout) == expected
