"""Outbound-only PC agent. No Docker socket, server login or inbound port.

Controller is reachable ONLY at http://controller:9000 on the PC's private
Compose network. HTTPS validates the AWS hostname using system trust roots.
"""
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

MAX_REPLY = 16 * 1024 * 1024
MAX_INPUT = 1024 * 1024
ALLOWED_PATH = re.compile(
    r"^/(?:health|owner|heartbeat|release|"
    r"(?:compile|runtime|close)/[a-zA-Z0-9_-]{1,96}|"
    r"runtime/[a-zA-Z0-9_-]{1,96}/request|"
    r"battlecode/(?:compile|match)/[a-zA-Z0-9_-]{1,96})$"
)


class AgentError(RuntimeError):
    pass


class WorkerAgent:
    def __init__(self, server_url=None, key=None):
        self.server = (server_url or os.environ.get("ARENA_REMOTE_SERVER_URL", "")).rstrip("/")
        parsed = urlsplit(self.server)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.path or parsed.query or parsed.fragment or not parsed.netloc):
            raise ValueError("ARENA_REMOTE_SERVER_URL must be an HTTPS origin with a trusted certificate")
        self.key = key if key is not None else os.environ.get("ARENA_REMOTE_RUNNER_KEY", "")
        if len(self.key.encode("utf-8")) < 32:
            raise ValueError("ARENA_REMOTE_RUNNER_KEY must contain 32+ secret bytes")
        self.session = None
        self.stop = threading.Event()
        # Never use an inherited HTTP proxy for controller or bearer credentials.
        self.opener = build_opener(ProxyHandler({}))

    def _request(self, url, *, payload=None, session=None, is_controller=False, timeout=15, limit=MAX_REPLY):
        body = None if payload is None else json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        if body is not None and len(body) > MAX_INPUT + 1024:
            raise AgentError("Controller request exceeds allowed size")
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if is_controller:
            token = os.environ.get("ARENA_RUNNER_TOKEN", "")
            if len(token) < 32:
                raise AgentError("PC Controller token is not configured")
        else:
            token = self.key
            if session:
                headers["X-Arena-Runner-Session"] = session
        headers["Authorization"] = "Bearer " + token
        req = Request(url, data=body, headers=headers,
                      method="POST" if body is not None else "GET")
        try:
            with self.opener.open(req, timeout=timeout) as response:
                data = response.read(limit + 1)
                status = response.status
        except HTTPError as error:
            status = error.code
            data = error.read(min(limit, 8192) + 1)
        except (OSError, URLError) as error:
            raise AgentError("Runner connection lost") from error
        if len(data) > limit:
            raise AgentError("Runner response too large")
        if status == 204:
            return status, None
        try:
            answer = json.loads(data) if data else {}
        except (UnicodeDecodeError, ValueError) as error:
            raise AgentError("Remote endpoint returned invalid JSON") from error
        if not isinstance(answer, dict):
            raise AgentError("Remote endpoint returned a non-object")
        return status, answer

    def cloud(self, path, *, payload=None, session=None, timeout=15):
        status, data = self._request(self.server + "/api/remote-runner/" + path,
                                     payload=payload, session=session,
                                     timeout=timeout, limit=MAX_INPUT)
        if status not in (200, 204):
            raise AgentError("Remote worker rejected by cloud; check secret and session")
        return data

    def controller(self, task):
        path = task.get("path")
        if not isinstance(path, str) or not ALLOWED_PATH.fullmatch(path):
            return 400, {"detail": "Unsupported controller operation"}
        payload = task.get("payload")
        if payload is not None and not isinstance(payload, dict):
            return 400, {"detail": "Invalid controller payload"}
        try:
            return self._request("http://controller:9000" + path,
                                 payload=payload, is_controller=True,
                                 timeout=195 if path.startswith("/battlecode/match/") else 48)
        except AgentError:
            return 503, {"detail": "Private sandbox controller unavailable"}

    def execute(self, task, session):
        request_id = task.get("id")
        if not isinstance(request_id, str) or not re.fullmatch(r"[0-9a-f]{32}", request_id):
            return
        status, result = self.controller(task)
        if status not in (200, 400, 401, 403, 404, 409, 422, 503):
            status, result = 503, {"detail": "Private sandbox controller returned unsupported status"}
        try:
            self.cloud("respond", payload={"id": request_id, "status": status, "result": result},
                       session=session, timeout=25)
        except AgentError:
            # Server may have timed out or issued a new lease; never retry a
            # late result as a new match or write to the Online database.
            pass

    def run(self):
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="sandbox-rpc") as pool:
            while not self.stop.is_set():
                try:
                    result = self.cloud("connect", payload={})
                    session = result["session"]
                    if not isinstance(session, str) or len(session) != 48:
                        raise AgentError("Invalid cloud session")
                    self.session = session
                    while not self.stop.is_set():
                        task = self.cloud("poll", session=session, timeout=15)
                        if task is not None:
                            pool.submit(self.execute, task, session)
                except (AgentError, KeyError, ValueError):
                    self.session = None
                    self.stop.wait(4)
            if self.session:
                try:
                    self.cloud("disconnect", payload={}, session=self.session, timeout=3)
                except AgentError:
                    pass


def main():
    agent = WorkerAgent()
    try:
        agent.run()
    except KeyboardInterrupt:
        agent.stop.set()


if __name__ == "__main__":
    main()
