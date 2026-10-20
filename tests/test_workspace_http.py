"""Profile identity, Admin controls, session invalidation and safe monitoring."""
from test_team_http import room,login,csrf


def test_player_profile_cannot_change_role_or_username(room):
    login(room,'player','alice')
    assert room.client.patch('/api/player/profile',json={'display_name':'New name'}).status_code==403
    headers=csrf(room,'player')
    assert room.client.patch('/api/player/profile',json={'display_name':'New name','system_role':'ADMIN'},headers=headers).status_code==422
    response=room.client.patch('/api/player/profile',json={'display_name':'Nguyễn Minh Anh'},headers=headers)
    assert response.status_code==200,response.text
    assert response.json()['account']['username']=='alice'
    assert response.json()['account']['system_role']=='PLAYER'
    assert response.json()['account']['display_name']=='Nguyễn Minh Anh'
    assert room.client.get('/api/player/auth/me').json()['account']['display_name']=='Nguyễn Minh Anh'
    assert room.client.get('/api/admin/accounts').status_code in (401,403)


def test_admin_disable_enable_never_resurrects_old_player_session(room):
    login(room,'player','alice')
    player_id=room.client.get('/api/player/auth/me').json()['account']['id']
    login(room,'admin','admin')
    accounts=room.client.get('/api/admin/accounts?search=alice')
    assert accounts.status_code==200
    assert accounts.json()['total']==1
    assert 'password_hash' not in accounts.text and 'auth_version' not in accounts.text
    headers=csrf(room,'admin')
    assert room.client.post(f'/api/admin/accounts/{player_id}/disable',json={},headers=headers).json()['disabled']
    assert room.client.get('/api/player/auth/me').status_code==401
    assert room.client.post(f'/api/admin/accounts/{player_id}/enable',json={},headers=headers).json()['enabled']
    assert room.client.get('/api/player/auth/me').status_code==401
    login(room,'player','alice')
    assert room.client.get('/api/player/auth/me').status_code==200
    admin_id=next(account['id'] for account in room.client.get('/api/admin/accounts').json()['accounts'] if account['system_role']=='ADMIN')
    assert room.client.post(f'/api/admin/accounts/{admin_id}/disable',json={},headers=csrf(room,'admin')).status_code==409


def test_system_status_is_admin_only_and_omits_runtime_secrets(room):
    assert room.client.get('/api/admin/system').status_code==401
    login(room,'player','alice')
    assert room.client.get('/api/admin/system').status_code in (401,403)
    login(room,'admin','admin')
    response=room.client.get('/api/admin/system')
    assert response.status_code==200,response.text
    payload=response.json()
    assert payload['capacity']==2 and payload['active_matches']==[]
    assert all(isinstance(available,bool) for available in payload['runner']['toolchains'].values())
    assert 'command' not in response.text and 'token' not in response.text and 'password' not in response.text
