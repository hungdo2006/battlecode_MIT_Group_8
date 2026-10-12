"""Small persistent browser identities, not accounts or an authorization system.

Only a hash of the opaque cookie is saved. Public participant IDs are separate
from tokens, so displaying a bot's owner never exposes a reusable cookie.
"""
import hashlib
import secrets
import threading
import time
from copy import deepcopy
from pathlib import Path

from backend.storage import Store

COOKIE_NAME = "arena_session"
SESSION_SECONDS = 30 * 24 * 60 * 60


class Sessions:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        self.records = Store._read(path, {})

    @staticmethod
    def key(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def resolve(self, token: str | None):
        if not token or len(token) > 128:
            return None
        key = self.key(token)
        with self.lock:
            record = self.records.get(key)
            if record and record["expires_at"] > time.time():
                return deepcopy(record["participant"]), key
        return None

    def create(self):
        token = secrets.token_urlsafe(32)
        key = self.key(token)
        participant_id = secrets.token_hex(8)
        participant = {"id": participant_id, "name": f"Player-{participant_id[:4].upper()}"}
        with self.lock:
            now = time.time()
            self.records = {k: v for k, v in self.records.items() if v["expires_at"] > now}
            self.records[key] = {"participant": participant, "expires_at": now + SESSION_SECONDS}
            Store._write(self.path, self.records)
        return deepcopy(participant), token, key

    def rename(self, key: str, name: str):
        with self.lock:
            self.records[key]["participant"]["name"] = name
            Store._write(self.path, self.records)
            return deepcopy(self.records[key]["participant"])
