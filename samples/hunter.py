"""Python sample. One input JSON line -> one output JSON line, always flush."""
import json
import sys


def choose(state):
    you, enemy = state["you"], state["enemy"]
    dx, dy = enemy["x"] - you["x"], enemy["y"] - you["y"]
    distance = abs(dx) + abs(dy)
    if distance == 1:
        return {"type": "attack"}
    # At distance 2, A lets B approach. Prevent both bots moving into one cell.
    if distance == 2 and state["player"] == "A":
        return {"type": "wait"}
    if dx:
        direction = "right" if dx > 0 else "left"
    else:
        direction = "down" if dy > 0 else "up"
    return {"type": "move", "direction": direction}


for line in sys.stdin:
    state = json.loads(line)
    print(json.dumps(choose(state), separators=(",", ":")), flush=True)
