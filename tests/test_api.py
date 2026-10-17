from workflow import official_match, player_client
import pytest
from fastapi.testclient import TestClient

from backend.main import create_app

WAIT_BOT = b"import sys,json\nfor line in sys.stdin:\n print(json.dumps({'type':'wait'}),flush=True)\n"


@pytest.fixture
def client(tmp_path, authorize_organizer):
    with TestClient(create_app(tmp_path, tick_seconds=0.001)) as client:
        authorize_organizer(client)
        yield client


def upload(client, code=WAIT_BOT, name="test"):
    response = player_client(client).post("/api/bots", files={"file": ("bot.py", code, "text/plain")}, data={"name": name, "game_id": "robot_battle"})
    assert response.status_code == 201
    return response.json()


def watch_to_end(client, match):
    frames = []
    with client.websocket_connect(f"/ws/matches/{match['id']}") as ws:
        assert ws.receive_json()["type"] == "hello"
        for _ in range(50):
            message = ws.receive_json()
            if message["type"] == "state":
                assert message["seq"] == len(frames)
                frames.append(message["state"])
            if message["type"] == "complete":
                assert message["match"]["status"] == "completed"
                return frames
    raise AssertionError("No final websocket message")


def test_rules_match_websocket_and_persisted_replay(client, tmp_path, open_competition, stop_backend):
    rules = {"map_size": 7, "initial_hp": 60, "damage": 15, "max_turns": 3}
    assert client.put("/api/rules", json=rules).json() == rules
    open_competition(client)
    a, b = upload(client, name="A"), upload(client, name="B")
    assert a["status"] == "ready" and "command" not in a
    response = official_match(client, {"bot_a": a["id"], "bot_b": b["id"]})
    assert response.status_code == 200
    match = response.json()
    frames = watch_to_end(client, match)
    assert [frame["turn"] for frame in frames] == [0, 1, 2, 3]
    assert frames[-1]["result"]["reason"] == "turn_limit"
    assert frames[0]["robots"]["A"]["hp"] == 60
    assert frames[0]["rules"]["map_size"] == 7
    replay = client.get(f"/api/matches/{match['id']}/replay").json()
    assert replay["frames"] == frames
    # A fresh app reads replay from disk and never needs a running bot.
    stop_backend(client)
    with TestClient(create_app(tmp_path)) as restarted:
        assert restarted.get(f"/api/matches/{match['id']}/replay").json()["frames"] == frames
        with restarted.websocket_connect(f"/ws/matches/{match['id']}?after=2") as ws:
            assert ws.receive_json()["type"] == "hello"
            assert ws.receive_json()["seq"] == 3
            assert ws.receive_json()["type"] == "complete"


@pytest.mark.parametrize("bad_bot", [
    b"import sys\nfor line in sys.stdin:\n print('bad json',flush=True)\n",
    b"import sys,json\nfor line in sys.stdin:\n print(json.dumps({'type':'teleport'}),flush=True)\n",
    b"raise RuntimeError('crash')\n",
])
def test_bot_fault_is_reported_in_match_and_replay(client, bad_bot, open_competition):
    open_competition(client)
    a, b = upload(client, name="good"), upload(client, bad_bot, "faulty")
    match = official_match(client, {"bot_a": a["id"], "bot_b": b["id"]}).json()
    frames = watch_to_end(client, match)
    result = frames[-1]["result"]
    assert result["winner"] == "A" and result["reason"] == "bot_error"
    assert result["faults"]["B"]


def test_invalid_requests_and_compile_error(client, open_competition):
    assert client.put("/api/rules", json={"map_size": 2}).status_code == 422
    assert player_client(client).post("/api/bots", files={"file": ("x.txt", b"code")}, data={"game_id": "robot_battle"}).status_code == 400
    assert player_client(client).post("/api/bots", files={"file": ("x.py", b"x" * (256 * 1024 + 1))}, data={"game_id": "robot_battle"}).status_code == 400
    broken = upload(client, b"def broken(:", "broken")
    assert broken["status"] == "error" and "SyntaxError" in broken["logs"]
    open_competition(client)
    assert official_match(client, {"bot_a": broken["id"], "bot_b": broken["id"]}).status_code == 409
    assert client.get("/api/matches/unknown/replay").status_code == 404
    assert client.get("/api/matches/../../etc/passwd/replay").status_code == 404


def test_browser_origin_is_restricted(client):
    assert player_client(client).post("/api/samples/python/submit", headers={"Origin": "https://unrelated.example"}).status_code == 403
    assert client.get("/api/health", headers={"Host": "unrelated.example"}).status_code == 403


def test_sample_submission_is_idempotent_and_downloadable(client):
    assert "flush=True" in client.get("/api/samples/python").text
    first = player_client(client).post("/api/samples/python/submit").json()
    second = player_client(client).post("/api/samples/python/submit").json()
    assert first["id"] == second["id"]
    assert len(client.get("/api/bots").json()) == 1


def test_rules_are_frozen_for_running_match(client, open_competition):
    a = upload(client)
    rules = {"map_size": 5, "initial_hp": 70, "damage": 11, "max_turns": 3}
    open_competition(client, rules=rules)
    match = official_match(client, {"bot_a": a["id"], "bot_b": a["id"]}).json()
    assert client.put("/api/rules", json={"map_size": 20, "initial_hp": 400, "damage": 100, "max_turns": 5}).status_code == 409
    frames = watch_to_end(client, match)
    assert all(frame["rules"] == rules for frame in frames)


def test_static_frontend_is_served_by_same_app(client):
    assert client.get("/").status_code == 200
    assert "LIVE ARENA" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
