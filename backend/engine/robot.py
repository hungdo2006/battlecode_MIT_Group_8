from copy import deepcopy
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from .base import GameAdapter, GameEngine, InvalidAction

DIRECTIONS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}


class RobotRules(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    map_size: int = Field(default=12, ge=5, le=24)
    initial_hp: int = Field(default=100, ge=10, le=1000)
    damage: int = Field(default=20, ge=1, le=500)
    max_turns: int = Field(default=100, ge=1, le=1000)


class RobotBattle(GameEngine):
    def __init__(self, rules: RobotRules):
        self.rules = rules
        n = rules.map_size
        self.robots = {
            "A": {"x": 1, "y": n // 2, "hp": rules.initial_hp},
            "B": {"x": n - 2, "y": n // 2, "hp": rules.initial_hp},
        }
        self.turn = 0
        self.events: list[dict] = []
        self.actions: dict = {}
        self.result: dict | None = None

    @property
    def finished(self) -> bool:
        return self.result is not None

    def snapshot(self) -> dict:
        return deepcopy({"turn": self.turn, "rules": self.rules.model_dump(),
                         "robots": self.robots, "actions": self.actions,
                         "events": self.events, "result": self.result})

    def observation(self, player: str) -> dict:
        enemy = "B" if player == "A" else "A"
        return {"protocol": 1, "game": "robot_battle", "player": player,
                "turn": self.turn, "rules": self.rules.model_dump(),
                "you": deepcopy(self.robots[player]),
                "enemy": deepcopy(self.robots[enemy])}

    def validate_action(self, action: Any) -> dict:
        if not isinstance(action, dict):
            raise InvalidAction("Hành động phải là một JSON object.")
        kind = action.get("type")
        if not isinstance(kind, str) or kind not in ("move", "attack", "wait"):
            raise InvalidAction("type phải là move, attack hoặc wait.")
        allowed = {"type", "direction"} if kind == "move" else {"type"}
        if set(action) != allowed:
            raise InvalidAction("Hành động chứa trường thiếu hoặc không hợp lệ.")
        if kind == "move":
            direction = action.get("direction")
            if not isinstance(direction, str) or direction not in DIRECTIONS:
                raise InvalidAction("direction phải là up, down, left hoặc right.")
        return dict(action)

    def step(self, actions: dict[str, dict]) -> dict:
        if self.finished:
            raise RuntimeError("Trận đấu đã kết thúc.")
        actions = {p: self.validate_action(actions[p]) for p in ("A", "B")}
        self.turn += 1
        self.events = []
        self.actions = actions
        starts = {p: (r["x"], r["y"]) for p, r in self.robots.items()}
        targets = dict(starts)
        for player, action in actions.items():
            if action["type"] == "move":
                dx, dy = DIRECTIONS[action["direction"]]
                x, y = starts[player]
                target = (x + dx, y + dy)
                if all(0 <= coordinate < self.rules.map_size for coordinate in target):
                    targets[player] = target

        # Prevent occupying one cell or passing through each other. Otherwise both move.
        collision = targets["A"] == targets["B"]
        swap = targets["A"] == starts["B"] and targets["B"] == starts["A"]
        if collision or swap:
            targets = starts
        for player, target in targets.items():
            if actions[player]["type"] == "move":
                moved = target != starts[player]
                self.events.append({"type": "move" if moved else "blocked", "player": player,
                                    "from": list(starts[player]), "to": list(target)})
            self.robots[player]["x"], self.robots[player]["y"] = target

        # Damage is accumulated first, so both robots can die on the same turn.
        damage = {"A": 0, "B": 0}
        distance = sum(abs(a - b) for a, b in zip(targets["A"], targets["B"]))
        for player, action in actions.items():
            if action["type"] == "attack":
                enemy = "B" if player == "A" else "A"
                hit = distance == 1
                damage[enemy] += self.rules.damage if hit else 0
                self.events.append({"type": "attack", "player": player, "target": enemy,
                                    "hit": hit, "damage": self.rules.damage if hit else 0})
        for player in damage:
            self.robots[player]["hp"] = max(0, self.robots[player]["hp"] - damage[player])
        dead = [p for p, r in self.robots.items() if r["hp"] == 0]
        if dead:
            winner = None if len(dead) == 2 else ("B" if dead[0] == "A" else "A")
            self.result = {"winner": winner, "reason": "knockout", "faults": {}}
        elif self.turn >= self.rules.max_turns:
            a, b = self.robots["A"]["hp"], self.robots["B"]["hp"]
            self.result = {"winner": None if a == b else ("A" if a > b else "B"),
                           "reason": "turn_limit", "faults": {}}
        return self.snapshot()

    def forfeit(self, faults: dict[str, str]) -> dict:
        if self.finished:
            return self.snapshot()
        self.turn += 1
        self.actions = {}
        self.events = [{"type": "fault", "player": p, "message": msg} for p, msg in faults.items()]
        winner = None if len(faults) == 2 else ("B" if "A" in faults else "A")
        self.result = {"winner": winner, "reason": "bot_error", "faults": faults}
        return self.snapshot()


class RobotBattleAdapter(GameAdapter):
    rules_model = RobotRules
    metadata = {
        "game_id": "robot_battle", "name": "Robot Battle", "version": "1.0",
        "description": "Hai robot hành động đồng thời. Di chuyển, áp sát và tấn công để hạ đối thủ.",
        "turn_mode": "simultaneous", "renderer": "robot_battle", "badge": "ROBOT BATTLE",
        "fixed_rules": {"movement": "1 ô, 4 hướng", "attack_range": "Ô kề, Manhattan = 1"},
        "guide": [
            {"title": "MOVE", "description": "Hai bot nhận cùng trạng thái. Di chuyển một ô theo 4 hướng; va chạm hoặc ra biên thì đứng yên."},
            {"title": "ATTACK", "description": "Tấn công sau di chuyển. Sát thương hai bot tính đồng thời khi ở ô kề."},
            {"title": "WIN", "description": "Đối thủ hết HP: thắng. Hết lượt: so HP. HP bằng nhau hoặc cùng bị hạ: hòa."}],
        "action_examples": [{"type": "move", "direction": "right"}, {"type": "attack"}, {"type": "wait"}],
    }
    samples = {
        "python": {"path": "hunter.py", "name": "PY / HUNTER", "description": "Áp sát và tấn công liên tục."},
        "cpp": {"path": "hunter.cpp", "name": "C++ / SENTINEL", "description": "Áp sát, nghỉ một lượt trong bốn."},
        "java": {"path": "Main.java", "name": "JAVA / PHANTOM", "description": "Áp sát, nghỉ một lượt trong năm."},
    }

    def get_rules_schema(self):
        schema = super().get_rules_schema()
        labels = {"map_size": "Kích thước bản đồ", "initial_hp": "HP ban đầu",
                  "damage": "Sát thương mỗi đòn", "max_turns": "Số lượt tối đa"}
        for key, title in labels.items():
            schema["properties"][key]["title"] = title
        return schema

    @staticmethod
    def _restore(state):
        engine = RobotBattle(RobotRules.model_validate(state["rules"]))
        for key in ("robots", "turn", "events", "actions", "result"):
            setattr(engine, key, deepcopy(state[key]))
        return engine

    def create_initial_state(self, rules):
        return {"game_id": self.metadata["game_id"], **RobotBattle(RobotRules.model_validate(rules)).snapshot()}

    def get_observation(self, state, player):
        return {**self._restore(state).observation(player), "game_id": self.metadata["game_id"]}

    def validate_action(self, state, player, action):
        if player not in self.get_players_to_act(state):
            raise InvalidAction("Không phải lượt của bot hoặc trận đã kết thúc.")
        return self._restore(state).validate_action(action)

    def get_players_to_act(self, state):
        return () if self.is_game_over(state) else ("A", "B")

    def apply_action(self, state, actions):
        if set(actions) != {"A", "B"}:
            raise InvalidAction("Robot Battle cần hành động của cả A và B.")
        return {"game_id": self.metadata["game_id"], **self._restore(state).step(actions)}
