"""Optional off-host Sandbox runner, using the existing lease and artifact protocol.

The worker PC polls the Arena over HTTPS, then talks to its own controller
over a Docker-internal network. Arena has no Docker socket or PC callback URL.
"""
import os
import threading
import uuid

from backend.execution import RunnerUnavailable
from backend.remote_relay import RemoteRelay
from backend.sandbox_client import ControllerRejected, SandboxRunner


class RemoteSandboxRunner(SandboxRunner):
    # Keep the existing execution/Official policies that require mode='sandbox'.
    mode = "sandbox"

    def __init__(self):
        key = os.environ.get("ARENA_REMOTE_RUNNER_KEY", "")
        if len(key.encode("utf-8")) < 32:
            raise ValueError("ARENA_REMOTE_RUNNER_KEY must contain 32+ private random bytes")
        super().__init__(remote=True)
        self.relay = RemoteRelay()
        self._control_thread = None

    def rpc(self, path, payload=None, timeout=45, lease=None, max_bytes=1024 * 1024):
        body = None
        if payload is not None:
            with self.lease_lock:
                body = {"owner": self.owner, **payload}
                if path != "/owner":
                    body["lease"] = self.lease if lease is None else lease
        status, result = self.relay.call(path, body, timeout=timeout, max_bytes=max_bytes)
        if status != 200:
            raise ControllerRejected(status)
        return result

    def startup(self):
        # Starting the cloud service must not require a laptop already online.
        # No jobs are admitted until the remote Controller is healthy and leased.
        self._control_thread = threading.Thread(target=self._control, daemon=True,
                                               name="remote-runner-control")
        self._control_thread.start()

    def _control(self):
        while not self.stop.is_set():
            try:
                if not self.relay.connected():
                    self.available = False
                elif not self.available:
                    health = self.rpc("/health", timeout=3)
                    try:
                        self.claim_epoch(health["epoch"])
                    except ControllerRejected as exc:
                        if exc.status == 409:
                            # A retired Controller owner must never resurrect
                            # after its lease expires. Old in-flight sessions
                            # keep their captured lease and cannot use this one.
                            with self.lease_lock:
                                self.owner = uuid.uuid4().hex
                                self.lease = None
                                self.epoch = None
                        raise
                    self._save_image_ids(health)
                    self.available = bool(health["ready"])
                else:
                    self.heartbeat_once()
            except (RunnerUnavailable, ValueError, KeyError):
                self.available = False
            self.stop.wait(3)

    def health(self):
        if not self.relay.connected():
            self.available = False
        data = super().health()
        data["transport"] = "remote-outbound"
        return data

    def shutdown(self):
        self.stop.set()
        if self._control_thread:
            self._control_thread.join(timeout=4)
        if self.relay.connected() and self.lease:
            try:
                self.rpc("/release", {}, timeout=4)
            except RunnerUnavailable:
                pass
        self.relay.shutdown()
        self.available = False
