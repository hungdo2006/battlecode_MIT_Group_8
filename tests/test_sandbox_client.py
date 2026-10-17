import pytest

from backend.execution import RunnerUnavailable
from backend.sandbox_client import ControllerRejected, SandboxRunner


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.setenv('ARENA_RUNNER_TOKEN', 'unit-test-only-token-with-at-least-32-characters')
    runner = SandboxRunner()
    runner.epoch, runner.lease = 'e' * 32, 'f' * 32
    return runner


def test_close_retries_infrastructure_failure_without_legacy_fallback(runner):
    def disconnected(*args, **kwargs):
        raise RunnerUnavailable('offline')
    runner.rpc = disconnected
    runner.close_job('r-cancelled')
    assert runner.pending_closes == {'r-cancelled': runner.lease}
    runner.rpc = lambda *args, **kwargs: {'closed': True}
    runner.close_job('r-cancelled')
    assert not runner.pending_closes


def test_ambiguous_request_not_resent_and_not_a_bot_fault(runner):
    session = runner.session({'execution_backend': 'sandbox', 'artifact_id': 'artifact',
                              'artifact_digest': 'a' * 64}, 'r-test')
    calls = []
    def lost_response(path, payload, **kwargs):
        calls.append((path, payload))
        raise RunnerUnavailable('response lost')
    runner.rpc = lost_response
    with pytest.raises(RunnerUnavailable):
        session.request({'turn': 0})
    assert len(calls) == 1 and session.seq == 0


def test_cancelled_remote_handle_never_starts(runner):
    calls = []
    runner.rpc = lambda *args, **kwargs: calls.append(args) or {'closed': True}
    session = runner.session({'execution_backend': 'sandbox', 'artifact_id': 'artifact',
                              'artifact_digest': 'b' * 64}, 'r-cancelled')
    session.close()
    with pytest.raises(RunnerUnavailable, match='cancelled'):
        session.start()
    assert all('/runtime/' not in call[0] for call in calls)


def test_controller_url_cannot_redirect_token_to_public_host(monkeypatch):
    monkeypatch.setenv('ARENA_CONTROLLER_URL', 'http://example.com:9000')
    with pytest.raises(ValueError, match='private Compose network'):
        SandboxRunner()


def test_same_epoch_rejection_never_reclaims_live_or_expired_lease(runner):
    calls = []
    def rpc(path, *args, **kwargs):
        calls.append(path)
        if path == '/heartbeat':
            raise ControllerRejected(409)
        return {'epoch': runner.epoch}
    runner.rpc = rpc
    with pytest.raises(ControllerRejected):
        runner.heartbeat_once()
    assert calls == ['/heartbeat', '/health']


def test_controller_restart_fences_old_sessions_and_cleanup(runner):
    session = runner.session({'execution_backend': 'sandbox', 'artifact_id': 'artifact',
                              'artifact_digest': 'a' * 64}, 'old-runtime')
    old_lease = session.lease
    calls = []
    def rpc(path, payload=None, **kwargs):
        calls.append((path, kwargs.get('lease')))
        if path == '/heartbeat':
            raise ControllerRejected(409)
        if path == '/health':
            return {'epoch': '1' * 32}
        if path == '/owner':
            return {'epoch': '1' * 32, 'lease': '2' * 32}
        if path.startswith('/close/'):
            raise ControllerRejected(409)
        raise ControllerRejected(409)
    runner.rpc = rpc
    runner.heartbeat_once()
    assert runner.lease == '2' * 32 and runner.available
    with pytest.raises(ControllerRejected):
        session.request({'turn': 1})
    session.close()
    assert calls[-2:] == [('/runtime/old-runtime/request', old_lease), ('/close/old-runtime', old_lease)]
    assert not runner.pending_closes
