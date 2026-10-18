"""Phase 4.2D1: deterministic Official scheduling and per-match frozen selections."""
from pathlib import Path
import hashlib
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
    source=b"print('ok',flush=True)\n"
    (root/"bot.py").write_bytes(source)
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
        db.execute("""INSERT INTO official_source_attestations
            (bot_id,source_sha256,attested_at) VALUES (?,?,?)""",
            (bot_id,hashlib.sha256(source).hexdigest(),room.clock.now))
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


def freeze_official_requests(room):
    from backend.official_service import OfficialSchedule
    from backend.auth_service import AuthService
    from backend.auth_limits import AuthRateLimiter
    rt=room.app.state.account_http
    with rt.database.writer_connection(rt.writer) as conn:
        service=OfficialSchedule(conn,rt.writer,
            AuthService(conn,rt.writer,clock=room.clock,login_limiter=AuthRateLimiter()),
            room.app.state.store,room.app.state.registry)
        return service.freeze_due()


def test_compiled_source_mutation_blocks_official_snapshot(room):
    ta=create_team(room,"alice","alpha-tamper")
    tb=create_team(room,"bob","beta-tamper")
    a=seed_ready_bot(room,ta,"alice","a"*16)
    b=seed_ready_bot(room,tb,"bob","b"*16)
    select_bot(room,"alice",a)
    select_bot(room,"bob",b)
    deadline=room.clock.now+4
    response=schedule(room,ta,tb,bot_lock_at=deadline)
    assert response.status_code==201,response.text
    request_id=response.json()["request"]["id"]
    (room.app.state.store.uploads/a/"bot.py").write_bytes(b"print('TAMPERED')\n")
    room.clock.now=deadline
    assert freeze_official_requests(room)==[(request_id,"BLOCKED")]
    login(room,"admin","admin")
    locked=room.client.get(f"/api/admin/official-matches/{request_id}").json()["request"]
    assert locked["status"]=="BLOCKED"
    assert locked["status_reason"]=="SOURCE_CHANGED"
    assert locked["slots"]==[]


def test_old_unattested_bot_is_rejected_for_official_match(room):
    ta=create_team(room,"alice","alpha-unverified")
    tb=create_team(room,"bob","beta-unverified")
    a=seed_ready_bot(room,ta,"alice","a"*16)
    b=seed_ready_bot(room,tb,"bob","b"*16)
    select_bot(room,"alice",a)
    select_bot(room,"bob",b)
    deadline=room.clock.now+2
    response=schedule(room,ta,tb,bot_lock_at=deadline)
    assert response.status_code==201,response.text
    request_id=response.json()["request"]["id"]
    rt=room.app.state.account_http
    with rt.database.writer_connection(rt.writer) as conn,transaction(conn):
        conn.execute("DELETE FROM official_source_attestations WHERE bot_id=?",(a,))
    room.clock.now=deadline
    assert freeze_official_requests(room)==[(request_id,"BLOCKED")]
    login(room,"admin","admin")
    locked=room.client.get(f"/api/admin/official-matches/{request_id}").json()["request"]
    assert locked["status_reason"]=="SOURCE_UNVERIFIED"
    assert locked["slots"]==[]


def test_unreadable_source_does_not_starve_unrelated_due_request(room,monkeypatch):
    ta=create_team(room,"alice","alpha-unread")
    tb=create_team(room,"bob","beta-unread")
    tc=create_team(room,"charlie","gamma-unread")
    for user,tid,bot_id in (("alice",ta,"a"*16),("bob",tb,"b"*16),
                            ("charlie",tc,"c"*16)):
        seed_ready_bot(room,tid,user,bot_id)
        select_bot(room,user,bot_id)
    deadline=room.clock.now+3
    bad=schedule(room,ta,tb,bot_lock_at=deadline)
    good=schedule(room,tb,tc,bot_lock_at=deadline)
    assert bad.status_code==201 and good.status_code==201
    bad_id,good_id=bad.json()["request"]["id"],good.json()["request"]["id"]
    source_file=(room.app.state.store.uploads/("a"*16)/"bot.py").resolve()
    original_read=Path.read_bytes

    def faulty_read(self):
        if self.resolve()==source_file:
            raise PermissionError("QA fault injection: one unreadable source")
        return original_read(self)

    monkeypatch.setattr(Path,"read_bytes",faulty_read)
    room.clock.now=deadline
    updates=freeze_official_requests(room)
    assert dict(updates)=={bad_id:"BLOCKED",good_id:"LOCKED"}
    assert freeze_official_requests(room)==[]
    login(room,"admin","admin")
    failed=room.client.get(f"/api/admin/official-matches/{bad_id}").json()["request"]
    healthy=room.client.get(f"/api/admin/official-matches/{good_id}").json()["request"]
    assert failed["status_reason"]=="SOURCE_UNAVAILABLE"
    assert failed["slots"]==[]
    assert len(healthy["slots"])==2
    assert {slot["bot_id"] for slot in healthy["slots"]}=={"b"*16,"c"*16}



