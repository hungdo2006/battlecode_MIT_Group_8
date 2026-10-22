"""Capacity, archive authority and opt-in matchmaking with disposable datasets."""
import asyncio
import base64
import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from test_team_http import room, login, csrf
from test_official_schedule import create_team, seed_ready_bot, select_bot
from test_scrimmages import prepared, pause_worker
from backend.auth_http import account_cookie_name
from backend.auth_limits import AuthRateLimiter
from backend.auth_service import AuthService
from backend.team_service import TeamService, TeamConflict
from backend.matchmaking_service import Matchmaking


def principal(room, username):
    login(room, 'player', username)
    token = room.client.cookies[account_cookie_name('PLAYER')]
    return room.client.portal.call(room.app.state.account_http.run,
                                  lambda auth,db:auth.validate_session(token,audience='PLAYER',touch=False))


def test_capacity_admin_validation_and_two_simultaneous_accepts(room):
    login(room,'admin','admin')
    assert room.client.get('/api/admin/team-policy').json()['max_members'] == 5
    for invalid in (1,21,True,'5',2.5):
        assert room.client.put('/api/admin/team-policy',json={'max_members':invalid},headers=csrf(room,'admin')).status_code == 422
    assert room.client.put('/api/admin/team-policy',json={'max_members':2}).status_code == 403
    assert room.client.put('/api/admin/team-policy',json={'max_members':2},headers=csrf(room,'admin')).status_code == 200
    tid = create_team(room,'alice','capacity-race')
    headers = csrf(room,'player')
    invitations = []
    for username in ('bob','charlie'):
        response = room.client.post(f'/api/player/teams/{tid}/invitations',json={'username':username},headers=headers)
        assert response.status_code == 201, response.text
        invitations.append(response.json()['invitation']['id'])
    actors = [principal(room,name) for name in ('bob','charlie')]
    runtime = room.app.state.account_http
    barrier = threading.Barrier(2)

    def accept(index):
        with runtime.database.writer_connection(runtime.writer) as db:
            auth = AuthService(db,runtime.writer,clock=room.clock,login_limiter=AuthRateLimiter())
            service = TeamService(db,runtime.writer,auth_service=auth,clock=room.clock)
            barrier.wait(timeout=5)
            try:
                service.accept_invitation(actors[index],invitations[index])
                return 'accepted'
            except TeamConflict:
                return 'full'
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(accept,i) for i in range(2)]
        assert sorted(f.result(timeout=10) for f in futures) == ['accepted','full']
    login(room,'player','alice')
    team = room.client.get('/api/player/team').json()['team']
    assert team['member_count'] == team['max_members'] == 2
    assert room.client.post(f'/api/player/teams/{tid}/invitations',json={'username':'charlie'},headers=csrf(room,'player')).status_code == 409
    assert room.client.put('/api/admin/team-policy',json={'max_members':20},headers=csrf(room,'player')).status_code in (401,403)


def test_lower_capacity_preserves_existing_members(room):
    tid = create_team(room,'alice','capacity-existing')
    for username in ('bob','charlie'):
        login(room,'player','alice')
        invitation = room.client.post(f'/api/player/teams/{tid}/invitations',json={'username':username},headers=csrf(room,'player')).json()['invitation']['id']
        login(room,'player',username)
        assert room.client.post(f'/api/player/team-invitations/{invitation}/accept',json={},headers=csrf(room,'player')).status_code == 200
    login(room,'admin','admin')
    assert room.client.put('/api/admin/team-policy',json={'max_members':2},headers=csrf(room,'admin')).status_code == 200
    team = room.client.get(f'/api/admin/teams/{tid}').json()['team']
    assert (team['member_count'],team['max_members']) == (3,2)


def upload(room, name):
    response = room.client.post('/api/player/bots',json={'filename':'bot.py','name':name,'game_id':'robot_battle',
        'source_base64':base64.b64encode(b"print('fixture')").decode()},headers=csrf(room,'player'))
    assert response.status_code == 201,response.text
    return response.json()['bot']['id']


