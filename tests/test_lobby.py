"""Real HTTP/cookie/WebSocket invitation workflow, no fake match runner."""
import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app

WAIT = b"import sys,json\nfor line in sys.stdin:\n print(json.dumps({'type':'wait'}),flush=True)\n"


@pytest.fixture
def clients(tmp_path, authorize_organizer):
    with TestClient(create_app(tmp_path, tick_seconds=0.02)) as org:
        authorize_organizer(org)
        others = [TestClient(org.app) for _ in range(3)]
        for client in others:
            client.portal = org.portal
            client.get('/api/session')
        with ExitStack() as stack:
            sockets = [stack.enter_context(c.websocket_connect('/ws/competition')) for c in [org, *others]]
            yield org, *others, sockets
        for client in others:
            client.close()


def ready(client, game='robot_battle', language=None):
    response = (client.post(f'/api/games/{game}/samples/{language}/submit') if language else
                client.post('/api/bots', files={'file': ('wait.py', WAIT)}, data={'game_id': game}))
    assert response.status_code == 201, response.text
    bot = response.json()
    assert bot['status'] == 'ready', bot['logs']
    response = client.put('/api/players/active-bot', json={'bot_id': bot['id']})
    assert response.status_code == 200, response.text
    return bot


def invite(org, a, b):
    response = org.post('/api/invitations', json={
        'player_a_id': a.get('/api/players/me').json()['player_id'],
        'player_b_id': b.get('/api/players/me').json()['player_id']})
    assert response.status_code == 201, response.text
    return response.json()


def watch(client, match_id):
    frames = []
    with client.websocket_connect(f'/ws/matches/{match_id}') as ws:
        while True:
            item = ws.receive_json()
            if item['type'] == 'state':
                assert item['seq'] == len(frames)
                frames.append(item['state'])
            if item['type'] == 'complete':
                return frames, item['match']


def until(ws, predicate):
    for _ in range(100):
        message = ws.receive_json()
        if message['type'] == 'competition' and predicate(message):
            return message
    raise AssertionError('Lobby update missing')


def test_roles_block_upload_samples_pairing_bypass_and_impersonation(clients, open_competition):
    org, a, b, stranger, sockets = clients
    assert org.post('/api/bots', files={'file': ('wait.py', WAIT)}, data={'game_id': 'robot_battle'}).status_code == 403
    for route in ('/api/samples/python/submit', '/api/games/robot_battle/samples/python/submit'):
        assert org.post(route).status_code == 403
    assert org.put('/api/players/active-bot', json={'bot_id': 'any'}).status_code == 403
    assert a.put('/api/rules', json={'max_turns': 2}).status_code == 403
    assert a.post('/api/invitations', json={'player_a_id': 'a', 'player_b_id': 'b'}).status_code == 403
    ready(a); ready(b)
    open_competition(org, rules={'max_turns': 4})
    inv = invite(org, a, b)
    assert stranger.get('/api/invitations').json() == []
    assert stranger.post(f"/api/invitations/{inv['id']}/accept").status_code == 403
    assert a.post(f"/api/invitations/{inv['id']}/accept", json={'player_id': inv['player_ids'][1]}).status_code == 422
    assert a.post(f"/api/invitations/{inv['id']}/cancel").status_code == 403
    for client in (org, a, b):
        assert client.post('/api/matches', json={'bot_a': 'x', 'bot_b': 'x'}).status_code == 403
    assert org.get('/api/matches').json() == []


