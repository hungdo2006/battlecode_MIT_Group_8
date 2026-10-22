"""Activity is bounded by idle/absolute TTL and cannot revive revoked sessions."""
import pytest

from test_auth_service import env, player, PASSWORD
from test_team_http import room, login, csrf
from backend.auth_service import AuthPolicy, SessionTTL, InvalidSession, PermissionDenied


@pytest.mark.parametrize('audience', ['PLAYER','ADMIN'])
def test_active_heartbeat_reaches_but_never_extends_absolute_expiry(env,audience):
    env.service.policy = AuthPolicy(player=SessionTTL(20,10),admin=SessionTTL(20,10))
    if audience == 'PLAYER':
        player(env)
    grant = env.service.login('alice' if audience=='PLAYER' else 'admin',PASSWORD,audience=audience,source_key='test')
    start = env.clock.now
    for elapsed in (3,6,9,12,15,18):
        env.clock.now = start+elapsed
        status = env.service.session_activity(grant.principal,touch=True)
        assert status['expires_at'] == grant.expires_at == start+20
        assert status['idle_expires_at'] == min(start+20,env.clock.now+10)
    env.clock.now = start+20
    with pytest.raises((InvalidSession,PermissionDenied)):
        env.service.session_activity(grant.principal,touch=True)


@pytest.mark.parametrize('ending', ['idle','revoked'])
def test_readonly_activity_and_revocation_cannot_renew_session(env,ending):
    env.service.policy = AuthPolicy(player=SessionTTL(100,10))
    player(env)
    grant = env.service.login('alice',PASSWORD,audience='PLAYER',source_key='test')
    start = env.clock.now
    for elapsed in (3,6,9):
        env.clock.now = start+elapsed
        assert env.service.session_activity(grant.principal)['idle_expires_at'] == start+10
    if ending == 'revoked':
        env.service.logout(grant.token,audience='PLAYER')
    else:
        env.clock.now = start+10
    with pytest.raises((InvalidSession,PermissionDenied)):
        env.service.session_activity(grant.principal,touch=True)


def test_heartbeat_http_csrf_cookie_and_passive_reads(room):
    login(room,'player','alice')
    initial = room.client.get('/api/player/auth/me').json()['session']
    headers = csrf(room,'player')
    room.clock.now += 3500
    assert room.client.get('/api/player/auth/me').json()['session']['idle_expires_at'] == initial['idle_expires_at']
    assert room.client.get('/api/player/team').status_code == 200
    assert room.client.post('/api/player/auth/heartbeat',json={}).status_code == 403
    response = room.client.post('/api/player/auth/heartbeat',json={},headers=headers)
    assert response.status_code == 200,response.text
    assert response.json()['idle_expires_at'] > initial['idle_expires_at']
    assert response.json()['expires_at'] == initial['expires_at']
    assert 'set-cookie' not in response.headers
    room.clock.now += 3600
    assert room.client.post('/api/player/auth/heartbeat',json={},headers=headers).status_code == 401


def test_heartbeat_throttles_writes_and_rejects_revoked_cookie(room):
    login(room,'admin','admin')
    headers = csrf(room,'admin')
    initial = room.client.get('/api/admin/auth/me').json()['session']
    room.clock.now += 5
    status = room.client.post('/api/admin/auth/heartbeat',json={},headers=headers).json()
    assert status['idle_expires_at'] == initial['idle_expires_at']
    runtime = room.app.state.account_http
    with runtime.database.writer_connection(runtime.writer) as db:
        db.execute("UPDATE auth_sessions SET revoked_at=created_at WHERE audience='ADMIN'")
    assert room.client.post('/api/admin/auth/heartbeat',json={},headers=headers).status_code == 401