def test_bot_archive_uploader_captain_cross_team_csrf_and_idempotence(room,monkeypatch):
    monkeypatch.setattr(room.app.state.runner,'prepare',lambda *_:{'status':'ready','logs':'','command':[],'execution_backend':'legacy'})
    tid = create_team(room,'alice','archive-members')
    alice_bot = upload(room,'Captain bot')
    invitation = room.client.post(f'/api/player/teams/{tid}/invitations',json={'username':'bob'},headers=csrf(room,'player')).json()['invitation']['id']
    login(room,'player','bob')
    room.client.post(f'/api/player/team-invitations/{invitation}/accept',json={},headers=csrf(room,'player'))
    bob_bot = upload(room,'Member bot')
    h = csrf(room,'player')
    assert room.client.delete(f'/api/player/bots/{bob_bot}').status_code == 403
    assert room.client.request('DELETE',f'/api/player/bots/{alice_bot}',json={},headers=h).status_code == 403
    for _ in range(2):
        assert room.client.request('DELETE',f'/api/player/bots/{bob_bot}',json={},headers=h).status_code == 200
    assert room.client.get(f'/api/player/bots/{bob_bot}/source').status_code == 404
    assert room.client.get('/api/player/bots').json()['bots'][0]['id'] == alice_bot
    login(room,'player','charlie')
    create_team(room,'charlie','archive-outsider')
    assert room.client.request('DELETE',f'/api/player/bots/{alice_bot}',json={},headers=csrf(room,'player')).status_code == 404
    login(room,'player','alice')
    assert room.client.put('/api/player/active-bot',json={'game_id':'robot_battle','bot_id':bob_bot},headers=csrf(room,'player')).status_code == 404
    another = upload(room,'Another member candidate')
    select_bot(room,'alice',alice_bot)
    assert room.client.request('DELETE',f'/api/player/bots/{alice_bot}',json={},headers=csrf(room,'player')).status_code == 409
    assert room.client.request('DELETE',f'/api/player/bots/{another}',json={},headers=csrf(room,'player')).status_code == 200
    runtime = room.app.state.account_http
    with runtime.database.read() as db:
        assert db.execute("SELECT count(*) FROM audit_events WHERE action='TEAM_BOT_ARCHIVED' AND target_id=?",(bob_bot,)).fetchone()[0] == 1
    assert room.app.state.store.get_bot(bob_bot) is not None


def test_archive_retains_queued_scrimmage_frozen_source_and_artifact(room,monkeypatch,pause_worker):
    teams = prepared(room,monkeypatch)
    response = room.client.post('/api/player/scrimmages',json={'game_id':'robot_battle','opponent_team_id':teams['bob']},headers=csrf(room,'player'))
    request_id = response.json()['request']['id']
    seed_ready_bot(room,teams['alice'],'alice','d'*16)
    select_bot(room,'alice','d'*16)
    login(room,'player','alice')
    assert room.client.request('DELETE','/api/player/bots/'+'a'*16,json={},headers=csrf(room,'player')).status_code == 200
    assert (room.app.state.store.uploads/('a'*16)/'bot.py').is_file()
    runtime = room.app.state.account_http
    with runtime.database.read() as db:
        plan = json.loads(db.execute('SELECT plan_json FROM scrimmage_requests WHERE id=?',(request_id,)).fetchone()[0])
        assert plan['slots']['A']['bot_id'] == 'a'*16
        assert plan['slots']['A']['artifact_id'] == 'artifact-alice'


def find(room):
    return room.client.post('/api/player/matchmaking/find',json={'game_id':'robot_battle'},headers=csrf(room,'player'))


def test_matchmaking_opt_in_idempotence_cancel_reload_and_privacy(room,monkeypatch,pause_worker):
    teams = prepared(room,monkeypatch)
    assert room.client.post('/api/player/matchmaking/find',json={'game_id':'robot_battle'}).status_code == 403
    first = find(room).json()['search']
    assert first['status'] == 'SEARCHING'
    assert find(room).json()['search']['id'] == first['id']
    assert room.client.get('/api/player/scrimmages').json()['requests'] == []  # Other ready Teams have not opted in.
    assert room.client.get('/api/player/matchmaking?game_id=robot_battle').json()['search']['id'] == first['id']
    login(room,'player','charlie')
    assert room.client.post(f"/api/player/matchmaking/{first['id']}/cancel",json={},headers=csrf(room,'player')).status_code == 404
    second = find(room).json()['search']
    assert second['status'] == 'MATCHED'
    assert 'artifact' not in json.dumps(second) and 'source' not in json.dumps(second)
    assert {s['team_id'] for s in second['request']['teams'].values()} == {teams['alice'],teams['charlie']}
    assert find(room).json()['search']['request_id'] == second['request_id']
    assert room.client.post(f"/api/player/matchmaking/{second['id']}/cancel",json={},headers=csrf(room,'player')).status_code == 409
    login(room,'player','bob')
    third = find(room).json()['search']
    assert third['status'] == 'SEARCHING'
    cancelled = room.client.post(f"/api/player/matchmaking/{third['id']}/cancel",json={},headers=csrf(room,'player'))
    assert cancelled.json()['search']['status'] == 'CANCELLED'
    assert find(room).json()['search']['id'] != third['id']