@pytest.mark.parametrize('first', [0, 1])
def test_one_accept_does_not_start_and_two_accept_auto_start_three_streams(clients, open_competition, first):
    org, a, b, _, sockets = clients
    a.put('/api/session', json={'name': 'Hoang'})
    b.put('/api/session', json={'name': 'Minh'})
    bots = [ready(a), ready(b)]
    snapshot = open_competition(org, rules={'max_turns': 5})['active_rules_snapshot']
    inv = invite(org, a, b)
    people = [a, b]
    path = f"/api/invitations/{inv['id']}/accept"
    assert people[first].post(path).json()['status'] == 'PARTIALLY_ACCEPTED'
    assert org.get('/api/matches').json() == []
    assert people[first].put('/api/players/active-bot', json={'bot_id': bots[first]['id']}).status_code == 409
    assert people[first].post('/api/session/organizer', json={'code': 'neon-test-organizer-code'}).status_code == 409
    started = people[1-first].post(path).json()
    assert started['status'] == 'STARTED'
    match_id = started['match_id']
    for ws in sockets[:3]:
        update = until(ws, lambda m: any(i['id'] == inv['id'] and i['status'] == 'STARTED' for i in m['lobby']['invitations']))
        assert update['lobby']['invitations'][0]['match_id'] == match_id
    streams = [watch(client, match_id) for client in (org, a, b)]
    assert streams[0] == streams[1] == streams[2]
    frames, match = streams[0]
    assert match['rules_snapshot'] == snapshot
    assert match['player_a_name_snapshot'] == 'Hoang' and match['player_b_name_snapshot'] == 'Minh'
    assert match['player_a_id'] != match['player_b_id']
    assert match['bot_a_id'] == bots[0]['id'] and match['bot_b_id'] == bots[1]['id']
    assert org.get(f'/api/matches/{match_id}/replay').json()['frames'] == frames
    a.put('/api/session', json={'name': 'Changed later'})
    assert org.get(f'/api/matches/{match_id}').json()['player_a_name_snapshot'] == 'Hoang'
    until(sockets[0], lambda m: any(i.get('finished') for i in m['lobby']['invitations']))
    assert a.get('/api/players/me').json()['status'] == 'READY'
    assert b.get('/api/players/me').json()['status'] == 'READY'
    assert a.post(path).json()['match_id'] == match_id
    assert len(org.get('/api/matches').json()) == 1
    assert invite(org, a, b)['id'] != inv['id']


def test_simultaneous_and_repeated_accept_create_exactly_one_match(clients, open_competition):
    org, a, b, _, _ = clients
    ready(a); ready(b)
    open_competition(org, rules={'max_turns': 3})
    inv = invite(org, a, b)
    path = f"/api/invitations/{inv['id']}/accept"
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda c: c.post(path), (a, b, a, b)))
    assert all(r.status_code == 200 for r in responses)
    assert len(org.get('/api/matches').json()) == 1
    ids = {r.json()['match_id'] for r in responses if r.json()['match_id']}
    assert len(ids) == 1
    watch(org, ids.pop())


@pytest.mark.parametrize('ending', ['decline', 'cancel', 'expiry', 'close'])
def test_invitation_terminal_cases_release_players_and_never_start(clients, open_competition, ending):
    org, a, b, _, sockets = clients
    ready(a); ready(b)
    open_competition(org)
    if ending == 'expiry':
        org.app.state.lobby.invitation_seconds = 0.1
    inv = invite(org, a, b)
    a.post(f"/api/invitations/{inv['id']}/accept")
    if ending == 'decline':
        assert b.post(f"/api/invitations/{inv['id']}/decline").json()['status'] == 'DECLINED'
    elif ending == 'cancel':
        assert org.post(f"/api/invitations/{inv['id']}/cancel").json()['status'] == 'CANCELLED'
    elif ending == 'close':
        assert org.post('/api/competition/close').status_code == 200
    else:
        until(sockets[0], lambda m: any(i['status'] == 'EXPIRED' for i in m['lobby']['invitations']))
    assert b.post(f"/api/invitations/{inv['id']}/accept").status_code == 409
    assert org.get('/api/matches').json() == []
    assert a.get('/api/players/me').json()['status'] == 'READY'
    assert a.put('/api/players/active-bot', json={'bot_id': a.get('/api/players/me').json()['active_bot_id']}).status_code == 200


