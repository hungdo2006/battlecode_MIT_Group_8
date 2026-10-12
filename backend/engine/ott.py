"""OTT v2 standard 9x9 port; MIT source retained in docs/reference/ottv2.

Original formation, 8-direction moves, RPS captures and both win conditions.
Tournament extensions: bounded rounds/moves and draws on limit/stalemate.
"""
from copy import deepcopy
from typing import Any
from pydantic import BaseModel, ConfigDict, Field
from backend.engine.base import GameAdapter, InvalidAction

BOARD_SIZE = 9
TYPES = ("rock", "paper", "scissors")
BEATS = {"rock": "scissors", "scissors": "paper", "paper": "rock"}
GOALS = {"A": {"row": 8, "col": 8}, "B": {"row": 0, "col": 0}}
FORMATION = {
    "A": [(0, 1, "rock"), (0, 2, "paper"), (0, 3, "scissors"), (0, 4, "rock"),
          (0, 5, "paper"), (0, 6, "scissors"), (0, 7, "rock"), (1, 3, "paper"), (1, 5, "scissors")],
    "B": [(8, 1, "scissors"), (8, 2, "paper"), (8, 3, "rock"), (8, 4, "scissors"),
          (8, 5, "paper"), (8, 6, "rock"), (8, 7, "scissors"), (7, 3, "paper"), (7, 5, "rock")],
}