def make_sandbox_artifact(room, bot_id):
    """QA-only sandbox metadata; no Docker process or real artifact is created."""
    bot = room.app.state.store.get_bot(bot_id)
    bot.update(execution_backend="sandbox",
               artifact_id="a" * 32, artifact_digest="d" * 64)
    room.app.state.store.save_bot(bot)


def test_d2_claim_is_single_use_and_restart_never_reexecutes(room):
    ta=create_team(room,"alice","alpha-d2once")
    tb=create_team(room,"bob","beta-d2once")
    for user,tid,bot_id in (("alice",ta,"a"*16),("bob",tb,"b"*16)):
        seed_ready_bot(room,tid,user,bot_id)
        make_sandbox_artifact(room,bot_id)
        select_bot(room,user,bot_id)
    deadline=room.clock.now+10
    res=schedule(room,ta,tb,bot_lock_at=deadline,scheduled_at=deadline)
    assert res.status_code==201,res.text
    request_id=res.json()["request"]["id"]
    room.clock.now=deadline
    rt=room.app.state.account_http
    from backend.official_service import OfficialSchedule
    from backend.auth_service import AuthService
    from backend.auth_limits import AuthRateLimiter
    with rt.database.writer_connection(rt.writer) as conn:
        svc=OfficialSchedule(conn,rt.writer,
            AuthService(conn,rt.writer,clock=room.clock,login_limiter=AuthRateLimiter()),
            room.app.state.store,room.app.state.registry)
        svc.freeze_due()
        first=svc.claim_due()
        assert first["id"]==request_id
        assert first["match_id"]=="o"+request_id[:15]
        assert svc.claim_due() is None
        # A crash after a durable claim but before writing a replay must not
        # cause the match to be resubmitted; restart is fail-closed.
        assert svc.recover_uncertain()==1
        assert svc.claim_due() is None
        request=svc._get(request_id)
        assert request["status"]=="INTERRUPTED"
        assert request["status_reason"]=="SERVER_RESTART"
        assert svc.recover_uncertain()==0


def test_d3_replay_scoped_to_participating_team_and_admin(room):
    ta=create_team(room,"alice","alpha-d3private")
    tb=create_team(room,"bob","beta-d3private")
    for user,tid,bot_id in (("alice",ta,"a"*16),("bob",tb,"b"*16)):
        seed_ready_bot(room,tid,user,bot_id)
        make_sandbox_artifact(room,bot_id)
        select_bot(room,user,bot_id)
    deadline=room.clock.now+8
    response=schedule(room,ta,tb,bot_lock_at=deadline,scheduled_at=deadline)
    assert response.status_code==201,response.text
    request_id=response.json()["request"]["id"]
    room.clock.now=deadline
    rt=room.app.state.account_http
    from backend.official_service import OfficialSchedule
    from backend.auth_service import AuthService
    from backend.auth_limits import AuthRateLimiter
    with rt.database.writer_connection(rt.writer) as conn:
        svc=OfficialSchedule(conn,rt.writer,
            AuthService(conn,rt.writer,clock=room.clock,login_limiter=AuthRateLimiter()),
            room.app.state.store,room.app.state.registry)
        svc.freeze_due()
        claim=svc.claim_due()
        match_id=claim["match_id"]
        room.app.state.store.save_match({
            "id":match_id,"official_request_id":request_id,"game_id":GAME,
            "status":"completed","result":{"winner":"A","reason":"goal"},
            "turn":1,"bots":{"A":{"id":"a"*16,"name":"A","language":"py"},
                             "B":{"id":"b"*16,"name":"B","language":"py"}},
            "command":["private"],"artifact_digest":"secret"})
        room.app.state.store.start_replay(match_id,{"turn":0,"game_id":GAME})
        room.app.state.store.append_replay_frame(match_id,{
            "turn":1,"game_id":GAME,"result":{"winner":"A","reason":"goal"}})
        assert svc.sync_execution()==[request_id]
        saved=svc._get(request_id)
        assert saved["status"]=="COMPLETED"
        assert svc.sync_execution()==[]
        assert svc.recover_uncertain()==0
    login(room,"admin","admin")
    path="/api/admin/official-matches/"+request_id+"/replay"
    admin=room.client.get(path)
    assert admin.status_code==200,admin.text
    assert len(admin.json()["frames"])==2
    assert "command" not in admin.json()["match"]
    assert "artifact_digest" not in admin.json()["match"]
    login(room,"player","charlie")
    denied=room.client.get("/api/player/official-matches/"+request_id+"/replay")
    assert denied.status_code==404
    login(room,"player","alice")
    allowed=room.client.get("/api/player/official-matches/"+request_id+"/replay")
    assert allowed.status_code==200,allowed.text
    assert len(allowed.json()["frames"])==2
    assert allowed.json()["match"]["status"]=="completed"


