"""OTT v2 bot: choose from server-generated legal_actions, flush one JSON line.

The full board is also available for stronger strategies. Modifying this local
observation never changes server state; every returned move is validated again.
"""
import json
import sys


def choose(state):
    goal = state["goals"][state["player"]]
    board = state["board"]

    def score(action):
        target = action["to"]
        dr, dc = abs(goal["row"] - target["row"]), abs(goal["col"] - target["col"])
        capture = board[target["row"]][target["col"]] is not None
        return (max(dr, dc), dr + dc, not capture, dc)

    return min(state["legal_actions"], key=score)


for line in sys.stdin:
    print(json.dumps(choose(json.loads(line)), separators=(",", ":")), flush=True)
