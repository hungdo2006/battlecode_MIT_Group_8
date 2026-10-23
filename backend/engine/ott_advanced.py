"""Configurable OTT variant. Original ott_v2 remains byte-compatible with 9x9 rules.

A move slides 1..3 cells horizontally, vertically or diagonally without
jumping pieces. Captures happen only at the destination. Each replay stores
its rules and dynamic board, so changing the next round does not rewrite it.
"""
from copy import deepcopy
from typing import Literal

from pydantic import Field

from .base import InvalidAction
from .ott import OTTAdapter, OTTRules, TYPES, BEATS


class OTTAdvancedRules(OTTRules):
    board_size: Literal[7, 9, 11] = Field(
        default=9, title="Kích thước bàn cờ",
        description="Bàn vuông 7x7, 9x9 hoặc 11x11.")
    max_move_distance: int = Field(
        default=1, ge=1, le=3, title="Số ô tối đa mỗi nước",
        description="Đi thẳng hoặc chéo, không nhảy qua quân; ăn ở ô cuối.")


class OTTAdvancedAdapter(OTTAdapter):
    rules_model = OTTAdvancedRules
    metadata = {
        **OTTAdapter.metadata,
        "game_id": "ott_advanced",
        "name": "OTT Advanced",
        "version": "1.0",
        "renderer": "ott_advanced",
        "badge": "OTT ADVANCED",
        "description": "Biến thể OTT tùy chỉnh bàn 7/9/11 và quãng đi 1–3 ô, không nhảy quân.",
        "fixed_rules": {
            "pieces": "9 quân/bên (3 mỗi loại)", "captures": "Búa > Kéo > Bao > Búa",
            "movement": "8 hướng, tối đa 1–3 ô, không xuyên quân",
            "goals": "Hai góc đối diện theo kích thước bàn",
        },
        "guide": [
            {"title": "SETUP", "description": "Bàn 7x7, 9x9 hoặc 11x11; mỗi bên 9 quân."},
            {"title": "MOVE", "description": "Đi thẳng hoặc chéo tối đa số ô được cấu hình; không nhảy qua quân."},
            {"title": "CAPTURE", "description": "Chỉ ăn quân ở ô đích theo Búa-Kéo-Bao."},
            {"title": "WIN", "description": "Đến góc đích hoặc loại hết một loại quân đối thủ; hết lượt thì hòa."},
        ],
    }
    # Original samples consume legal_actions from the observation and remain
    # compatible with the extended protocol.
    # Python example reads dynamic legal_actions/goals. The OTT v2 C++/Java
    # samples assume 0..8 coordinates and must not be advertised here.
    samples = {"python": OTTAdapter.samples["python"]}

    @staticmethod
    def advanced_board(size):
        board = [[None for _ in range(size)] for _ in range(size)]
        if size == 9:
            from .ott import FORMATION
            formations = FORMATION
        else:
            # Three of each kind, mirrored and disjoint from the goal cells.
            positions = ([(0, col) for col in range(1, 6)]
                         + [(1, col) for col in range(1, 5)])
            kinds = [TYPES[i % len(TYPES)] for i in range(9)]
            formations = {
                "A": [(r, c, kinds[i]) for i, (r, c) in enumerate(positions)],
                "B": [(size - 1 - r, size - 1 - c, kinds[i])
                      for i, (r, c) in enumerate(positions)],
            }
        for owner, pieces in formations.items():
            for index, (row, col, kind) in enumerate(pieces, 1):
                board[row][col] = {"id": f"{owner.lower()}-{kind}-{index}",
                                   "owner": owner, "type": kind}
        return board

    def initial_board_from_rules(self, rules):
        return self.advanced_board(rules["board_size"])

    def create_initial_state(self, rules):
        validated = self.validate_rules(rules)
        state = super().create_initial_state(validated)
        size = validated["board_size"]
        state["board_size"] = size
        state["board"] = self.initial_board_from_rules(validated)
        state["goals"] = {"A": {"row": size - 1, "col": size - 1},
                          "B": {"row": 0, "col": 0}}
        return self.serialize_state(state)

    def validate_action(self, state, player, action):
        if player not in self.get_players_to_act(state):
            raise InvalidAction("Không phải lượt của bot.")
        if (not isinstance(action, dict) or set(action) != {"action", "from", "to"}
                or action["action"] != "move"):
            raise InvalidAction("Cần action=move với from và to.")
        size = state["board_size"]
        for key in ("from", "to"):
            p = action[key]
            if (not isinstance(p, dict) or set(p) != {"row", "col"}
                    or any(type(p[c]) is not int or not 0 <= p[c] < size
                           for c in ("row", "col"))):
                raise InvalidAction("Tọa độ phải là số nguyên trong bàn cờ.")
        source, dest = action["from"], action["to"]
        dr, dc = dest["row"] - source["row"], dest["col"] - source["col"]
        distance = max(abs(dr), abs(dc))
        if (not 1 <= distance <= state["rules"]["max_move_distance"]
                or not (dr == 0 or dc == 0 or abs(dr) == abs(dc))):
            raise InvalidAction("Chỉ đi thẳng/chéo trong quãng đường cho phép.")
        board = state["board"]
        piece = board[source["row"]][source["col"]]
        if not piece or piece["owner"] != player:
            raise InvalidAction("Chỉ di chuyển quân của mình.")
        step_r = (dr > 0) - (dr < 0)
        step_c = (dc > 0) - (dc < 0)
        for offset in range(1, distance):
            if board[source["row"] + offset * step_r][source["col"] + offset * step_c]:
                raise InvalidAction("Không được nhảy qua quân khác.")
        target = board[dest["row"]][dest["col"]]
        if target and (target["owner"] == player or BEATS[piece["type"]] != target["type"]):
            raise InvalidAction("Ô đích bị chặn hoặc không thể ăn quân.")
        return deepcopy(action)

    def legal_actions(self, state, player):
        if player not in self.get_players_to_act(state):
            return []
        actions = []
        n = state["board_size"]
        distance = state["rules"]["max_move_distance"]
        for r, row in enumerate(state["board"]):
            for c, piece in enumerate(row):
                if not piece or piece["owner"] != player:
                    continue
                for sr, sc in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
                    for step in range(1, distance + 1):
                        rr, cc = r + step*sr, c + step*sc
                        if not (0 <= rr < n and 0 <= cc < n):
                            break
                        action = {"action": "move", "from": {"row": r,"col": c},
                                  "to": {"row": rr,"col": cc}}
                        try:
                            actions.append(self.validate_action(state, player, action))
                        except InvalidAction:
                            # Once an intermediate cell blocks a ray, no further
                            # destination in this direction can be reachable.
                            if state["board"][rr][cc]:
                                break
        return actions

    def get_observation(self, state, player):
        result = super().get_observation(state, player)
        result["board_size"] = state["board_size"]
        result["goals"] = deepcopy(state["goals"])
        return result

    @staticmethod
    def detect_winner(state, player, destination):
        if destination == state["goals"][player]:
            return {"winner": player, "reason": "goal", "goal": deepcopy(destination)}
        enemy = "B" if player == "A" else "A"
        counts = OTTAdvancedAdapter.count_pieces(state)[enemy]
        eliminated = next((kind for kind in TYPES if counts[kind] == 0), None)
        return ({"winner": player, "reason": "elimination", "eliminated_type": eliminated}
                if eliminated else None)
