"""Small JSON store: atomic replacements, one local server process, no database setup."""
import json
import os
import threading
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from backend.engine.registry import GameRegistry


class Store:
    def __init__(self, base_dir: Path, registry: GameRegistry):
        self.registry = registry
        self.data = base_dir / "data"
        self.uploads = base_dir / "uploads"
        self.replays = self.data / "replays"
        for folder in (self.data, self.uploads, self.replays):
            folder.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.bots: dict = self._read(self.data / "bots.json", {})
        self.matches: dict = self._read(self.data / "matches.json", {})
        if not registry.ids():
            raise ValueError("Cần cài ít nhất một game adapter.")
        fallback = registry.ids()[0]
        config = self._read(self.data / "rules.json", {})
        # Migrate v1's single flat rule object without erasing bots/replays.
        saved = config.get("game_rules", {fallback: config})
        self.game_rules = {game_id: registry.get(game_id).validate_rules(saved.get(game_id))
                           for game_id in registry.ids()}
        self.selected_game_id = config.get("selected_game_id", fallback)
        if self.selected_game_id not in registry.ids():
            self.selected_game_id = fallback
        for bot in self.bots.values():
            bot.setdefault("game_id", fallback)
            if bot.get("sample_key") and ":" not in bot["sample_key"]:
                bot["sample_key"] = f"{bot['game_id']}:{bot['sample_key']}"
        # A restarted server must not leave phantom "running" matches.
        for match in self.matches.values():
            match.setdefault("game_id", match.get("game", fallback))
            if match["status"] in ("queued", "running"):
                match["status"] = "interrupted"
                match["result"] = {"winner": None, "reason": "server_restart", "faults": {}}
        self._write(self.data / "matches.json", self.matches)
        self._write(self.data / "bots.json", self.bots)
        self._save_config()

    @staticmethod
    def _read(path: Path, default):
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default

    @staticmethod
    def _write(path: Path, value):
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(temporary, path)

    def get_bots(self) -> list[dict]:
        with self.lock:
            return deepcopy(list(reversed(self.bots.values())))

    def get_bot(self, bot_id: str) -> dict | None:
        with self.lock:
            return deepcopy(self.bots.get(bot_id))

    def save_bot(self, bot: dict):
        with self.lock:
            self.bots[bot["id"]] = deepcopy(bot)
            self._write(self.data / "bots.json", self.bots)

    def _save_config(self):
        self._write(self.data / "rules.json", {"version": 2, "selected_game_id": self.selected_game_id,
                                              "game_rules": self.game_rules})

    def get_rules(self, game_id: str) -> dict:
        with self.lock:
            self.registry.get(game_id)
            return deepcopy(self.game_rules[game_id])

    def set_rules(self, game_id: str, rules: dict):
        with self.lock:
            self.game_rules[game_id] = self.registry.get(game_id).validate_rules(rules)
            self._save_config()
            return deepcopy(self.game_rules[game_id])

    def select_game(self, game_id: str):
        with self.lock:
            self.registry.get(game_id)
            self.selected_game_id = game_id
            self._save_config()

    def get_matches(self) -> list[dict]:
        with self.lock:
            return deepcopy(list(reversed(self.matches.values())))

    def save_match(self, match: dict):
        with self.lock:
            self.matches[match["id"]] = deepcopy(match)
            self._write(self.data / "matches.json", self.matches)

    def get_match(self, match_id: str) -> dict | None:
        with self.lock:
            return deepcopy(self.matches.get(match_id))

    def save_replay(self, match_id: str, frames: list[dict]):
        with self.lock:
            self._write(self.replays / f"{match_id}.json", {"version": 1, "frames": frames})

    def get_replay(self, match_id: str) -> dict | None:
        with self.lock:
            path = self.replays / f"{match_id}.json"
            return self._read(path, None)

    @staticmethod
    def new_id() -> str:
        return uuid4().hex[:16]
