from workflow import official_match, player_client
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field

from backend.engine import create_registry
from backend.engine.base import GameAdapter, InvalidAction
from backend.main import create_app
from backend.runner import tool


@pytest.fixture
def client(tmp_path, authorize_organizer):
    with TestClient(create_app(tmp_path, tick_seconds=0.001)) as connection:
        authorize_organizer(connection)
        yield connection


def sample(client, game_id, language):
    if client.get("/api/competition").json()["selected_game_id"] != game_id:
        assert client.put("/api/games/selected", json={"game_id": game_id}).status_code == 200
    response = player_client(client).post(f"/api/games/{game_id}/samples/{language}/submit")
    assert response.status_code == 201
    bot = response.json()
    assert bot["status"] == "ready", bot["logs"]
    assert bot["game_id"] == game_id
    return bot


def watch(client, match_id, after=-1, headers=None):
    messages = []
    with client.websocket_connect(f"/ws/matches/{match_id}?after={after}", headers=headers or {}) as socket:
        while True:
            message = socket.receive_json()
            messages.append(message)
            if message["type"] == "complete":
                break
    return [item["state"] for item in messages if item["type"] == "state"], messages[-1]["match"]


def test_registry_game_specific_schema_selection_validation_and_reset(client):
    catalog = client.get("/api/games").json()
    assert catalog["selected_game_id"] == "robot_battle"
    games = {game["game_id"]: game for game in catalog["games"]}
    assert set(games) == {"robot_battle", "ott_v2"}
    assert set(games["robot_battle"]["rules_schema"]["properties"]) == {"map_size", "initial_hp", "damage", "max_turns"}
    assert set(games["ott_v2"]["rules_schema"]["properties"]) == {"max_turns", "rounds"}
    assert games["ott_v2"]["preview_state"]["board_size"] == 9
    assert client.put("/api/games/selected", json={"game_id": "ott_v2"}).status_code == 200
    assert client.get("/api/rules").json() == {"max_turns": 100, "rounds": 1}
    assert client.put("/api/games/ott_v2/rules", json={"max_turns": 5, "rounds": 2}).json() == {"max_turns": 5, "rounds": 2}
    assert client.put("/api/games/ott_v2/rules", json={"map_size": 5}).status_code == 422
    assert client.put("/api/games/robot_battle/rules", json={"rounds": 2}).status_code == 422
    assert client.post("/api/games/ott_v2/rules/reset").json() == {"max_turns": 100, "rounds": 1}
    assert client.get("/api/games/not_installed").status_code == 404


def test_submission_requires_game_and_rejects_cross_game_pair(client, open_competition):
    assert player_client(client).post("/api/bots", files={"file": ("bot.py", b"pass")}).status_code == 422
    assert player_client(client).post("/api/bots", files={"file": ("bot.py", b"pass")}, data={"game_id": "unknown"}).status_code == 404
    robot, ott = sample(client, "robot_battle", "python"), sample(client, "ott_v2", "python")
    open_competition(client, "ott_v2")
    assert official_match(client, {"game_id": "ott_v2", "bot_a": robot["id"], "bot_b": ott["id"]}).status_code == 409
    assert len(client.get("/api/bots?game_id=ott_v2").json()) == 1
    assert player_client(client).post("/api/games/ott_v2/samples/python/submit").json()["id"] == ott["id"]


def test_ott_saved_config_changes_real_rounds_and_replay_freezes_snapshot(client, tmp_path, open_competition, stop_backend):
    rules = {"max_turns": 3, "rounds": 2}
    client.put("/api/games/selected", json={"game_id": "ott_v2"})
    client.put("/api/games/ott_v2/rules", json=rules)
    a = sample(client, "ott_v2", "python")
    open_competition(client, "ott_v2")
    match = official_match(client, {"bot_a": a["id"], "bot_b": a["id"]}).json()
    assert client.put("/api/games/ott_v2/rules", json={"max_turns": 20, "rounds": 1}).status_code == 409
    frames, meta = watch(client, match["id"])
    assert meta["game_id"] == "ott_v2" and meta["rules"] == rules
    assert meta["turn"] == 7 and meta["result"]["winner"] is None
    assert frames[-1]["round"] == 2 and len(frames[-1]["round_results"]) == 2
    assert all(frame["rules"] == rules for frame in frames)
    assert [frame["turn"] for frame in frames] == list(range(8))
    assert client.get(f"/api/matches/{meta['id']}/replay").json()["frames"] == frames
    stop_backend(client)
    with TestClient(create_app(tmp_path)) as restarted:
        assert restarted.get("/api/games").json()["selected_game_id"] == "ott_v2"
        assert restarted.get(f"/api/matches/{meta['id']}/replay").json()["frames"] == frames


@pytest.mark.parametrize("game_id,a_lang,b_lang", [("robot_battle", "python", "cpp"),
                                                  ("robot_battle", "cpp", "java"),
                                                  ("ott_v2", "python", "cpp"),
                                                  ("ott_v2", "cpp", "java")])
