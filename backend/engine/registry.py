import re
from backend.engine.base import GameAdapter


class GameRegistry:
    """Installed adapters only: register an object, then expose its metadata/schema."""
    def __init__(self):
        self._adapters: dict[str, GameAdapter] = {}

    def register(self, adapter: GameAdapter):
        game_id = adapter.get_metadata()["game_id"]
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,47}", game_id):
            raise ValueError("Game ID không hợp lệ.")
        if game_id in self._adapters:
            raise ValueError(f"Game ID đã được đăng ký: {game_id}")
        self._adapters[game_id] = adapter
        return adapter

    def get(self, game_id: str) -> GameAdapter:
        if game_id not in self._adapters:
            raise ValueError(f"Game chưa được cài đặt: {game_id}")
        return self._adapters[game_id]

    def ids(self) -> tuple[str, ...]:
        return tuple(self._adapters)

    def describe(self, game_id: str) -> dict:
        adapter = self.get(game_id)
        return {**adapter.get_metadata(), "rules_schema": adapter.get_rules_schema(),
                "default_rules": adapter.validate_rules(),
                "samples": [{"language": language, "name": sample["name"],
                             "description": sample["description"]} for language, sample in adapter.samples.items()]}

    def list_games(self) -> list[dict]:
        return [self.describe(game_id) for game_id in self.ids()]
