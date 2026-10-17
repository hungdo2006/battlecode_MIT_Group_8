"""Controller policy tests, no Engine required. Run Dockerfile.controller tests target."""
import threading
import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import sandbox_controller.service as service

OWNER = 'a' * 32
LEASE = 'b' * 32
EPOCH = 'c' * 32


@pytest.fixture
def control():
    controller = service.Controller.__new__(service.Controller)
    controller.lock, controller.owner, controller.jobs = threading.RLock(), OWNER, {}
    controller.lease, controller.epoch, controller.heartbeat = LEASE, EPOCH, time.monotonic()
    controller.used_ids, controller.retired_owners = set(), set()
    return controller


def test_cancelled_but_not_removed_container_still_uses_capacity(control):
    for n in range(4):
        job = service.Job('runtime', OWNER, '', lease=LEASE)
        job.cancelled.set()
        job.container = object()  # Engine is offline: cleanup has not succeeded.
        control.jobs[str(n)] = job
    with pytest.raises(HTTPException) as exc:
        control.reserve('new', service.Open(owner=OWNER, lease=LEASE, artifact_id='a', artifact_digest='b'*64), 'runtime')
    assert exc.value.status_code == 503


def test_duplicate_observation_has_exactly_one_execution(control):
    class Pipe:
        calls = 0
        def request(self, observation):
            self.calls += 1
            return {'count': self.calls}
    job = service.Job('runtime', OWNER, '', lease=LEASE)
    job.pipe = Pipe()
    control.jobs['runtime'] = job
    payload = service.Observation(owner=OWNER, lease=LEASE, seq=0, observation={'turn': 1})
    assert control.request('runtime', payload) == control.request('runtime', payload) == {'action': {'count': 1}}
    assert job.pipe.calls == 1
    for seq, observation in ((0, {'turn': 2}), (3, {'turn': 1})):
        with pytest.raises(HTTPException) as exc:
            control.request('runtime', service.Observation(owner=OWNER, lease=LEASE, seq=seq, observation=observation))
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
            'owner': OWNER, 'lease': LEASE, 'artifact_id': 'a', 'artifact_digest': 'b'*64,
            'image': 'arbitrary', 'privileged': True}).status_code == 422
        assert client.post('/owner', headers=headers, content=b'x'*(1024*1024+1)).status_code == 413
        assert client.get('/docs').status_code == 401


def test_late_start_cannot_replace_tombstone(control):
    closed = service.Job('closed', OWNER, '', lease=LEASE)
    closed.cancelled.set()
    control.jobs['late'] = closed
    with pytest.raises(HTTPException) as exc:
        control.reserve('late', service.Open(owner=OWNER, lease=LEASE, artifact_id='a', artifact_digest='b'*64), 'runtime')
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
    job = service.Job('runtime', OWNER, '', lease=LEASE)
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


def payload(**kwargs):
    return service.Payload(owner=OWNER, lease=LEASE, **kwargs)


def opening(**kwargs):
    return service.Open(owner=OWNER, lease=LEASE, artifact_id='artifact', artifact_digest='d'*64, **kwargs)


def test_live_owner_claim_is_idempotent_and_foreign_claim_cannot_close_jobs(control):
    job = control.reserve('active', opening(), 'runtime')
    assert control.claim(OWNER, EPOCH)['lease'] == LEASE
    with pytest.raises(HTTPException) as exc:
        control.claim('d'*32, EPOCH)
    assert exc.value.status_code == 409
    assert control.owner == OWNER and not job.cancelled.is_set()


def test_expired_owner_is_fenced_even_before_reaper_tick(control, monkeypatch):
    now = control.heartbeat
    job = control.reserve('active', opening(), 'runtime')
    monkeypatch.setattr(service.time, 'monotonic', lambda: now + 21)
    with pytest.raises(HTTPException) as exc:
        control.renew(payload())
    assert exc.value.status_code == 409 and job.cancelled.is_set()
    for operation in (lambda: control.claim(OWNER, EPOCH),
                      lambda: control.reserve('late', opening(), 'runtime'),
                      lambda: control.close_id('active', payload())):
        with pytest.raises(HTTPException):
            operation()
    result = control.claim('d'*32, EPOCH)
    assert result['lease'] != LEASE
    with pytest.raises(HTTPException):
        control.release(payload())
    assert control.owner == 'd'*32


