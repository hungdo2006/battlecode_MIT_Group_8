"""Phase 4.2C2/C3 integration tests with isolated Account-Only data."""
import base64
import hashlib

from test_team_http import room, login, csrf


def team(room, username, slug):
    login(room, "player", username)
    h = csrf(room, "player")
    result = room.client.post("/api/player/teams", json={"slug":slug,"display_name":slug},headers=h)
    assert result.status_code == 201, result.text
    tid = result.json()["team"]["id"]
    assert room.client.post(f"/api/player/teams/{tid}/activate",json={},headers=h).status_code == 200
    return tid, h


def test_submission_owner_and_captain_selection(room, monkeypatch):
    # No compilation side-effects, exercising real HTTP/SQLite/JSON transaction flow.
    monkeypatch.setattr(room.app.state.runner, "prepare",
                        lambda source, filename, folder: {"status":"ready","logs":"","command":[],
                            "execution_backend":"legacy"})
    team_id, h = team(room,"alice","alpha-bots")
    source = base64.b64encode(b"print('hello')").decode()
    payload = {"filename":"bot.py","name":"Alpha","game_id":"robot_battle","source_base64":source}
    res = room.client.post("/api/player/bots",json=payload,headers=h)
    assert res.status_code == 201, res.text
    bot_id = res.json()["bot"]["id"]
    # The SQLite attestation binds the original upload bytes independently of
    # subsequent JSON metadata or mutable files on disk.
    rt = room.app.state.account_http
    with rt.database.writer_connection(rt.writer) as db:
        attested = db.execute("SELECT source_sha256 FROM official_source_attestations WHERE bot_id=?",
                              (bot_id,)).fetchone()
        assert attested is not None
        assert attested["source_sha256"] == hashlib.sha256(b"print('hello')").hexdigest()
    assert room.client.get("/api/player/bots").json()["bots"][0]["id"] == bot_id
    src = room.client.get(f"/api/player/bots/{bot_id}/source")
    # Runner mock does not materialize source; metadata is still owned, source fail closed.
    assert src.status_code == 404
    sel = room.client.put("/api/player/active-bot",json={"bot_id":bot_id,"game_id":"robot_battle"},headers=h)
    assert sel.status_code == 200, sel.text
    assert sel.json()["active"]["revision"] == 1
    again = room.client.put("/api/player/active-bot",json={"bot_id":bot_id,"game_id":"robot_battle"},headers=h)
    assert again.json()["active"]["revision"] == 2
    assert room.client.get("/api/player/active-bot?game_id=robot_battle").json()["active"]["revision"] == 2
    team(room,"bob","beta-bots")
    assert room.client.get("/api/player/bots").json()["bots"] == []
    assert room.client.get(f"/api/player/bots/{bot_id}").status_code == 404
    assert room.client.get(f"/api/player/bots/{bot_id}/source").status_code == 404
    other = room.client.put("/api/player/active-bot",json={"bot_id":bot_id,"game_id":"robot_battle"},headers=csrf(room,"player"))
    assert other.status_code == 404


def test_disallowed_source_and_team_preconditions(room):
    login(room, "player", "alice")
    h = csrf(room, "player")
    res = room.client.post("/api/player/bots",json={"filename":"bot.py","game_id":"robot_battle",
        "source_base64":base64.b64encode(b"ok").decode()},headers=h)
    assert res.status_code == 403
    assert room.client.get("/api/player/bots").status_code == 403
    assert room.client.put("/api/player/active-bot",json={"bot_id":"invalid","game_id":"robot_battle"},headers=h).status_code == 403
    assert room.client.post("/api/player/bots",json={"filename":"bot.py","game_id":"robot_battle",
        "source_base64":"$$"},headers=h).status_code == 422



def test_incomplete_journal_recovery_idempotent(room):
    from backend.account_database import transaction
    from backend.auth_service import AuthService
    from backend.auth_limits import AuthRateLimiter
    from backend.bot_service import TeamBots
    tid,h=team(room,"alice","journal-qa")
    rt=room.app.state.account_http
    with rt.database.writer_connection(rt.writer) as db:
        auth=AuthService(db,rt.writer,login_limiter=AuthRateLimiter(),clock=room.clock)
        bots=TeamBots(auth,db,rt.writer,room.app.state.store,room.app.state.registry)
        uid=db.execute("SELECT id FROM users WHERE username='alice'").fetchone()[0]
        with transaction(db):
            db.execute("INSERT INTO submission_journal VALUES ('unfinished',?,?,?,?,'PREPARING')",
                       (tid,"robot_battle",uid,room.clock.now))
        assert bots.reconcile()==1
        assert bots.reconcile()==0
        assert db.execute("SELECT state FROM submission_journal WHERE bot_id='unfinished'").fetchone()[0]=="ABORTED"
    assert room.client.get("/api/player/bots").json()["bots"] == []
