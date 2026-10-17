"""Phase 4.2D1: deterministic Official scheduling and per-match frozen selections."""
from pathlib import Path
import pytest

from test_team_http import room,login,csrf
from backend.account_database import transaction


GAME = "robot_battle"


def create_team(room,username,slug):
    login(room,"player",username)
    hdr=csrf(room,"player")
    reply=room.client.post("/api/player/teams",json={"slug":slug,"display_name":slug.upper()},headers=hdr)
    assert reply.status_code==201,reply.text
    team_id=reply.json()["team"]["id"]
    activated=room.client.post(f"/api/player/teams/{team_id}/activate",json={},headers=hdr)
    assert activated.status_code==200,activated.text
    return team_id


def seed_ready_bot(room,team_id,username,bot_id):
    """Synthetic locally persisted compiled bot and ownership; real compiler is tested by C2."""
    root=room.app.state.store.uploads/bot_id
    root.mkdir(parents=True,exist_ok=True)
    (root/"bot.py").write_bytes(b"print('ok',flush=True)\n")
    room.app.state.store.save_bot({
        "id":bot_id,"name":"Ready "+username,"language":"py","game_id":GAME,
        "team_id":team_id,"status":"ready","filename":"bot.py",
        "command":[],"folder":str(root)
    })
    runtime=room.app.state.account_http
    with runtime.database.writer_connection(runtime.writer) as db,transaction(db):
        user_id=db.execute("SELECT id FROM users WHERE username=?",(username,)).fetchone()[0]
        db.execute("""INSERT INTO submission_ownership
            (bot_id,team_id,game_id,uploaded_by,origin,created_at)
            VALUES (?,?,?,?,'NEW',?)""",
            (bot_id,team_id,GAME,user_id,room.clock.now))
    return bot_id


def select_bot(room,username,bot_id):
    login(room,"player",username)
    reply=room.client.put("/api/player/active-bot",
        json={"game_id":GAME,"bot_id":bot_id},headers=csrf(room,"player"))
    assert reply.status_code==200,reply.text


def schedule(room,team_a_id,team_b_id,*,bot_lock_at,scheduled_at=None):
    login(room,"admin","admin")
    response=room.client.post("/api/admin/official-matches",json={
        "team_a_id":team_a_id,"team_b_id":team_b_id,"game_id":GAME,
        "bot_lock_at":bot_lock_at,"scheduled_at":scheduled_at or bot_lock_at+30,
    },headers=csrf(room,"admin"))
    return response


def test_d1_admin_schedule_and_player_isolation(room):
    ta=create_team(room,"alice","alpha-official")
    tb=create_team(room,"bob","beta-official")
    now=room.clock.now
    # Player cannot create Admin-scheduled matches.
    denied=room.client.post("/api/admin/official-matches",json={
        "team_a_id":ta,"team_b_id":tb,"game_id":GAME,
        "bot_lock_at":now+20,"scheduled_at":now+50},headers=csrf(room,"player"))
    assert denied.status_code in (401,403)
    invalid=schedule(room,ta,ta,bot_lock_at=now+20)
    assert invalid.status_code==409
    response=schedule(room,ta,tb,bot_lock_at=now+20)
    assert response.status_code==201,response.text
    data=response.json()["request"]
    assert data["status"]=="SCHEDULED"
    assert data["slots"]==[]
    assert data["bot_lock_at"]==now+20
    assert data["rules_snapshot"]==room.app.state.store.get_rules(GAME)
    login(room,"player","charlie")
    assert room.client.get("/api/player/official-matches").json()["requests"]==[]
    login(room,"player","alice")
    all_requests=room.client.get("/api/player/official-matches")
    assert all_requests.status_code==200
    assert [x["id"] for x in all_requests.json()["requests"]]==[data["id"]]


