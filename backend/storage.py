"""Small JSON store: atomic replacements, one local server process, no database setup."""
import json
import os
import threading
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from backend.engine.registry import GameRegistry
from backend.competition import CompetitionConflict


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
        self.tournaments: dict = self._read(self.data / "tournaments.json", {})
        if not registry.ids():
            raise ValueError("Cần cài ít nhất một game adapter.")
        fallback = registry.ids()[0]
        config = self._read(self.data / "rules.json", {})
        # Migrate v1's single flat rule object without erasing bots/replays.
        saved = config.get("game_rules", {} if "selected_game_id" in config else {fallback: config})
        self.game_rules = {game_id: registry.get(game_id).validate_rules(saved.get(game_id))
                           for game_id in registry.ids()}
        self.competition_locked = config.get("competition_locked", False)
        if not isinstance(self.competition_locked, bool):
            raise ValueError("competition_locked phải là boolean.")
        self.selected_game_id = config.get("selected_game_id", fallback)
        if self.selected_game_id not in registry.ids():
            if self.competition_locked:
                raise ValueError("Game đã khóa không còn được cài. Không tự chuyển cuộc thi sang game khác.")
            self.selected_game_id = fallback
        snapshot = config.get("active_rules_snapshot")
        if self.competition_locked and snapshot is None:
            raise ValueError("Cuộc thi đã khóa nhưng thiếu active_rules_snapshot.")
        self.active_rules_snapshot = (registry.get(self.selected_game_id).validate_rules(snapshot)
                                      if snapshot is not None else None)
        for bot in self.bots.values():
            bot.setdefault("game_id", fallback)
            if bot.get("sample_key") and ":" not in bot["sample_key"]:
                bot["sample_key"] = f"{bot['game_id']}:{bot['sample_key']}"
        # A restarted server must not leave phantom "running" matches.
        for match in self.matches.values():
            match.setdefault("game_id", match.get("game", fallback))
            if "rules" in match:
                match.setdefault("rules_snapshot", deepcopy(match["rules"]))
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
        self._write(self.data / "rules.json", {"version": 3, "selected_game_id": self.selected_game_id,
                                              "game_rules": self.game_rules,
                                              "competition_locked": self.competition_locked,
                                              "active_rules_snapshot": self.active_rules_snapshot})

    def get_competition(self):
        with self.lock:
            return {"selected_game_id": self.selected_game_id,
                    "competition_locked": self.competition_locked,
                    "active_rules_snapshot": deepcopy(self.active_rules_snapshot)}

    def open_competition(self):
        with self.lock:
            if self.competition_locked:
                raise CompetitionConflict("Cuộc thi đang mở.")
            previous_snapshot = self.active_rules_snapshot
            self.active_rules_snapshot = deepcopy(self.game_rules[self.selected_game_id])
            self.competition_locked = True
            try:
                self._save_config()
            except Exception:
                self.competition_locked = False
                self.active_rules_snapshot = previous_snapshot
                raise

    def close_competition(self):
        with self.lock:
            previous = self.competition_locked
            self.competition_locked = False
            try:
                self._save_config()
            except Exception:
                self.competition_locked = previous
                raise

    def require_submission_game(self, game_id: str):
        with self.lock:
            if game_id != self.selected_game_id:
                raise CompetitionConflict("Submission phải thuộc game ban tổ chức đang chọn.")

    def match_configuration(self, game_id: str | None, rules: dict | None):
        with self.lock:
            if not self.competition_locked:
                raise CompetitionConflict("Cuộc thi chưa mở hoặc đã đóng. Không thể tạo trận mới.")
            if game_id is not None and game_id != self.selected_game_id:
                raise CompetitionConflict("Chỉ game đang khóa được phép tạo trận.")
            if rules is not None:
                raise CompetitionConflict("Trận dùng luật đã khóa trên server; không nhận rules override.")
            return self.selected_game_id, deepcopy(self.active_rules_snapshot)

    def get_rules(self, game_id: str) -> dict:
        with self.lock:
            self.registry.get(game_id)
            return deepcopy(self.game_rules[game_id])

    def set_rules(self, game_id: str, rules: dict):
        with self.lock:
            if self.competition_locked:
                raise CompetitionConflict("Không thể chỉnh luật khi cuộc thi đã khóa.")
            previous_rules, previous_snapshot = self.game_rules[game_id], self.active_rules_snapshot
            self.game_rules[game_id] = self.registry.get(game_id).validate_rules(rules)
            if game_id == self.selected_game_id:
                self.active_rules_snapshot = None
            try:
                self._save_config()
            except Exception:
                self.game_rules[game_id], self.active_rules_snapshot = previous_rules, previous_snapshot
                raise
            return deepcopy(self.game_rules[game_id])

    def select_game(self, game_id: str):
        with self.lock:
            if self.competition_locked:
                raise CompetitionConflict("Không thể đổi game khi cuộc thi đã khóa.")
            self.registry.get(game_id)
            previous_game, previous_snapshot = self.selected_game_id, self.active_rules_snapshot
            self.selected_game_id = game_id
            self.active_rules_snapshot = None
            try:
                self._save_config()
            except Exception:
                self.selected_game_id, self.active_rules_snapshot = previous_game, previous_snapshot
                raise

    def get_matches(self) -> list[dict]:
        with self.lock:
            return deepcopy(list(reversed(self.matches.values())))

    def get_standings(self, game_id: str | None = None) -> list[dict]:
        with self.lock:
            players = {}

            for match in self.matches.values():
                if match.get("status") != "completed":
                    continue
                if game_id is not None and match.get("game_id") != game_id:
                    continue

                player_ids = {
                    "A": match.get("player_a_id"),
                    "B": match.get("player_b_id"),
                }

                # Bỏ qua trận không gắn với đủ hai người chơi.
                if not player_ids["A"] or not player_ids["B"]:
                    continue

                participants = match.get("participants") or {}

                for side, player_id in player_ids.items():
                    participant = participants.get(side) or {}
                    name = (
                        match.get(f"player_{side.lower()}_name_snapshot")
                        or participant.get("name")
                        or player_id[:6]
                    )

                    if player_id not in players:
                        players[player_id] = {
                            "player_id": player_id,
                            "nickname": name,
                            "played": 0,
                            "wins": 0,
                            "draws": 0,
                            "losses": 0,
                        }

                    players[player_id]["played"] += 1
                    # Dùng tên từ trận gần nhất trong lịch sử.
                    players[player_id]["nickname"] = name

                winner = (match.get("result") or {}).get("winner")

                if winner == "A":
                    players[player_ids["A"]]["wins"] += 1
                    players[player_ids["B"]]["losses"] += 1
                elif winner == "B":
                    players[player_ids["B"]]["wins"] += 1
                    players[player_ids["A"]]["losses"] += 1
                else:
                    players[player_ids["A"]]["draws"] += 1
                    players[player_ids["B"]]["draws"] += 1

            standings = sorted(
                players.values(),
                key=lambda player: (-player["wins"], player["nickname"].casefold()),
            )

            # Người bằng số trận thắng nhận cùng hạng.
            previous_wins = None
            for position, player in enumerate(standings, start=1):
                if player["wins"] != previous_wins:
                    player["rank"] = position
                    previous_wins = player["wins"]
                else:
                    player["rank"] = standings[position - 2]["rank"]

        return standings

    def save_match(self, match: dict):
        with self.lock:
            self.matches[match["id"]] = deepcopy(match)
            self._write(self.data / "matches.json", self.matches)

    def get_match(self, match_id: str) -> dict | None:
        with self.lock:
            return deepcopy(self.matches.get(match_id))

    def get_tournaments(self) -> list[dict]:
        with self.lock:
            return deepcopy(list(reversed(self.tournaments.values())))

    def get_tournament(self, tournament_id: str) -> dict | None:
        with self.lock:
            return deepcopy(self.tournaments.get(tournament_id))

    def save_tournament(self, tournament: dict):
        with self.lock:
            self.tournaments[tournament["id"]] = deepcopy(tournament)
            self._write(self.data / "tournaments.json", self.tournaments)

    def delete_tournament(self, tournament_id: str) -> bool:
        with self.lock:
            if tournament_id not in self.tournaments:
                return False
            previous = deepcopy(self.tournaments)
            del self.tournaments[tournament_id]
            try:
                self._write(self.data / "tournaments.json", self.tournaments)
            except Exception:
                self.tournaments = previous
                raise
            return True

    def start_replay(self, match_id: str, initial_frame: dict):
        with self.lock:
            path = self.replays / f"{match_id}.jsonl"
            # Exclusive create prevents an accidental reset of existing history.
            with path.open("xb") as stream:
                stream.write(self._frame_line(initial_frame))

    @staticmethod
    def _frame_line(frame: dict) -> bytes:
        return (json.dumps(frame, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")

    def append_replay_frame(self, match_id: str, frame: dict):
        line = self._frame_line(frame)
        with self.lock:
            # One complete frame per record; closing flushes before publishing to spectators.
            with (self.replays / f"{match_id}.jsonl").open("ab") as stream:
                stream.write(line)

    def get_replay(self, match_id: str) -> dict | None:
        with self.lock:
            path = self.replays / f"{match_id}.jsonl"
            if not path.exists():
                # Old JSON replays stay readable without rewriting user data.
                return self._read(self.replays / f"{match_id}.json", None)
            frames = []
            with path.open("rb") as stream:
                for line in stream:
                    if not line.endswith(b"\n"):
                        break  # A crash mid-write leaves an uncommitted final record.
                    frames.append(json.loads(line))
            return {"version": 1, "frames": frames}

    @staticmethod
    def new_id() -> str:
        return uuid4().hex[:16]
