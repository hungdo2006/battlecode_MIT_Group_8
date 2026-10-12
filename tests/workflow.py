"""Regression setup uses the real v3 invitation APIs, not direct match creation.

Older engine/replay tests may provide two submissions of one owner. A second
independent Player submits the same source so the official flow has two people.
"""
import os
from contextlib import ExitStack
from pathlib import Path

from fastapi.testclient import TestClient


def player_client(client):
    if client.get('/api/session').json()['role'] == 'player':
        return client
    if not hasattr(client, '_submission_player'):
        other = TestClient(client.app, base_url=str(client.base_url))
        other.portal = client.portal
        other.get('/api/session')
        client._submission_player = other
        client.app.state._regression_clients = getattr(client.app.state, '_regression_clients', []) + [other]
    return client._submission_player


def organizer_client(client):
    if client.get('/api/session').json()['role'] == 'organizer':
        return client
    other = getattr(client.app.state, '_regression_organizer', None)
    if other:
        return other
    other = TestClient(client.app, base_url=str(client.base_url)); other.portal = client.portal
    assert other.post('/api/session/organizer', json={'code': os.environ['ARENA_ADMIN_CODE']}).status_code == 200
    client.app.state._regression_organizer = other
    return other


def official_match(client, payload):
    if payload.get('rules') is not None:
        return client.post('/api/matches', json=payload)
    organizer = organizer_client(client)
    if payload.get('game_id', payload.get('game', organizer.app.state.store.selected_game_id)) != organizer.app.state.store.selected_game_id:
        return client.post('/api/matches', json=payload)
    peers = []
    for bot_id in (payload['bot_a'], payload['bot_b']):
        bot = client.app.state.store.get_bot(bot_id)
        candidates = [client, *getattr(client.app.state, '_regression_clients', [])]
        peer = next((c for c in candidates if c not in peers
                     and c.get('/api/session').json()['role'] == 'player'
                     and bot and c.get('/api/session').json()['participant']['id'] == (bot.get('owner') or {}).get('id')), None)
        if peer is None:
            peer = TestClient(client.app, base_url=str(client.base_url)); peer.portal = client.portal
            peer.get('/api/session')
            client.app.state._regression_clients = getattr(client.app.state, '_regression_clients', []) + [peer]
            if bot:
                source = (Path(bot['folder']) / ('Main.java' if bot['language'] == 'java' else 'bot.' + bot['language'])).read_bytes()
                response = peer.post('/api/bots', files={'file': (bot['filename'], source)},
                                     data={'game_id': bot['game_id'], 'name': bot['name']})
                if response.status_code != 201: return response
                bot_id = response.json()['id']
        response = peer.put('/api/players/active-bot', json={'bot_id': bot_id})
        if response.status_code != 200: return response
        peers.append(peer)
    with ExitStack() as stack:
        for peer in peers:
            endpoint = str(peer.base_url).replace('http://', 'ws://').replace('https://', 'wss://').rstrip('/') + '/ws/competition'
            stack.enter_context(peer.websocket_connect(endpoint)).receive_json()
        response = organizer.post('/api/invitations', json={
            'player_a_id': peers[0].get('/api/players/me').json()['player_id'],
            'player_b_id': peers[1].get('/api/players/me').json()['player_id']})
        if response.status_code != 201: return response
        path = f"/api/invitations/{response.json()['id']}/accept"
        response = peers[0].post(path)
        if response.status_code != 200: return response
        response = peers[1].post(path)
        if response.status_code != 200: return response
        if not response.json().get('match_id'): return response
        return client.get(f"/api/matches/{response.json()['match_id']}")