def test_pairing_checks_owner_ready_duplicate_and_busy(clients, open_competition):
    org, a, b, other, _ = clients
    bot = ready(a)
    assert b.put('/api/players/active-bot', json={'bot_id': bot['id']}).status_code == 403
    ids = [c.get('/api/players/me').json()['player_id'] for c in (a, b, other)]
    payload = {'player_a_id': ids[0], 'player_b_id': ids[1]}
    assert org.post('/api/invitations', json=payload).status_code == 409  # closed
    open_competition(org, rules={'max_turns': 30})
    assert org.post('/api/invitations', json=payload).status_code == 409  # no active B
    ready(b); ready(other)
    assert org.post('/api/invitations', json={**payload, 'player_b_id': ids[0]}).status_code == 409
    assert org.post('/api/invitations', json={**payload, 'player_b_id': 'missing'}).status_code == 409
    inv = invite(org, a, b)
    assert org.post('/api/invitations', json={**payload, 'player_b_id': ids[2]}).status_code == 409
    for c in (a, b): c.post(f"/api/invitations/{inv['id']}/accept")
    assert org.post('/api/invitations', json=payload).status_code == 409
    assert a.put('/api/players/active-bot', json={'bot_id': bot['id']}).status_code == 409
    assert org.post('/api/competition/close').json()['phase'] == 'draining'
    assert org.put('/api/games/selected', json={'game_id': 'ott_v2'}).status_code == 409
    assert org.post(f"/api/matches/{inv['id']}/cancel").status_code == 404
    match_id = org.get('/api/invitations').json()[0]['match_id']
    assert org.post(f'/api/matches/{match_id}/cancel').status_code == 200
    assert a.get('/api/players/me').json()['status'] == 'READY'
    assert org.put('/api/games/selected', json={'game_id': 'ott_v2'}).status_code == 200
    assert a.get('/api/players/me').json()['status'] == 'ONLINE'  # incompatible active hidden
    assert a.put('/api/players/active-bot', json={'bot_id': bot['id']}).status_code == 409


def test_presence_multitab_heartbeat_reconnect_pending_and_running(clients, open_competition):
    org, a, b, _, sockets = clients
    bot = ready(a); ready(b)
    a.put('/api/session', json={'name': 'Duplicate'})
    b.put('/api/session', json={'name': 'Duplicate'})
    roster = org.get('/api/players').json()
    duplicates = [p for p in roster if p['nickname'] == 'Duplicate']
    assert len(duplicates) == 2 and duplicates[0]['display_name'] != duplicates[1]['display_name']
    with a.websocket_connect('/ws/competition') as extra:
        extra.receive_json()
        assert a.get('/api/players/me').json()['online']
    assert a.get('/api/players/me').json()['status'] == 'READY'  # original tab remains
    open_competition(org, rules={'max_turns': 25})
    inv = invite(org, a, b)
    sockets[1].close()
    until(sockets[0], lambda m: any(p['player_id'] == bot['owner']['id'] and not p['online'] for p in m['lobby']['players']))
    with a.websocket_connect('/ws/competition') as restored:
        restored.receive_json()
        assert a.get('/api/invitations').json()[0]['responses'][bot['owner']['id']] == 'PENDING'
        a.post(f"/api/invitations/{inv['id']}/accept")
        match_id = b.post(f"/api/invitations/{inv['id']}/accept").json()['match_id']
    until(sockets[0], lambda m: any(p['player_id'] == bot['owner']['id'] and not p['online'] for p in m['lobby']['players']))
    with a.websocket_connect('/ws/competition') as restored:
        initial = restored.receive_json()
        assert initial['lobby']['me']['current_match_id'] == match_id
        restored.send_json({'type': 'heartbeat'})
        assert watch(a, match_id)[1]['status'] == 'completed'
    assert a.get('/api/players/me').json()['status'] == 'OFFLINE'