def test_d2_no_legacy_runner_dispatch_for_locked_official(room):
    """The native/legacy runner must never execute an Official match."""
    ta=create_team(room,"alice","alpha-legacy-d2")
    tb=create_team(room,"bob","beta-legacy-d2")
    for user,tid,bot_id in (("alice",ta,"a"*16),("bob",tb,"b"*16)):
        seed_ready_bot(room,tid,user,bot_id)
        select_bot(room,user,bot_id)
    deadline=room.clock.now+2
    response=schedule(room,ta,tb,bot_lock_at=deadline,scheduled_at=deadline)
    assert response.status_code==201
    request_id=response.json()["request"]["id"]
    room.clock.now=deadline
    from backend.official_service import OfficialSchedule
    from backend.auth_service import AuthService
    from backend.auth_limits import AuthRateLimiter
    rt=room.app.state.account_http
    with rt.database.writer_connection(rt.writer) as conn:
        svc=OfficialSchedule(conn,rt.writer,
            AuthService(conn,rt.writer,clock=room.clock,login_limiter=AuthRateLimiter()),
            room.app.state.store,room.app.state.registry)
        svc.freeze_due()
        assert svc._get(request_id)["status"]=="LOCKED"
    # The official worker must leave it locked until an enabled sandbox exists.
    assert room.app.state.manager.runner.mode=="legacy"
    assert room.app.state.store.get_match("o"+request_id[:15]) is None


def test_d2_artifact_metadata_change_after_lock_blocks_dispatch(room):
    ta=create_team(room,"alice","alpha-d2-artifact")
    tb=create_team(room,"bob","beta-d2-artifact")
    for user,tid,bot_id in (("alice",ta,"a"*16),("bob",tb,"b"*16)):
        seed_ready_bot(room,tid,user,bot_id)
        make_sandbox_artifact(room,bot_id)
        select_bot(room,user,bot_id)
    deadline=room.clock.now+5
    response=schedule(room,ta,tb,bot_lock_at=deadline,scheduled_at=deadline+4)
    assert response.status_code==201,response.text
    request_id=response.json()["request"]["id"]
    room.clock.now=deadline
    assert freeze_official_requests(room)==[(request_id,"LOCKED")]
    # Changing the mutable JSON artifact after lock cannot switch a frozen bot.
    tampered=room.app.state.store.get_bot("a"*16)
    tampered["artifact_digest"]="b"*64
    room.app.state.store.save_bot(tampered)
    room.clock.now=deadline+4
    rt=room.app.state.account_http
    from backend.official_service import OfficialSchedule
    from backend.auth_service import AuthService
    from backend.auth_limits import AuthRateLimiter
    with rt.database.writer_connection(rt.writer) as conn:
        svc=OfficialSchedule(conn,rt.writer,
            AuthService(conn,rt.writer,clock=room.clock,login_limiter=AuthRateLimiter()),
            room.app.state.store,room.app.state.registry)
        blocked=svc.claim_due()
        assert blocked=={"blocked":request_id,"reason":"FROZEN_ARTIFACT_UNAVAILABLE"}
        assert svc.claim_due() is None
        assert svc._get(request_id)["status"]=="BLOCKED"
        assert conn.execute("SELECT count(*) FROM official_match_slots WHERE request_id=?",
                            (request_id,)).fetchone()[0]==2


