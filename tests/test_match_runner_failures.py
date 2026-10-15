from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient

from backend.execution import LegacyRunner, RunnerUnavailable
from backend.main import create_app
from backend.runner import BotError
from workflow import official_match, player_client


@pytest.mark.parametrize('failure,stage,status,reason', [
    (BotError('invalid JSON'), 'request', 'completed', 'bot_error'),
    (RunnerUnavailable('controller down'), 'request', 'interrupted', 'runner_unavailable'),
    (RunnerUnavailable('Engine down'), 'start', 'interrupted', 'runner_unavailable'),
    (RuntimeError('unexpected transport failure'), 'request', 'interrupted', 'server_error'),
])
def test_infrastructure_never_becomes_player_forfeit(tmp_path, authorize_organizer, open_competition,
                                                   failure, stage, status, reason):
    class FailedSession:
        closed = False
        def start(self):
            if stage == 'start':
                raise failure
        def request(self, observation):
            raise failure
        def close(self):
            self.closed = True

    class FailedRunner(LegacyRunner):
        def __init__(self):
            super().__init__()
            self.sessions = []
        def session(self, bot, job_id):
            handle = FailedSession()
            self.sessions.append(handle)
            return handle

    with TestClient(create_app(tmp_path, tick_seconds=0)) as client:
        authorize_organizer(client)
        open_competition(client)
        player = player_client(client)
        bot = player.post('/api/games/robot_battle/samples/python/submit').json()
        runner = FailedRunner()
        client.app.state.manager.runner = runner
        match = official_match(client, {'bot_a': bot['id'], 'bot_b': bot['id']}).json()
        with client.websocket_connect('/ws/matches/' + match['id']) as socket:
            while (message := socket.receive_json())['type'] != 'complete':
                pass
        result = message['match']
        assert result['status'] == status
        assert result['result']['reason'] == reason
        assert result['result']['winner'] is None
        # MatchManager owns each handle before start; close also covers failed start.
        client.portal.call(client.app.state.manager.shutdown)
        assert runner.sessions and all(s.closed for s in runner.sessions)