def test_restart_cancels_pending_keeps_active_and_old_replay(clients, tmp_path, authorize_organizer, open_competition):
    org, a, b, _, _ = clients
    ba = ready(a); ready(b)
    cookie = a.cookies.get('arena_session')
    open_competition(org, rules={'max_turns': 2})
    inv = invite(org, a, b)
    a.post(f"/api/invitations/{inv['id']}/accept")
    mid = b.post(f"/api/invitations/{inv['id']}/accept").json()['match_id']
    frames, _ = watch(org, mid)
    pending = invite(org, a, b)
    a.post(f"/api/invitations/{pending['id']}/accept")
    with TestClient(create_app(tmp_path)) as restarted:
        restarted.cookies.set('arena_session', cookie)
        me = restarted.get('/api/players/me').json()
        assert me['status'] == 'OFFLINE' and me['active_bot_id'] == ba['id']
        invitations = restarted.get('/api/invitations').json()
        assert invitations[0]['status'] == 'CANCELLED' and invitations[0]['reason'] == 'server_restart'
        assert restarted.post(f"/api/invitations/{pending['id']}/accept").status_code == 409
        assert len(restarted.get('/api/matches').json()) == 1
        authorize_organizer(restarted)
        restarted.post('/api/competition/close')
        restarted.put('/api/games/selected', json={'game_id': 'ott_v2'})
        assert restarted.get(f'/api/matches/{mid}/replay').json()['frames'] == frames


@pytest.mark.parametrize('game,langs', [('robot_battle', ('cpp', 'python')), ('robot_battle', ('java', 'cpp')),
                                      ('ott_v2', ('python', 'cpp')), ('ott_v2', ('java', 'python'))])
def test_invited_multilanguage_games(clients, open_competition, game, langs):
    org, a, b, _, _ = clients
    open_competition(org, game)
    ready(a, game, langs[0]); ready(b, game, langs[1])
    inv = invite(org, a, b)
    a.post(f"/api/invitations/{inv['id']}/accept")
    mid = b.post(f"/api/invitations/{inv['id']}/accept").json()['match_id']
    frames, match = watch(org, mid)
    assert match['status'] == 'completed' and match['result']['reason'] != 'bot_error'
    assert match['bot_a_language'] == {'python': 'py'}.get(langs[0], langs[0])
    assert all(f['game_id'] == game for f in frames)


def test_unaccepted_active_bot_change_updates_invitation_then_freezes(clients, open_competition):
    org, a, b, _, _ = clients
    first = ready(a); ready(b)
    open_competition(org, rules={'max_turns': 2})
    inv = invite(org, a, b)
    replacement = ready(a)
    assert replacement['id'] != first['id']
    current = a.get('/api/invitations').json()[0]
    assert current['bots'][first['owner']['id']]['id'] == replacement['id']
    a.post(f"/api/invitations/{inv['id']}/accept")
    assert a.put('/api/players/active-bot', json={'bot_id': first['id']}).status_code == 409
    mid = b.post(f"/api/invitations/{inv['id']}/accept").json()['match_id']
    assert watch(org, mid)[1]['bot_a_id'] == replacement['id']


def test_heartbeat_timeout_counts_offline_and_recovers_without_accept(clients, open_competition):
    org, a, b, _, sockets = clients
    ready(a); ready(b)
    open_competition(org)
    inv = invite(org, a, b)
    lobby = org.app.state.lobby
    pid = a.get('/api/players/me').json()['player_id']
    async def lose_heartbeat():
        async with org.app.state.competition.lock:
            for cid in lobby.connections[pid]:
                lobby.connections[pid][cid] = time.monotonic() - 40
            lobby.wakeup.set()
    org.portal.call(lose_heartbeat)
    until(sockets[0], lambda m: any(p['player_id'] == pid and not p['online'] for p in m['lobby']['players']))
    assert a.get('/api/players/me').json()['status'] == 'OFFLINE'
    assert a.post(f"/api/invitations/{inv['id']}/accept").status_code == 409
    sockets[1].send_json({'type': 'heartbeat'})
    until(sockets[0], lambda m: any(p['player_id'] == pid and p['online'] for p in m['lobby']['players']))
    assert a.get('/api/invitations').json()[0]['responses'][pid] == 'PENDING'


