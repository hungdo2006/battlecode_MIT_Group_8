"""Local operator control plane. No Docker, SSH, public route or mode hot-swap.

Admission intent survives restarts. A fresh acknowledgement, not a health probe,
proves the single Arena writer has closed admission and drained its work.
"""
import argparse
import asyncio
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from backend.execution import RunnerUnavailable
from backend.storage import Store
from backend.writer_lock import WriterLock


def canonical_mode(value):
    if value in ("sandbox", "local_sandbox"):
        return "local_sandbox"
    if value == "remote_sandbox":
        return value
    return "legacy"


class RunnerControl:
    def __init__(self, data, mode):
        self.directory = Path(data) / ".runner-control"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.mode = canonical_mode(mode)
        self.boot_id = uuid4().hex
        self.operations = 0

    def intent(self):
        path = self.directory / "intent.json"
        if not path.exists():
            return {"closed": False, "id": None}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if type(value["closed"]) is not bool or not isinstance(value["id"], str):
                raise ValueError()
            return value
        except (OSError, ValueError, KeyError, TypeError):
            return {"closed": True, "id": "invalid-intent"}

    @property
    def closed(self):
        return self.intent()["closed"]

    def require_open(self):
        if self.closed:
            raise RunnerUnavailable("Runner admission is closed for operator maintenance")

    @contextmanager
    def operation(self):
        # Used on the single asyncio event loop, including across awaits. A
        # request arriving after this check cannot acknowledge zero operations.
        self.require_open()
        self.operations += 1
        try:
            yield
        finally:
            self.operations -= 1

    def request(self, closed):
        with WriterLock(self.directory):
            value = {"closed": closed, "id": uuid4().hex}
            # Record only fixed actions and IDs; never environment/credentials.
            with (self.directory / "audit.jsonl").open("a", encoding="utf-8") as target:
                target.write(json.dumps({"time": time.time(), "action": "drain" if closed else "resume",
                                         "id": value["id"]}) + "\n")
                target.flush()
                os.fsync(target.fileno())
            Store._write(self.directory / "intent.json", value)
        return value["id"]

    def status(self):
        return json.loads((self.directory / "status.json").read_text(encoding="utf-8"))

    def publish(self, manager, uploading, health):
        intent = self.intent()
        value = {"protocol": 1, "boot_id": self.boot_id, "time": time.time(),
                 "request_id": intent["id"], "admission_closed": intent["closed"],
                 "mode": self.mode, "active_matches": len(manager.live),
                 "operations": self.operations, "uploading": bool(uploading),
                 "ready": bool(health.get("ready")), "transport": health.get("transport", "local"),
                 "cleanup_pending": len(getattr(manager.runner, "pending_closes", {}))}
        Store._write(self.directory / "status.json", value)
        return value


def validate_status(status, *, drained=False, mode=None, ready=False, now=None):
    now = time.time() if now is None else now
    if status.get("protocol") != 1 or not -1 <= now - status.get("time", 0) <= 10:
        raise RuntimeError("Missing/stale switch-aware Arena acknowledgement")
    if mode and status.get("mode") != mode:
        raise RuntimeError("Active runner mode differs from requested mode")
    if drained and (not status.get("admission_closed") or status.get("active_matches") != 0
                    or status.get("operations") != 0 or status.get("uploading") is not False
                    or status.get("cleanup_pending") != 0):
        raise RuntimeError("Runner must drain matches, uploads, dispatch and Docker cleanup first")
    if ready and not status.get("ready"):
        raise RuntimeError("Runner is not ready; admission stays closed")
    if ready and status.get("mode") == "remote_sandbox" and status.get("transport") != "remote-outbound":
        raise RuntimeError("Remote worker transport is not ready")
    return status


async def monitor(control, manager, upload_lock):
    while True:
        health = await asyncio.to_thread(manager.runner.health)
        control.publish(manager, upload_lock.locked(), health)
        await asyncio.sleep(0.5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "drain", "resume"))
    parser.add_argument("--data", default="/app/data")
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--mode", choices=("local_sandbox", "remote_sandbox"))
    args = parser.parse_args()
    control = RunnerControl(args.data, os.environ.get("ARENA_RUNNER", "legacy"))
    try:
        before = validate_status(control.status(), mode=args.mode, ready=args.action == "resume")
        if args.action == "status":
            print(json.dumps(before))
            return
        request = control.request(args.action == "drain")
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            status = control.status()
            if status.get("request_id") == request:
                validate_status(status, drained=args.action == "drain", mode=args.mode,
                                ready=args.action == "resume")
                print(json.dumps(status))
                return
            time.sleep(0.2)
        raise RuntimeError("Arena did not acknowledge admission request")
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, "BLOCKED: " + str(exc) + "\n")


if __name__ == "__main__":
    main()