def test_matchmaking_timeout_and_restart_are_terminal(room,monkeypatch,pause_worker):
    prepared(room,monkeypatch)
    first = find(room).json()['search']
    room.clock.now += 301
    assert room.client.get('/api/player/matchmaking?game_id=robot_battle').json()['search']['status'] == 'EXPIRED'
    second = find(room).json()['search']
    runtime = room.app.state.account_http
    room.client.portal.call(runtime.run,lambda auth,db:Matchmaking(auth,db,runtime.writer,room.app.state.store,room.app.state.registry).maintain(restart=True))
    status = room.client.get('/api/player/matchmaking?game_id=robot_battle').json()['search']
    assert status['id'] == second['id'] and status['status_reason'] == 'SERVER_RESTART'


def test_three_concurrent_finds_never_claim_a_team_twice(room,monkeypatch,pause_worker):
    prepared(room,monkeypatch)
    actors = [principal(room,name) for name in ('alice','bob','charlie')]
    runtime = room.app.state.account_http
    barrier = threading.Barrier(3)
    def search(actor):
        with runtime.database.writer_connection(runtime.writer) as db:
            auth = AuthService(db,runtime.writer,clock=room.clock,login_limiter=AuthRateLimiter())
            service = Matchmaking(auth,db,runtime.writer,room.app.state.store,room.app.state.registry)
            barrier.wait(timeout=5)
            return service.find(actor,'robot_battle')
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(search,actor) for actor in actors]
        outcomes = [f.result(timeout=15) for f in futures]
    with runtime.database.read() as db:
        assert db.execute('SELECT count(*) FROM scrimmage_requests').fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM matchmaking_searches WHERE status='MATCHED'").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM matchmaking_searches WHERE status='SEARCHING'").fetchone()[0] == 1
    assert len({row['request_id'] for row in outcomes if row['request_id']}) == 1


def test_fifo_selection_and_bot_snapshot_at_pairing(room,monkeypatch,pause_worker):
    teams = prepared(room,monkeypatch)
    actors = {name:principal(room,name) for name in ('alice','bob','charlie')}
    runtime = room.app.state.account_http
    # Multiple already-waiting Teams can exist after eligibility changes. The
    # oldest eligible one must win rather than a random recent search.
    with runtime.database.writer_connection(runtime.writer) as db:
        from backend.account_database import transaction
        with transaction(db):
            for name,age in [('alice',10),('bob',5)]:
                db.execute("""INSERT INTO matchmaking_searches(id,team_id,requested_by,game_id,status,created_at,expires_at,updated_at)
                    VALUES (?,?,?,'robot_battle','SEARCHING',?,?,?)""",(name,teams[name],actors[name].account.id,room.clock.now-age,room.clock.now+300,room.clock.now-age))
    seed_ready_bot(room,teams['alice'],'alice','d'*16)
    bot = room.app.state.store.get_bot('d'*16)
    bot.update(execution_backend='sandbox',artifact_id='replacement',artifact_digest='d'*64)
    room.app.state.store.save_bot(bot)
    select_bot(room,'alice','d'*16)
    login(room,'player','charlie')
    result = find(room).json()['search']
    assert {slot['team_id'] for slot in result['request']['teams'].values()} == {teams['alice'],teams['charlie']}
    with runtime.database.read() as db:
        plan = json.loads(db.execute('SELECT plan_json FROM scrimmage_requests WHERE id=?',(result['request_id'],)).fetchone()[0])
        assert plan['slots']['A']['bot_id'] == 'd'*16
        assert db.execute("SELECT status FROM matchmaking_searches WHERE id='bob'").fetchone()[0] == 'SEARCHING'


def test_archive_after_official_lock_retains_claimable_frozen_bot(room,monkeypatch,pause_worker):
    from test_official_schedule import schedule
    from backend.official_service import OfficialSchedule
    teams = prepared(room,monkeypatch)
    deadline = room.clock.now+2
    response = schedule(room,teams['alice'],teams['bob'],bot_lock_at=deadline,scheduled_at=deadline+5)
    assert response.status_code == 201,response.text
    request_id = response.json()['request']['id']
    seed_ready_bot(room,teams['alice'],'alice','d'*16)
    room.clock.now = deadline
    select_bot(room,'alice','d'*16)  # Freezes the old bot before selection.
    login(room,'player','alice')
    assert room.client.request('DELETE','/api/player/bots/'+'a'*16,json={},headers=csrf(room,'player')).status_code == 200
    room.clock.now = deadline+5
    runtime = room.app.state.account_http
    plan = room.client.portal.call(runtime.run,lambda auth,db:OfficialSchedule(db,runtime.writer,auth,room.app.state.store,room.app.state.registry).claim_due())
    assert plan['id'] == request_id
    assert plan['slots']['A']['bot_id'] == 'a'*16
    assert plan['slots']['A']['artifact_id'] == 'artifact-alice'