def test_lock_deadline_precedes_late_active_bot_change(room):
    ta=create_team(room,"alice","alpha-freeze")
    tb=create_team(room,"bob","beta-freeze")
    for username,team_id,bot_id in (("alice",ta,"a"*16),("bob",tb,"b"*16),
                                    ("alice",ta,"c"*16)):
        seed_ready_bot(room,team_id,username,bot_id)
    select_bot(room,"alice","a"*16)
    select_bot(room,"bob","b"*16)
    deadline=room.clock.now+15
    reply=schedule(room,ta,tb,bot_lock_at=deadline)
    assert reply.status_code==201,reply.text
    request_id=reply.json()["request"]["id"]
    # No scheduler tick required: selection itself locks every overdue request.
    room.clock.now=deadline
    select_bot(room,"alice","c"*16)
    login(room,"admin","admin")
    response=room.client.get(f"/api/admin/official-matches/{request_id}")
    assert response.status_code==200,response.text
    request=response.json()["request"]
    assert request["status"]=="LOCKED"
    assert len(request["slots"])==2
    assert request["slots"][0]["bot_id"]=="a"*16
    assert request["slots"][1]["bot_id"]=="b"*16
    assert request["slots"][0]["bot_revision"]==1
    assert request["slots"][0]["source_sha256"]
    # Late selection applies only to future matches.
    login(room,"player","alice")
    active=room.client.get(f"/api/player/active-bot?game_id={GAME}")
    assert active.json()["active"]["bot"]["id"]=="c"*16
    login(room,"admin","admin")
    same=room.client.get(f"/api/admin/official-matches/{request_id}").json()["request"]
    assert same["slots"]==request["slots"]


def test_missing_ready_bot_blocks_without_false_loss(room):
    ta=create_team(room,"alice","alpha-block")
    tb=create_team(room,"bob","beta-block")
    start=room.clock.now
    reply=schedule(room,ta,tb,bot_lock_at=start+1)
    assert reply.status_code==201,reply.text
    request_id=reply.json()["request"]["id"]
    room.clock.now+=2
    # Freeze is idempotent even when both Teams have no Active Bot.
    from backend.official_service import OfficialSchedule
    from backend.auth_service import AuthService
    from backend.auth_limits import AuthRateLimiter
    rt=room.app.state.account_http
    with rt.database.writer_connection(rt.writer) as conn:
        service=OfficialSchedule(conn,rt.writer,
            AuthService(conn,rt.writer,clock=room.clock,login_limiter=AuthRateLimiter()),
            room.app.state.store,room.app.state.registry)
        assert service.freeze_due()==[(request_id,"BLOCKED")]
        assert service.freeze_due()==[]
    res=room.client.get(f"/api/admin/official-matches/{request_id}")
    assert res.json()["request"]["status"]=="BLOCKED"
    assert res.json()["request"]["status_reason"]=="ACTIVE_BOT_MISSING"
    assert res.json()["request"]["slots"]==[]


def test_cancel_is_admin_only_and_audited(room):
    ta=create_team(room,"alice","alpha-cancel")
    tb=create_team(room,"bob","beta-cancel")
    reply=schedule(room,ta,tb,bot_lock_at=room.clock.now+20)
    assert reply.status_code==201
    request_id=reply.json()["request"]["id"]
    cancelled=room.client.post(f"/api/admin/official-matches/{request_id}/cancel",
        json={},headers=csrf(room,"admin"))
    assert cancelled.status_code==200,cancelled.text
    assert cancelled.json()["request"]["status"]=="CANCELLED"
    again=room.client.post(f"/api/admin/official-matches/{request_id}/cancel",
        json={},headers=csrf(room,"admin"))
    assert again.status_code==409
    runtime=room.app.state.account_http
    with runtime.database.writer_connection(runtime.writer) as db:
        assert db.execute("""SELECT count(*) FROM audit_events
            WHERE target_id=? AND action='OFFICIAL_MATCH_CANCELLED'""",(request_id,)).fetchone()[0]==1