def test_second_accept_revalidates_offline_opponent_and_cancels(clients, open_competition):
    org, a, b, _, sockets = clients
    ready(a); ready(b)
    open_competition(org)
    inv = invite(org, a, b)
    a.post(f"/api/invitations/{inv['id']}/accept")
    sockets[1].close()
    pid = a.get('/api/players/me').json()['player_id']
    until(sockets[0], lambda m: any(p['player_id'] == pid and not p['online'] for p in m['lobby']['players']))
    response = b.post(f"/api/invitations/{inv['id']}/accept")
    assert response.json()['status'] == 'CANCELLED' and response.json()['reason'] == 'player_unavailable'
    assert org.get('/api/matches').json() == []
    assert b.get('/api/players/me').json()['status'] == 'READY'


def test_start_failure_and_engine_infrastructure_error_release_reservations(clients, open_competition, monkeypatch):
    org, a, b, _, sockets = clients
    ready(a); ready(b)
    open_competition(org)
    manager = org.app.state.manager
    original = manager.start
    async def failure(*args, **kwargs):
        raise ValueError('No more match slots')
    monkeypatch.setattr(manager, 'start', failure)
    inv = invite(org, a, b)
    a.post(f"/api/invitations/{inv['id']}/accept")
    assert b.post(f"/api/invitations/{inv['id']}/accept").status_code == 409
    assert a.get('/api/players/me').json()['status'] == 'READY'
    assert org.get('/api/invitations').json()[0]['status'] == 'CANCELLED'
    monkeypatch.setattr(manager, 'start', original)
    def fail_frame(*args):
        raise OSError('Test disk full')
    monkeypatch.setattr(org.app.state.store, 'append_replay_frame', fail_frame)
    inv = invite(org, a, b)
    a.post(f"/api/invitations/{inv['id']}/accept")
    mid = b.post(f"/api/invitations/{inv['id']}/accept").json()['match_id']
    frames, match = watch(org, mid)
    assert match['status'] == 'interrupted' and len(frames) == 1
    until(sockets[0], lambda m: any(i['id'] == inv['id'] and i.get('finished') for i in m['lobby']['invitations']))
    assert a.get('/api/players/me').json()['status'] == 'READY'


def test_role_promotion_during_compile_cannot_commit_organizer_bot(clients, monkeypatch):
    import threading
    import backend.main as main
    org, a, _, _, _ = clients
    began, release = threading.Event(), threading.Event()
    original = main.prepare_submission
    def slow(*args):
        result = original(*args)
        began.set()
        assert release.wait(5)
        return result
    monkeypatch.setattr(main, 'prepare_submission', slow)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(a.post, '/api/bots', files={'file': ('wait.py', WAIT)}, data={'game_id': 'robot_battle'})
        assert began.wait(5)
        assert a.post('/api/session/organizer', json={'code': 'neon-test-organizer-code'}).status_code == 200
        release.set()
        assert future.result().status_code == 403
    assert org.get('/api/bots').json() == []


def test_invitation_write_failure_after_start_cannot_create_second_match(clients, monkeypatch, open_competition, tmp_path):
    org, a, b, _, _ = clients
    ready(a); ready(b)
    open_competition(org, rules={'max_turns': 30})
    inv = invite(org, a, b)
    path = f"/api/invitations/{inv['id']}/accept"
    assert a.post(path).status_code == 200
    lobby = org.app.state.lobby
    save = lobby.save_invitation
    failed = False
    def once(record):
        nonlocal failed
        if record['status'] == 'STARTED' and not failed:
            failed = True
            raise OSError('Test invitation write failed')
        save(record)
    monkeypatch.setattr(lobby, 'save_invitation', once)
    with pytest.raises(OSError):
        b.post(path)
    matches = org.get('/api/matches').json()
    assert len(matches) == 1
    assert b.post(path).json()['match_id'] == matches[0]['id']
    assert len(org.get('/api/matches').json()) == 1
    with TestClient(create_app(tmp_path)) as restarted:
        restarted.cookies.set('arena_session', b.cookies.get('arena_session'))
        assert restarted.get('/api/invitations').json()[0]['match_id'] == matches[0]['id']
        assert restarted.post(path).json()['match_id'] == matches[0]['id']
        assert len(restarted.get('/api/matches').json()) == 1