def test_cross_language_games_really_complete(client, game_id, a_lang, b_lang, open_competition):
    if not tool("g++") or ("java" in (a_lang, b_lang) and not tool("javac")):
        pytest.skip("Required compiler missing")
    a, b = sample(client, game_id, a_lang), sample(client, game_id, b_lang)
    open_competition(client, game_id)
    response = official_match(client, {"game_id": game_id, "bot_a": a["id"], "bot_b": b["id"]})
    assert response.status_code == 200, response.text
    frames, match = watch(client, response.json()["id"])
    assert match["status"] == "completed" and match["result"]["reason"] != "bot_error"
    assert match["result"]["reason"] in ("goal", "elimination", "knockout")
    assert len(frames) > 2 and all(frame["game_id"] == game_id for frame in frames)
    assert client.get(f"/api/matches/{match['id']}/replay").json()["frames"] == frames
    if game_id == "ott_v2":
        assert frames[2]["last_move"]["to"]["row"] < 7, "B must target a1, not last_move.player A's i9"
        for index, frame in enumerate(frames[1:], 1):
            assert set(frame["actions"]) == {"A" if index % 2 else "B"}


def test_private_lan_hosts_and_two_spectators_share_one_match(client, open_competition):
    headers = {"Host": "192.168.1.20:8000", "Origin": "http://192.168.1.20:8000"}
    assert client.get("/api/games", headers=headers).status_code == 200
    assert client.get("/api/health", headers={"Host": "8.8.8.8:8000"}).status_code == 403
    assert client.get("/api/health", headers={**headers, "Origin": "http://192.168.1.21:8000"}).status_code == 403
    a = sample(client, "ott_v2", "python")
    open_competition(client, "ott_v2", {"max_turns": 4})
    match = official_match(client, {"game_id": "ott_v2", "bot_a": a["id"], "bot_b": a["id"]}).json()
    with client.websocket_connect(f"/ws/matches/{match['id']}", headers=headers) as one:
        with client.websocket_connect(f"/ws/matches/{match['id']}") as two:
            streams = []
            for socket in (one, two):
                frames = []
                while True:
                    message = socket.receive_json()
                    if message["type"] == "state":
                        frames.append(message["state"])
                    if message["type"] == "complete":
                        break
                streams.append(frames)
    assert streams[0] == streams[1] == client.get(f"/api/matches/{match['id']}/replay").json()["frames"]


def test_ott_invalid_action_is_forfeit_not_state_mutation(client, open_competition):
    open_competition(client, "ott_v2")
    code = b"import sys,json\nfor line in sys.stdin:\n print(json.dumps({'action':'move','from':{'row':1,'col':3},'to':{'row':2,'col':4},'winner':'A'}),flush=True)\n"
    bad = player_client(client).post("/api/bots", files={"file": ("bad.py", code)}, data={"game_id": "ott_v2"}).json()
    good = sample(client, "ott_v2", "python")
    match = official_match(client, {"game_id": "ott_v2", "bot_a": bad["id"], "bot_b": good["id"]}).json()
    frames, meta = watch(client, match["id"])
    assert meta["result"]["winner"] == "B" and meta["result"]["reason"] == "bot_error"
    assert frames[-1]["board"] == frames[0]["board"]


class CounterRules(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    finish_after: int = Field(default=2, ge=1, le=5)


class CounterAdapter(GameAdapter):
    """Independent third adapter used to prove no tournament-core edit is needed."""
    rules_model = CounterRules
    metadata = {"game_id": "counter_demo", "name": "Counter", "version": "1", "turn_mode": "alternating", "description": "test", "renderer": "counter_demo"}
    def create_initial_state(self, rules):
        return {"game_id": "counter_demo", "rules": self.validate_rules(rules), "turn": 0, "result": None, "events": [], "actions": {}}
    def get_observation(self, state, player):
        return {"protocol": 1, "player": player, "turn": state["turn"]}
    def get_players_to_act(self, state):
        return ("A",) if not self.is_game_over(state) else ()
    def validate_action(self, state, player, action):
        if action != {"type": "wait"}:
            raise InvalidAction("Expected wait")
        return action
    def apply_action(self, state, actions):
        new = self.serialize_state(state)
        new["turn"] += 1
        new["actions"] = actions
        if new["turn"] >= new["rules"]["finish_after"]:
            new["result"] = {"winner": "A", "reason": "counter_finished", "faults": {}}
        return new


def test_installing_third_adapter_needs_no_core_change(tmp_path, authorize_organizer, open_competition):
    registry = create_registry()
    registry.register(CounterAdapter())
    with TestClient(create_app(tmp_path, tick_seconds=0.001, registry=registry)) as client:
        authorize_organizer(client)
        open_competition(client, "counter_demo", {"finish_after": 3})
        assert any(game["game_id"] == "counter_demo" for game in client.get("/api/games").json()["games"])
        code = b"import sys\nfor line in sys.stdin:\n print('{\"type\":\"wait\"}',flush=True)\n"
        bot = player_client(client).post("/api/bots", files={"file": ("counter.py", code)}, data={"game_id": "counter_demo"}).json()
        match = official_match(client, {"game_id": "counter_demo", "bot_a": bot["id"], "bot_b": bot["id"]}).json()
        frames, meta = watch(client, match["id"])
        assert len(frames) == 4 and meta["result"]["reason"] == "counter_finished"


def test_legacy_data_migrates_without_erasing_replays(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "rules.json").write_text(json.dumps({"map_size": 8, "initial_hp": 80, "damage": 10, "max_turns": 9}), encoding="utf-8")
    (data / "bots.json").write_text(json.dumps({"old": {"id": "old", "name": "old", "language": "py", "status": "ready", "sample_key": "python"}}), encoding="utf-8")
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/api/games/robot_battle/rules").json()["map_size"] == 8
        assert client.get("/api/bots").json()[0]["game_id"] == "robot_battle"
        assert client.get("/api/games/ott_v2/rules").json() == {"max_turns": 100, "rounds": 1}
