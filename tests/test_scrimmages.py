"""Queue authority, frozen artifacts, CSRF, opponent privacy and recovery."""
import asyncio
import json
import pytest

from test_team_http import room,login,csrf
from test_official_schedule import create_team,seed_ready_bot,select_bot
from backend.scrimmage_service import Scrimmages


@pytest.fixture(autouse=True)
def pause_worker(room):
    async def stop():
        room.app.state.official_deadline_task.cancel()
        await asyncio.gather(room.app.state.official_deadline_task,return_exceptions=True)
    room.client.portal.call(stop)


def prepared(room,monkeypatch):
    monkeypatch.setattr(room.app.state.runner,'mode','sandbox')
    teams={}
    for username,bot_id in (('alice','a'*16),('bob','b'*16),('charlie','c'*16)):
        teams[username]=create_team(room,username,'practice-'+username)
        seed_ready_bot(room,teams[username],username,bot_id)
        bot=room.app.state.store.get_bot(bot_id)
        bot.update(execution_backend='sandbox',artifact_id='artifact-'+username,artifact_digest=bot_id*4)
        room.app.state.store.save_bot(bot)
        select_bot(room,username,bot_id)
    login(room,'player','alice')
    return teams


def create(room,opponent):
    return room.client.post('/api/player/scrimmages',json={'game_id':'robot_battle','opponent_team_id':opponent},headers=csrf(room,'player'))


def test_scrimmage_private_queue_csrf_and_cancellation(room,monkeypatch):
    teams=prepared(room,monkeypatch)
    opponents=room.client.get('/api/player/scrimmage-opponents?game_id=robot_battle')
    assert opponents.status_code==200,opponents.text
    assert {team['id'] for team in opponents.json()['teams']}=={teams['bob'],teams['charlie']}
    assert 'artifact' not in opponents.text and 'source' not in opponents.text
    assert room.client.post('/api/player/scrimmages',json={'game_id':'robot_battle','opponent_team_id':teams['bob']}).status_code==403
    response=create(room,teams['bob'])
    assert response.status_code==201,response.text
    request=response.json()['request']; request_id=request['id']
    assert request['status']=='QUEUED' and 'artifact' not in response.text
    assert create(room,teams['bob']).status_code==409
    assert create(room,teams['alice']).status_code==422
    assert room.client.get(f'/api/player/scrimmages/{request_id}/replay').status_code==409
    login(room,'player','charlie')
    assert room.client.get('/api/player/scrimmages').json()['requests']==[]
    assert room.client.get(f'/api/player/scrimmages/{request_id}').status_code==404
    assert room.client.get(f'/api/player/scrimmages/{request_id}/replay').status_code==404
    login(room,'player','bob')
    assert room.client.get('/api/player/scrimmages').json()['requests'][0]['id']==request_id
    assert room.client.post(f'/api/player/scrimmages/{request_id}/cancel',json={},headers=csrf(room,'player')).status_code==403
    login(room,'player','alice')
    cancelled=room.client.post(f'/api/player/scrimmages/{request_id}/cancel',json={},headers=csrf(room,'player'))
    assert cancelled.status_code==200 and cancelled.json()['request']['status']=='CANCELLED'
    assert room.client.post(f'/api/player/scrimmages/{request_id}/cancel',json={},headers=csrf(room,'player')).status_code==409


def test_scrimmage_freezes_rules_and_never_restarts_uncertain_execution(room,monkeypatch):
    teams=prepared(room,monkeypatch)
    request=create(room,teams['bob']).json()['request']
    runtime=room.app.state.account_http
    def operation(auth,db):
        service=Scrimmages(auth,db,runtime.writer,room.app.state.store,room.app.state.registry)
        plan=service.claim()
        assert plan['id']==request['id']
        assert plan['slots']['A']['bot_id']=='a'*16
        assert plan['slots']['B']['artifact_digest']=='b'*64
        assert plan['rules_snapshot']==request['rules']
        assert service.claim() is None
        service.reconcile(room.app.state.manager,recover=True)
        assert service.claim() is None
        row=db.execute('SELECT * FROM scrimmage_requests WHERE id=?',(request['id'],)).fetchone()
        assert row['status']=='INTERRUPTED' and row['status_reason']=='UNCERTAIN_EXECUTION'
        assert row['outcome_json'] is None
    room.client.portal.call(runtime.run,operation)
    assert room.app.state.store.get_standings()==[]


def test_scrimmage_rejects_unattested_source_and_native_execution(room,monkeypatch):
    teams=prepared(room,monkeypatch)
    (room.app.state.store.uploads/('b'*16)/'bot.py').write_bytes(b'changed after attestation')
    assert create(room,teams['bob']).status_code==409
    monkeypatch.setattr(room.app.state.runner,'mode','legacy')
    assert create(room,teams['bob']).status_code==503