def test_release_allows_restart_but_never_old_lease_or_epoch(control):
    control.release(payload())
    result = control.claim('d'*32, EPOCH)
    for operation in (lambda: control.claim('e'*32, 'f'*32),
                      lambda: control.renew(payload()),
                      lambda: control.claim(OWNER, EPOCH)):
        with pytest.raises(HTTPException) as exc:
            operation()
        assert exc.value.status_code == 409
    assert control.lease == result['lease']


def test_closed_retention_starts_at_close_and_ids_never_reopen(control, monkeypatch):
    now = control.heartbeat
    job = control.reserve('old-runtime', opening(), 'runtime')
    job.created = now - 500
    monkeypatch.setattr(service.time, 'monotonic', lambda: now)
    control.close_id('old-runtime', payload())
    control.reap_once()
    assert job.closed_at == now and 'old-runtime' in control.jobs
    monkeypatch.setattr(service.time, 'monotonic', lambda: now + 121)
    control.heartbeat = now + 121
    control.reap_once()
    assert 'old-runtime' not in control.jobs and 'old-runtime' in control.used_ids
    assert control.close_id('old-runtime', payload()) == {'closed': True}
    with pytest.raises(HTTPException) as exc:
        control.reserve('old-runtime', opening(), 'runtime')
    assert exc.value.status_code == 409


def test_repeated_cleanup_does_not_extend_closed_at_and_failed_remove_keeps_handle(control, monkeypatch):
    now = control.heartbeat
    class Container:
        def remove(self, force):
            raise RuntimeError('offline')
    job = control.reserve('cleanup', opening(), 'runtime')
    job.container = Container()
    control.close(job)
    closed_at = job.closed_at
    monkeypatch.setattr(service.time, 'monotonic', lambda: now + 200)
    control.heartbeat = now + 200
    control.reap_once()
    assert job.closed_at == closed_at and control.jobs['cleanup'].container is not None


def test_duplicate_compile_and_open_execute_once(control, monkeypatch):
    import base64
    class Container:
        def remove(self, force):
            pass
    class Engine:
        image = 'image'
        calls = 0
        compiles = 0
        def create(self, *args):
            self.calls += 1
            return Container()
        def compile(self, *args):
            self.compiles += 1
            return False, 'test diagnostic', b''
        def provision(self, *args):
            pass
    class Store:
        def load(self, *args):
            return 'py', {'bot.py': b'pass'}
    control.engine, control.store = Engine(), Store()
    monkeypatch.setattr(service, 'Pipe', lambda *args: type('Pipe', (), {'close': lambda self: None})())
    code = service.Compile(owner=OWNER, lease=LEASE, language='py', source=base64.b64encode(b'bad').decode())
    assert control.compile('compile-once', code) == control.compile('compile-once', code)
    assert control.engine.calls == control.engine.compiles == 1
    assert control.open('runtime-once', opening()) == control.open('runtime-once', opening()) == {'ready': True}
    assert control.engine.calls == 2
    control.close_id('runtime-once', payload())
    with pytest.raises(HTTPException):
        control.open('runtime-once', opening())


def test_duplicate_bot_error_is_cached_and_not_executed_twice(control):
    class Pipe:
        calls = 0
        def request(self, observation):
            self.calls += 1
            raise service.BotError('invalid bot')
        def close(self):
            pass
    job = control.reserve('bot-error', opening(), 'runtime')
    job.pipe = Pipe()
    observation = service.Observation(owner=OWNER, lease=LEASE, seq=0, observation={})
    assert control.request('bot-error', observation) == control.request('bot-error', observation) == {'bot_error': 'invalid bot'}
    assert job.pipe.calls == 1


def test_job_id_ledger_is_bounded_fail_closed(control, monkeypatch):
    monkeypatch.setattr(service, 'MAX_USED_IDS', 1)
    control.close_id('one', payload())
    with pytest.raises(HTTPException) as exc:
        control.reserve('two', opening(), 'runtime')
    assert exc.value.status_code == 503


