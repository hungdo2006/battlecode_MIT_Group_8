import pytest

from backend.execution import RunnerUnavailable
from backend.sandbox_client import SandboxRunner


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.setenv('ARENA_RUNNER_TOKEN', 'unit-test-only-token-with-at-least-32-characters')
    return SandboxRunner()


def test_close_retries_infrastructure_failure_without_legacy_fallback(runner):
    def disconnected(*args, **kwargs):
        raise RunnerUnavailable('offline')
    runner.rpc = disconnected
    runner.close_job('r-cancelled')
    assert runner.pending_closes == {'r-cancelled'}
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
