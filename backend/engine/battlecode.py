"""Official whole-match integration. No approximation of Battlecode game rules."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from .base import GameAdapter, InvalidAction

ENGINE_COMMIT = "103abf6b67a2cf544e6344dddef9318af9ae9193"


class BattlecodeRules(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    map: Literal["DefaultSmall", "DefaultMedium", "DefaultLarge"] = Field(default="DefaultSmall", title="Bản đồ chính thức")


class BattlecodeAdapter(GameAdapter):
    whole_match = True
    rules_model = BattlecodeRules
    metadata = {
        "game_id": "battlecode26", "name": "Battlecode 2026", "version": ENGINE_COMMIT[:12],
        "description": "Engine MIT Battlecode 2026 chính thức. Java 21 và Python 3.12, chạy trong Docker Sandbox.",
        "turn_mode": "official_engine", "renderer": "battlecode26", "badge": "BATTLECODE 2026",
        "source_url": "https://github.com/battlecode/battlecode26/tree/" + ENGINE_COMMIT,
        "fixed_rules": {"engine": "Mã nguồn chính thức đã ghim phiên bản", "languages": "Java 21 · Python 3.12", "protocol": "RobotController / turn(), không dùng JSON stdin"},
        "guide": [
            {"title": "BOT", "description": "Java: package arena, RobotPlayer.run(RobotController). Python: hàm turn() dùng rc."},
            {"title": "MATCH", "description": "Engine chính thức điều khiển toàn bộ đơn vị, bytecode và điều kiện thắng trên bản đồ đã chọn."},
            {"title": "REPLAY", "description": "Xem lại các lượt đã xuất từ replay chính thức hoặc tải file .bc26 để mở trong client Battlecode."}],
        "action_examples": [],
    }
    samples = {
        "python": {"path": "battlecode26/bot.py", "name": "Python / Explorer", "description": "Hàm turn() và di chuyển bằng RobotController."},
        "java": {"path": "battlecode26/RobotPlayer.java", "name": "Java / Explorer", "description": "Java 21 · package arena · RobotPlayer.run()."},
    }

    def create_initial_state(self, rules):
        return {"game_id": "battlecode26", "turn": 0, "rules": self.validate_rules(rules),
                "units": [], "events": [], "result": None, "pending_engine": True}

    def get_observation(self, state, player):
        raise InvalidAction("Battlecode observations are provided by the official engine")

    def validate_action(self, state, player, action):
        raise InvalidAction("Battlecode actions are validated by the official engine")

    def apply_action(self, state, actions):
        raise InvalidAction("Battlecode is executed as one supervised engine job")

    def get_players_to_act(self, state):
        return ()