@pytest.mark.parametrize("replay_mode", ["missing", "truncated"])
def test_d2_missing_terminal_replay_frame_never_publishes_win(room, replay_mode):
    ta=create_team(room,"alice","alpha-d2partial")
    tb=create_team(room,"bob","beta-d2partial")
    for user,tid,bot_id in (("alice",ta,"a"*16),("bob",tb,"b"*16)):
        seed_ready_bot(room,tid,user,bot_id)
        make_sandbox_artifact(room,bot_id)
        select_bot(room,user,bot_id)
    deadline=room.clock.now+5
    response=schedule(room,ta,tb,bot_lock_at=deadline,scheduled_at=deadline)
    assert response.status_code==201
    request_id=response.json()["request"]["id"]
    room.clock.now=deadline
    rt=room.app.state.account_http
    from backend.official_service import OfficialSchedule
    from backend.auth_service import AuthService
    from backend.auth_limits import AuthRateLimiter
    with rt.database.writer_connection(rt.writer) as conn:
        svc=OfficialSchedule(conn,rt.writer,
            AuthService(conn,rt.writer,clock=room.clock,login_limiter=AuthRateLimiter()),
            room.app.state.store,room.app.state.registry)
        svc.freeze_due()
        claim=svc.claim_due()
        match_id=claim["match_id"]
        # Storage JSON says completed, but the final replay record is missing.
        room.app.state.store.save_match({
            "id":match_id,"official_request_id":request_id,"status":"completed",
            "game_id":GAME,"result":{"winner":"A","reason":"goal"},"turn":1})
        if replay_mode == "truncated":
            room.app.state.store.start_replay(match_id,{"turn":0,"game_id":GAME,"result":None})
        assert svc.sync_execution()==[request_id]
        row=svc._get(request_id)
        assert row["status"]=="INTERRUPTED"
        assert row["status_reason"]=="REPLAY_INCOMPLETE"
        assert row["outcome_json"] is None
    # Both a missing replay and an incomplete final record must not
    # advertise the unverified JSON victory to Account-Only clients.
    login(room,"admin","admin")
    response=room.client.get("/api/admin/official-matches/"+request_id+"/replay")
    assert response.status_code==200,response.text
    payload=response.json()
    assert payload["match"]["status"]=="interrupted"
    assert payload["match"]["winner"] is None
    assert payload["match"]["result"]["winner"] is None
    assert payload["match"]["result"]["reason"]=="REPLAY_INCOMPLETE"
    assert all(not frame.get("result") for frame in payload["frames"])


def test_robot_enriched_match_result_validates_against_serialized_terminal(room):
    """QA-002: raw Robot replay result lacks derived HP scores."""
    ta=create_team(room,"alice","robot-adapter-alpha")
    tb=create_team(room,"bob","robot-adapter-beta")
    for user,tid,bot_id in (("alice",ta,"a"*16),("bob",tb,"b"*16)):
        seed_ready_bot(room,tid,user,bot_id)
        make_sandbox_artifact(room,bot_id)
        select_bot(room,user,bot_id)
    deadline=room.clock.now+4
    created=schedule(room,ta,tb,bot_lock_at=deadline,scheduled_at=deadline)
    assert created.status_code==201,created.text
    request_id=created.json()["request"]["id"]
    room.clock.now=deadline
    from backend.official_service import OfficialSchedule
    from backend.auth_service import AuthService
    from backend.auth_limits import AuthRateLimiter
    rt=room.app.state.account_http
    with rt.database.writer_connection(rt.writer) as conn:
        service=OfficialSchedule(conn,rt.writer,
            AuthService(conn,rt.writer,clock=room.clock,login_limiter=AuthRateLimiter()),
            room.app.state.store,room.app.state.registry)
        service.freeze_due()
        plan=service.claim_due()
        assert plan["id"]==request_id
        adapter=room.app.state.registry.get(GAME)
        initial=adapter.create_initial_state(adapter.validate_rules())
        terminal=adapter.serialize_state(initial)
        terminal["turn"]=1
        terminal["result"]={"winner":"A","reason":"knockout","faults":{}}
        derived=adapter.get_result(terminal)
        assert "scores" in derived
        assert "scores" not in terminal["result"]
        room.app.state.store.save_match({
            "id":plan["match_id"],"official_request_id":request_id,
            "game_id":GAME,"status":"completed","turn":1,
            "result":derived,"winner":"A"})
        room.app.state.store.start_replay(plan["match_id"],initial)
        room.app.state.store.append_replay_frame(plan["match_id"],terminal)
        assert service.sync_execution()==[request_id]
        row=service._get(request_id)
        assert row["status"]=="COMPLETED"
        outcome=service.detail_admin(
            service.auth.login("admin","team-http test passphrase 84",
                               audience="ADMIN",source_key="robot-adapter").principal,
            request_id)["outcome"]
        assert outcome["winner_side"]=="A"
        assert outcome["winner_team_id"]==ta
        assert outcome["result"]==derived