def test_http_lease_fencing_and_restart_epoch(monkeypatch, control):
    monkeypatch.setenv('ARENA_RUNNER_TOKEN', 'test-only-controller-token-at-least-32-characters')
    monkeypatch.setattr(service, 'Controller', lambda: control)
    control.shutdown = lambda: None
    headers = {'Authorization': 'Bearer test-only-controller-token-at-least-32-characters'}
    with TestClient(service.create_app()) as client:
        assert client.post('/owner', headers=headers, json={'owner': OWNER, 'epoch': EPOCH}).json()['lease'] == LEASE
        assert client.post('/owner', headers=headers, json={'owner': 'd'*32, 'epoch': EPOCH}).status_code == 409
        assert client.post('/heartbeat', headers=headers, json={'owner': OWNER, 'lease': 'f'*32}).status_code == 409
        assert client.post('/release', headers=headers, json=payload().model_dump()).status_code == 200
        assert client.post('/heartbeat', headers=headers, json=payload().model_dump()).status_code == 409


def test_infrastructure_failure_never_replays_previous_action(control):
    class Pipe:
        calls = 0
        def request(self, observation):
            self.calls += 1
            if self.calls > 1:
                raise service.InfrastructureError('response lost')
            return {'turn': 0}
        def close(self):
            pass
    job = control.reserve('ambiguous', opening(), 'runtime')
    job.pipe = Pipe()
    first = service.Observation(owner=OWNER, lease=LEASE, seq=0, observation={})
    second = service.Observation(owner=OWNER, lease=LEASE, seq=1, observation={})
    assert control.request('ambiguous', first) == {'action': {'turn': 0}}
    for _ in range(2):
        with pytest.raises(service.InfrastructureError):
            control.request('ambiguous', second)
    assert job.pipe.calls == 2 and job.response is None


def test_cancelled_pipe_failure_is_infrastructure_not_bot_fault(control):
    job = control.reserve('cancel-during-action', opening(), 'runtime')
    class Pipe:
        def request(self, observation):
            control.close(job)
            raise service.BotError('process stopped by cancellation')
        def close(self):
            pass
    job.pipe = Pipe()
    with pytest.raises(service.InfrastructureError, match='no bot fault'):
        control.request('cancel-during-action', service.Observation(owner=OWNER, lease=LEASE, seq=0, observation={}))


def test_parallel_claims_have_exactly_one_winner(control):
    from concurrent.futures import ThreadPoolExecutor
    control.release(payload())
    def claim(owner):
        try:
            return control.claim(owner, EPOCH)['lease']
        except HTTPException as exc:
            assert exc.status_code == 409
            return None
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(claim, ['d'*32, 'e'*32]))
    assert sum(result is not None for result in results) == 1


def test_completed_action_receipt_after_close_never_executes_or_reopens(control):
    job = control.reserve('closed-action', opening(), 'runtime')
    class Pipe:
        calls = 0
        def request(self, observation):
            self.calls += 1
            return {'type': 'wait'}
        def close(self):
            pass
    job.pipe = Pipe()
    done = service.Observation(owner=OWNER, lease=LEASE, seq=0, observation={'turn': 0})
    expected = control.request('closed-action', done)
    control.close_id('closed-action', payload())
    assert job.cancelled.is_set() and job.closed_at is not None
    assert control.request('closed-action', done) == expected
    assert job.pipe.calls == 1 and job.container is None
    for seq, state in ((1, {'turn': 1}), (0, {'different': True})):
        with pytest.raises(service.InfrastructureError):
            control.request('closed-action', service.Observation(owner=OWNER, lease=LEASE, seq=seq, observation=state))
    control.release(payload())
    with pytest.raises(HTTPException) as exc:
        control.request('closed-action', done)
    assert exc.value.status_code == 409 and job.pipe.calls == 1


def test_action_cancelled_before_completion_is_never_cached(control):
    job = control.reserve('cancel-before-reply', opening(), 'runtime')
    class Pipe:
        calls = 0
        def request(self, observation):
            self.calls += 1
            control.close(job)
            return {'type': 'wait'}
        def close(self):
            pass
    job.pipe = Pipe()
    request = service.Observation(owner=OWNER, lease=LEASE, seq=0, observation={})
    for _ in range(2):
        with pytest.raises(service.InfrastructureError):
            control.request('cancel-before-reply', request)
    assert job.response is None and job.pipe.calls == 1
