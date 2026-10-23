"""Single-worker, outbound-only RPC mailbox for a trusted remote Sandbox controller.

The cloud process never opens a connection to a PC or stores its Docker token.
All requests are bounded, have random IDs, and fail closed after disconnect.
This is in-memory intentionally: one Arena process holds the existing writer lock.
"""
import json
import re
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass, field

from backend.execution import RunnerUnavailable

MAX_REQUESTS = 8
MAX_RESULT_BYTES = 16 * 1024 * 1024
STALE_AFTER = 20.0
POLL_SECONDS = 8.0

_ALLOWED = re.compile(
    r"^/(?:health|owner|heartbeat|release|"
    r"(?:compile|runtime|close)/[a-zA-Z0-9_-]{1,96}|"
    r"runtime/[a-zA-Z0-9_-]{1,96}/request|"
    r"battlecode/(?:compile|match)/[a-zA-Z0-9_-]{1,96})$"
)


@dataclass
class Pending:
    request_id: str
    session: str
    path: str
    payload: dict | None
    event: threading.Event = field(default_factory=threading.Event)
    answer: tuple[int, dict] | None = None
    error: str | None = None


class RemoteRelay:
    def __init__(self):
        self.cv = threading.Condition(threading.RLock())
        self.session = None
        self.last_poll = 0.0
        self.queue = deque()
        self.pending = {}
        self.closed = False

    def _expire(self, reason):
        for request in self.pending.values():
            request.error = reason
            request.event.set()
        self.pending.clear()
        self.queue.clear()

    def connect(self):
        with self.cv:
            if self.closed:
                raise RunnerUnavailable("Remote runner is stopped")
            if self.session and time.monotonic() - self.last_poll <= STALE_AFTER:
                raise ValueError("A remote runner is already connected")
            self._expire("Remote runner session was replaced")
            self.session = secrets.token_hex(24)
            self.last_poll = time.monotonic()
            self.cv.notify_all()
            return self.session

    def _check_session(self, session):
        if not isinstance(session, str) or not self.session or not secrets.compare_digest(session, self.session):
            raise ValueError("Invalid or expired remote runner session")
        if self.closed:
            raise ValueError("Remote runner is shutting down")

    def poll(self, session, timeout=POLL_SECONDS):
        with self.cv:
            self._check_session(session)
            self.last_poll = time.monotonic()
            deadline = time.monotonic() + min(float(timeout), POLL_SECONDS)
            while not self.queue:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self.cv.wait(remaining)
                self._check_session(session)
                self.last_poll = time.monotonic()
            request = self.queue.popleft()
            return {"id": request.request_id, "path": request.path, "payload": request.payload}

    def connected(self):
        with self.cv:
            return (not self.closed and self.session is not None
                    and time.monotonic() - self.last_poll <= STALE_AFTER)

    def call(self, path, payload=None, *, timeout=45, max_bytes=1024 * 1024):
        if not isinstance(path, str) or not _ALLOWED.fullmatch(path):
            raise ValueError("Remote controller endpoint is not allowlisted")
        if payload is not None and not isinstance(payload, dict):
            raise ValueError("Remote request must contain an object")
        if len(json.dumps(payload).encode("utf-8")) > 1024 * 1024:
            raise RunnerUnavailable("Remote controller request exceeds limit")
        with self.cv:
            if not self.connected():
                raise RunnerUnavailable("Remote runner not connected; no local fallback")
            if len(self.pending) >= MAX_REQUESTS:
                raise RunnerUnavailable("Remote runner queue is full")
            request = Pending(secrets.token_hex(16), self.session, path, payload)
            self.pending[request.request_id] = request
            self.queue.append(request)
            self.cv.notify_all()
        try:
            if not request.event.wait(timeout + 3):
                raise RunnerUnavailable("Remote runner request timed out; match must be interrupted")
            if request.error:
                raise RunnerUnavailable(request.error)
            if request.answer is None:
                raise RunnerUnavailable("Remote runner returned no result")
            status, result = request.answer
            data_size = len(json.dumps(result, ensure_ascii=False).encode("utf-8"))
            if data_size > min(max_bytes, MAX_RESULT_BYTES):
                raise RunnerUnavailable("Remote runner response exceeds limit")
            return status, result
        finally:
            with self.cv:
                self.pending.pop(request.request_id, None)
                try:
                    self.queue.remove(request)
                except ValueError:
                    pass

    def respond(self, session, request_id, status, result):
        if (not isinstance(request_id, str) or len(request_id) != 32
                or type(status) is not int or status not in (200, 400, 401, 403, 404, 409, 422, 503)
                or not isinstance(result, dict)):
            raise ValueError("Invalid remote controller response")
        with self.cv:
            self._check_session(session)
            request = self.pending.get(request_id)
            if request is None or request.session != session or request.answer is not None:
                raise ValueError("Remote controller response is late, duplicate or unknown")
            request.answer = status, result
            request.event.set()

    def disconnect(self, session):
        with self.cv:
            self._check_session(session)
            self.session = None
            self.last_poll = 0.0
            self._expire("Remote runner disconnected; no local fallback")
            self.cv.notify_all()

    def shutdown(self):
        with self.cv:
            self.closed = True
            self.session = None
            self._expire("Remote runner is shutting down")
            self.cv.notify_all()
