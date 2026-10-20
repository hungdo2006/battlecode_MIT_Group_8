"""Registration deadlines, Captain eligibility and atomic frozen season roster."""
from test_team_http import room,login,csrf
from test_team_tournament_http import create_active_team


def make_season(room,**changes):
    login(room,'admin','admin')
    now=room.clock.now
    payload={'name':'Season QA','game_id':'robot_battle','registration_opens_at':now-10,
             'registration_closes_at':now+100,'starts_at':now+200,'ends_at':now+1000,'max_teams':2}
    payload.update(changes)
    return room.client.post('/api/admin/seasons',json=payload,headers=csrf(room,'admin'))


def test_season_registration_deadline_capacity_roster_and_publication_gate(room):
    teams={name:create_active_team(room,name,'season-'+name) for name in ('alice','bob','charlie')}
    created=make_season(room)
    assert created.status_code==201,created.text
    season_id=created.json()['season']['id']
    for name in ('alice','bob'):
        login(room,'player',name)
        result=room.client.post(f'/api/player/seasons/{season_id}/register',json={},headers=csrf(room,'player'))
        assert result.status_code==200,result.text
        assert result.json()['season']['my_registration']
    login(room,'player','charlie')
    assert room.client.post(f'/api/player/seasons/{season_id}/register',json={},headers=csrf(room,'player')).status_code==409
    login(room,'admin','admin')
    headers=csrf(room,'admin')
    assert room.client.post(f'/api/admin/seasons/{season_id}/tournament',json={'format':'single_elimination'},headers=headers).status_code==409
    assert room.client.post(f'/api/admin/seasons/{season_id}/close-registration',json={},headers=headers).status_code==200
    frozen=room.client.post(f'/api/admin/seasons/{season_id}/tournament',json={'format':'single_elimination'},headers=headers)
    assert frozen.status_code==201,frozen.text
    tournament=frozen.json()['tournament']
    assert {team['team_id'] for team in tournament['teams']}=={teams['alice'],teams['bob']}
    assert frozen.json()['season']['tournament_id']==tournament['id']
    assert room.client.post(f'/api/admin/seasons/{season_id}/tournament',json={'format':'round_robin'},headers=headers).status_code==409
    assert room.client.post(f'/api/admin/seasons/{season_id}/publish',json={},headers=headers).status_code==409
    login(room,'player','alice')
    assert room.client.post(f'/api/player/seasons/{season_id}/withdraw',json={},headers=csrf(room,'player')).status_code==409
    seasons=room.client.get('/api/player/seasons').json()['seasons']
    assert seasons[0]['publication'] is None and seasons[0]['registered_teams']==2


def test_season_chronology_csrf_and_captain_permissions(room):
    assert make_season(room,ends_at=room.clock.now-1).status_code==422
    created=make_season(room)
    assert created.status_code==201
    season_id=created.json()['season']['id']
    login(room,'player','alice')
    assert room.client.post(f'/api/player/seasons/{season_id}/register',json={}).status_code==403
    assert room.client.post(f'/api/player/seasons/{season_id}/register',json={},headers=csrf(room,'player')).status_code==403
    assert room.client.post('/api/admin/seasons',json={},headers=csrf(room,'player')).status_code in (401,403)
