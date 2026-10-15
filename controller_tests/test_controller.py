"""Controller policy tests, no Engine required. Run Dockerfile.controller tests target."""
import threading

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import sandbox_controller.service as service

OWNER = 'a' * 32


@pytest.fixture
def control():
    controller = service.Controller.__new__(service.Controller)
    controller.lock, controller.owner, controller.jobs = threading.RLock(), OWNER, {}
    return controller


def test_cancelled_but_not_removed_container_still_uses_capacity(control):
    for n in range(4):
        job = service.Job('runtime', OWNER, '')
        job.cancelled.set()
        job.container = object()  # Engine is offline: cleanup has not succeeded.
        control.jobs[str(n)] = job
    with pytest.raises(HTTPException) as exc:
        control.reserve('new', service.Open(owner=OWNER, artifact_id='a', artifact_digest='b'*64), 'runtime')
    assert exc.value.status_code == 503


def test_duplicate_observation_has_exactly_one_execution(control):
    class Pipe:
        calls = 0
        def request(self, observation):
            self.calls += 1
            return {'count': self.calls}
    job = service.Job('runtime', OWNER, '')
    job.pipe = Pipe()
    control.jobs['runtime'] = job
    payload = service.Observation(owner=OWNER, seq=0, observation={'turn': 1})
    assert control.request('runtime', payload) == control.request('runtime', payload) == {'action': {'count': 1}}
    assert job.pipe.calls == 1
    for seq, observation in ((0, {'turn': 2}), (3, {'turn': 1})):
        with pytest.raises(HTTPException) as exc:
            control.request('runtime', service.Observation(owner=OWNER, seq=seq, observation=observation))
        assert exc.value.status_code == 409
    assert job.pipe.calls == 1


def test_private_api_auth_body_limit_and_strict_options(monkeypatch, control):
    monkeypatch.setenv('ARENA_RUNNER_TOKEN', 'test-only-controller-token-at-least-32-characters')
    monkeypatch.setattr(service, 'Controller', lambda: control)
    control.shutdown = lambda: None
    with TestClient(service.create_app()) as client:
        assert client.post('/owner', json={'owner': OWNER}).status_code == 401
        headers = {'Authorization': 'Bearer test-only-controller-token-at-least-32-characters'}
        assert client.post('/runtime/test', headers=headers, json={
            'owner': OWNER, 'artifact_id': 'a', 'artifact_digest': 'b'*64,
            'image': 'arbitrary', 'privileged': True}).status_code == 422
        assert client.post('/owner', headers=headers, content=b'x'*(1024*1024+1)).status_code == 413
        assert client.get('/docs').status_code == 401


def test_late_start_cannot_replace_tombstone(control):
    closed = service.Job('closed', OWNER, '')
    closed.cancelled.set()
    control.jobs['late'] = closed
    with pytest.raises(HTTPException) as exc:
        control.reserve('late', service.Open(owner=OWNER, artifact_id='a', artifact_digest='b'*64), 'runtime')
    assert exc.value.status_code == 409


def test_cancel_while_engine_is_creating_does_not_leak_container(control):
    entered, release = threading.Event(), threading.Event()
    class Container:
        removed = False
        def remove(self, force):
            self.removed = True
    container = Container()
    class Engine:
        def create(self, *args):
            entered.set()
            assert release.wait(2)
            return container
    control.engine = Engine()
    job = service.Job('runtime', OWNER, '')
    failures = []
    def delayed_start():
        try:
            control.ensure_container('r-race', job)
        except service.InfrastructureError as exc:
            failures.append(exc)
    thread = threading.Thread(target=delayed_start)
    thread.start()
    assert entered.wait(2)
    control.close(job)
    release.set()
    thread.join(2)
    assert not thread.is_alive() and failures
    assert container.removed and job.container is None
