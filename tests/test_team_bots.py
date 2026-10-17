"""Phase 4.2C2/C3 integration tests with isolated Account-Only data."""
import base64

from tests.test_team_http import room, login, csrf


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