class OTTRules(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    max_turns: int = Field(default=100, ge=1, le=500, title="Nước đi tối đa mỗi ván",
                         description="Một nước của A hoặc B tính là một lượt. Chạm giới hạn: ván hòa.")
    rounds: int = Field(default=1, ge=1, le=5, title="Số ván mỗi trận",
                        description="Chơi đủ số ván. Thắng: 1 điểm, hòa: 0. Điểm bằng nhau: hòa trận.")


class OTTAdapter(GameAdapter):
    rules_model = OTTRules
    metadata = {
        "game_id": "ott_v2", "name": "OTT v2", "version": "2.0-standard-9x9",
        "description": "Cờ Búa–Kéo–Bao: bàn 9×9, hai bot đi luân phiên; chiếm góc đích hoặc loại hết một loại quân đối thủ.",
        "turn_mode": "alternating", "renderer": "ott_v2", "badge": "OTT v2 / 9×9",
        "source_url": "https://github.com/hungdo2006/ottv2-playhtml",
        "fixed_rules": {"board_size": "9 × 9", "pieces": "9 quân/bên, 3 mỗi loại",
                        "movement": "1 ô, 8 hướng", "captures": "Búa > Kéo > Bao > Búa",
                        "goals": "A / P1 → i9; B / P2 → a1", "first_player": "A / P1"},
        "guide": [
            {"title": "MOVE", "description": "Chỉ bot đến lượt được đi. Một quân đi một ô theo 8 hướng. Tọa độ từ 0; row 0 là hàng dưới cùng."},
            {"title": "CAPTURE", "description": "Búa ăn Kéo, Kéo ăn Bao, Bao ăn Búa. Quân cùng đội hoặc cùng loại cản nhau; quân yếu không được bước vào quân mạnh."},
            {"title": "WIN", "description": "A đến i9, B đến a1; hoặc ăn hết một loại quân đối thủ. Xét góc đích trước, rồi loại quân."},
            {"title": "TOURNAMENT", "description": "Hết giới hạn nước hoặc không còn nước hợp lệ: hòa ván. Chơi đủ số ván, cộng điểm thắng và so điểm."}],
        "action_examples": [{"action": "move", "from": {"row": 1, "col": 3}, "to": {"row": 2, "col": 4}}],
    }
    samples = {
        "python": {"path": "ott_v2/runner.py", "name": "PY / OTT RUNNER", "description": "Chọn nước hợp lệ tiến gần góc đích nhất."},
        "cpp": {"path": "ott_v2/runner.cpp", "name": "C++ / OTT RUNNER", "description": "Đi về góc đích, ưu tiên cột khi bằng khoảng cách."},
        "java": {"path": "ott_v2/Main.java", "name": "JAVA / OTT RUNNER", "description": "Đi về góc đích, ưu tiên hàng khi bằng khoảng cách."},
    }

    @staticmethod
    def initial_board():
        board = [[None for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
        for owner, formation in FORMATION.items():
            for index, (row, col, kind) in enumerate(formation, 1):
                board[row][col] = {"id": f"{owner.lower()}-{kind}-{index}", "owner": owner, "type": kind}
        return board

    @staticmethod
    def count_pieces(state):
        counts = {p: dict.fromkeys(TYPES, 0) for p in ("A", "B")}
        for row in state["board"]:
            for piece in row:
                if piece:
                    counts[piece["owner"]][piece["type"]] += 1
        return counts

    def serialize_state(self, state):
        snapshot = deepcopy(state)
        snapshot["counts"] = self.count_pieces(snapshot)
        return snapshot

    def create_initial_state(self, rules):
        return self.serialize_state({
            "game_id": self.metadata["game_id"], "turn": 0, "rules": self.validate_rules(rules),
            "board_size": BOARD_SIZE, "board": self.initial_board(), "goals": deepcopy(GOALS),
            "current_player": "A", "round": 1, "round_turn": 0, "scores": {"A": 0, "B": 0},
            "round_results": [], "round_result": None, "pending_round": False,
            "last_move": None, "actions": {}, "events": [], "result": None,
        })

    def get_players_to_act(self, state):
        return () if self.is_game_over(state) or state["pending_round"] else (state["current_player"],)

    def validate_action(self, state: dict, player: str, action: Any):
        if player not in self.get_players_to_act(state):
            raise InvalidAction("Không phải lượt của bot hoặc ván đã kết thúc.")
        if not isinstance(action, dict) or set(action) != {"action", "from", "to"} or action["action"] != "move":
            raise InvalidAction("OTT v2 cần action=move với from/to; không được gửi board, winner hoặc trường khác.")
        for key in ("from", "to"):
            position = action[key]
            if (not isinstance(position, dict) or set(position) != {"row", "col"}
                    or any(type(position[c]) is not int or not 0 <= position[c] < BOARD_SIZE for c in ("row", "col"))):
                raise InvalidAction("row/col phải là số nguyên từ 0 đến 8.")
        source, destination = action["from"], action["to"]
        dr, dc = abs(source["row"] - destination["row"]), abs(source["col"] - destination["col"])
        if max(dr, dc) != 1:
            raise InvalidAction("Chỉ di chuyển một ô theo 8 hướng, không đứng yên hoặc nhảy ô.")
        piece = state["board"][source["row"]][source["col"]]
        target = state["board"][destination["row"]][destination["col"]]
        if not piece or piece["owner"] != player:
            raise InvalidAction("Phải chọn quân của chính bot.")
        if target:
            if target["owner"] == player:
                raise InvalidAction("Quân cùng đội cản ô đích.")
            if target["type"] == piece["type"]:
                raise InvalidAction("Hai quân cùng loại không được ăn nhau.")
            if BEATS[piece["type"]] != target["type"]:
                raise InvalidAction("Quân yếu không được ăn quân mạnh trong vòng Búa–Kéo–Bao.")
        return deepcopy(action)

    def legal_actions(self, state, player):
        if player not in self.get_players_to_act(state):
            return []
        actions = []
        for row in range(BOARD_SIZE):
            for col in range(BOARD_SIZE):
                piece = state["board"][row][col]
                if not piece or piece["owner"] != player:
                    continue
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        if not dr and not dc:
                            continue
                        action = {"action": "move", "from": {"row": row, "col": col},
                                  "to": {"row": row + dr, "col": col + dc}}
                        try:
                            self.validate_action(state, player, action)
                            actions.append(action)
                        except InvalidAction:
                            pass
        return actions

    def get_observation(self, state, player):
        return {"protocol": 1, "game_id": self.metadata["game_id"], "game": self.metadata["game_id"],
                "player": player, "turn": state["turn"], "round": state["round"],
                "round_turn": state["round_turn"], "current_player": state["current_player"],
                "rules": deepcopy(state["rules"]), "board_size": BOARD_SIZE,
                "board": deepcopy(state["board"]), "goals": deepcopy(GOALS),
                "counts": self.count_pieces(state), "scores": deepcopy(state["scores"]),
                "last_move": deepcopy(state["last_move"]), "legal_actions": self.legal_actions(state, player)}

    @staticmethod
    def detect_winner(state, player, destination):
        if destination == GOALS[player]:
            return {"winner": player, "reason": "goal", "goal": deepcopy(destination)}
        enemy = "B" if player == "A" else "A"
        counts = OTTAdapter.count_pieces(state)[enemy]
        eliminated = next((kind for kind in TYPES if counts[kind] == 0), None)
        return {"winner": player, "reason": "elimination", "eliminated_type": eliminated} if eliminated else None

    def _finish_round(self, state, result):
        state["round_result"] = {**result, "round": state["round"], "moves": state["round_turn"]}
        state["round_results"].append(deepcopy(state["round_result"]))
        if result["winner"]:
            state["scores"][result["winner"]] += 1
        state["events"].append({"type": "round_end", **deepcopy(state["round_result"])})
        if state["round"] < state["rules"]["rounds"]:
            state["pending_round"] = True
            return
        a, b = state["scores"]["A"], state["scores"]["B"]
        state["result"] = {**(result if state["rules"]["rounds"] == 1 else {"reason": "series_complete"}),
                           "winner": None if a == b else ("A" if a > b else "B"),
                           "scores": deepcopy(state["scores"]), "faults": {}}

    def apply_action(self, state, actions):
        if self.is_game_over(state):
            raise InvalidAction("Trận đã kết thúc.")
        next_state = self.serialize_state(state)
        next_state["turn"] += 1
        next_state["events"] = []
        if state["pending_round"]:
            if actions:
                raise InvalidAction("Chuyển ván không nhận hành động bot.")
            next_state.update(board=self.initial_board(), current_player="A", round=state["round"] + 1,
                              round_turn=0, pending_round=False, last_move=None, round_result=None, actions={})
            next_state["events"] = [{"type": "round_start", "round": next_state["round"]}]
            return self.serialize_state(next_state)
        player = state["current_player"]
        if set(actions) != {player}:
            raise InvalidAction("Chỉ nhận hành động của bot đến lượt.")
        action = self.validate_action(state, player, actions[player])
        source, destination = action["from"], action["to"]
        piece = deepcopy(state["board"][source["row"]][source["col"]])
        captured = deepcopy(state["board"][destination["row"]][destination["col"]])
        next_state["board"][source["row"]][source["col"]] = None
        next_state["board"][destination["row"]][destination["col"]] = piece
        next_state["round_turn"] += 1
        next_state["actions"] = {player: action}
        move = {"player": player, "from": source, "to": destination, "piece_type": piece["type"],
                "piece_id": piece["id"], "captured": captured}
        next_state["last_move"] = deepcopy(move)
        next_state["events"] = [{"type": "board_move", **deepcopy(move)}]
        if captured:
            next_state["events"].append({"type": "capture", "player": player, "at": destination,
                                         "piece": captured, "by_type": piece["type"]})
        # Standard order: goal before elimination; a win on the final allowed
        # move precedes the tournament draw rule.
        result = self.detect_winner(next_state, player, destination)
        next_state["current_player"] = "B" if player == "A" else "A"
        if result:
            self._finish_round(next_state, result)
        elif next_state["round_turn"] >= next_state["rules"]["max_turns"]:
            self._finish_round(next_state, {"winner": None, "reason": "turn_limit"})
        elif not self.legal_actions(next_state, next_state["current_player"]):
            self._finish_round(next_state, {"winner": None, "reason": "stalemate"})
        return self.serialize_state(next_state)
