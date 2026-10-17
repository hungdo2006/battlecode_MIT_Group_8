"""Real client serialization + ASGI API + artifact IO, with a fake Docker Engine.

This verifies the private wire protocol, not Docker isolation/resource limits.
"""
import io
from urllib.error import HTTPError
from urllib.parse import urlparse

from fastapi.testclient import TestClient
import pytest

import backend.sandbox_client as client_module
from backend.sandbox_client import ControllerRejected, SandboxRunner
from sandbox_controller.artifacts import pack
import sandbox_controller.service as service


@pytest.fixture
def wire(monkeypatch, tmp_path):
    monkeypatch.setenv('ARENA_RUNNER_TOKEN', 'test-only-private-protocol-token-at-least-32')
    monkeypatch.setenv('SANDBOX_ARTIFACTS', str(tmp_path / 'artifacts'))
    class Engine:
        image = 'sha256:' + 'a'*64
        def __init__(self, *args):
            self.client = type('Client', (), {'ping': lambda self: True})()
            self.containers = []
        def create(self, *args):
            container = type('Container', (), {'remove': lambda self, force: None})()
            self.containers.append(container)
            return container
        def compile(self, *args):
            return True, '', pack({'bot.py': b'pass'}, 'out/')
        def provision(self, *args):
            pass
    class Pipe:
        def __init__(self, *args):
            self.count = 0
        def request(self, observation):
            self.count += 1
            return {'count': self.count}
        def close(self):
            pass
    monkeypatch.setattr(service, 'Engine', Engine)
    monkeypatch.setattr(service, 'Pipe', Pipe)
    class Bridge:
        current = None
        def open(self, request, timeout):
            response = self.current.request('GET' if request.data is None else 'POST',
                                            urlparse(request.full_url).path, content=request.data,
                                            headers=dict(request.header_items()))
            if response.status_code >= 400:
                raise HTTPError(request.full_url, response.status_code, 'rejected', {}, io.BytesIO(response.content))
            return io.BytesIO(response.content)
    bridge = Bridge()
    monkeypatch.setattr(client_module, 'build_opener', lambda *args: bridge)
    return bridge


def test_runner_compile_runtime_duplicates_close_and_graceful_release(wire, tmp_path):
    with TestClient(service.create_app()) as controller:
        wire.current = controller
        runner = SandboxRunner()
        try:
            runner.startup()
            runner.heartbeat_once()
            bot = runner.prepare(b'pass', 'bot.py', tmp_path / 'source')
            session = runner.session(bot, 'r-persistent')
            session.start()
            session.start()  # Idempotent remote open.
            assert session.request({'turn': 0}) == {'count': 1}
            assert runner.rpc('/runtime/r-persistent/request', {'seq': 0, 'observation': {'turn': 0}}) == {'action': {'count': 1}}
            assert session.request({'turn': 1}) == {'count': 2}
            assert len(controller.app.state.controller.engine.containers) == 2
            session.close()
            session.close()
            assert not runner.pending_closes
        finally:
            runner.shutdown()
        assert controller.app.state.controller.owner is None


def test_controller_restart_recovers_new_jobs_but_never_resumes_old_runtime(wire, tmp_path):
    runner = SandboxRunner()
    try:
        with TestClient(service.create_app()) as first:
            wire.current = first
            runner.startup()
            bot = runner.prepare(b'pass', 'bot.py', tmp_path / 'source')
            old = runner.session(bot, 'r-before-restart')
            old.start()
            old_epoch, old_lease = runner.epoch, runner.lease
        with TestClient(service.create_app()) as second:
            wire.current = second
            runner.heartbeat_once()
            assert runner.epoch != old_epoch and runner.lease != old_lease
            with pytest.raises(ControllerRejected):
                old.request({'turn': 1})
            old.close()
            new = runner.session(bot, 'r-after-restart')
            new.start()
            assert new.request({'turn': 0}) == {'count': 1}
            new.close()
            runner.shutdown()
    finally:
        runner.shutdown()
