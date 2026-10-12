from workflow import official_match, player_client
"""Authorization, stable game defaults and append-only replay regression tests."""
import json
import os

import pytest
from fastapi.testclient import TestClient

from backend.engine import create_registry
from backend.main import create_app
from backend.sessions import COOKIE_NAME
from backend.storage import Store

WAIT = b"import sys,json\nfor line in sys.stdin:\n print(json.dumps({'type':'wait'}),flush=True)\n"


def watch(client, match_id):
    frames = []
    with client.websocket_connect(f"/ws/matches/{match_id}") as socket:
        while True:
            message = socket.receive_json()
            if message["type"] == "state":
                assert message["seq"] == len(frames)
                frames.append(message["state"])
            if message["type"] == "complete":
                return frames, message["match"]


def bot(client):
    response = player_client(client).post("/api/bots", files={"file": ("wait.py", WAIT)}, data={"game_id": "robot_battle"})
    assert response.status_code == 201
    return response.json()


def test_player_cannot_edit_rules_default_or_override_match(tmp_path, authorize_organizer, open_competition):
    app = create_app(tmp_path, tick_seconds=0.001)
    with TestClient(app) as organizer:
        authorize_organizer(organizer)
        assert organizer.put("/api/games/robot_battle/rules", json={"max_turns": 3}).status_code == 200
        player = TestClient(app)
        player.portal = organizer.portal
        try:
            assert player.get("/api/session").json()["role"] == "player"
            protected = [("PUT", "/api/rules", {"max_turns": 1}),
                         ("PUT", "/api/games/robot_battle/rules", {"max_turns": 1}),
                         ("PUT", "/api/games/ott_v2/rules", {"rounds": 5}),
                         ("POST", "/api/games/robot_battle/rules/reset", {}),
                         ("POST", "/api/games/ott_v2/rules/reset", {}),
                         ("PUT", "/api/games/selected", {"game_id": "ott_v2"})]
            for method, path, payload in protected:
                assert player.request(method, path, json=payload).status_code == 403, path
            assert organizer.get("/api/games").json()["selected_game_id"] == "robot_battle"
            assert organizer.get("/api/games/robot_battle/rules").json()["max_turns"] == 3
            submission = bot(player)
            open_competition(organizer)
            request = {"bot_a": submission["id"], "bot_b": submission["id"], "game_id": "robot_battle"}
            assert player.post("/api/matches", json={**request, "rules": {"max_turns": 1}}).status_code == 403
            response = official_match(organizer, request)
            assert response.status_code == 200
            frames, match = watch(player, response.json()["id"])
            assert len(frames) == 4 and match["rules"]["max_turns"] == 3
        finally:
            player.close()


def test_organizer_code_is_backend_verified_and_privilege_is_per_session(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as first:
        second = TestClient(app)
        second.portal = first.portal
        try:
            assert first.post("/api/session/organizer", json={"code": "wrong"}).status_code == 403
            assert first.get("/api/session").json()["role"] == "player"
            assert first.put("/api/session", json={"name": "Organizer", "role": "organizer"}).status_code == 422
            granted = first.post("/api/session/organizer", json={"code": os.environ["ARENA_ADMIN_CODE"]})
            assert granted.status_code == 200 and granted.json()["role"] == "organizer"
            assert second.get("/api/session").json()["role"] == "player"
            assert first.put("/api/games/selected", json={"game_id": "ott_v2"}).status_code == 200
            assert first.put("/api/games/ott_v2/rules", json={"rounds": 2}).status_code == 200
            assert first.post("/api/games/ott_v2/rules/reset").status_code == 200
            assert os.environ["ARENA_ADMIN_CODE"] not in granted.text
            assert os.environ["ARENA_ADMIN_CODE"] not in (tmp_path / "data/sessions.json").read_text(encoding="utf-8")
            assert first.delete("/api/session/organizer").json()["role"] == "player"
            assert first.put("/api/rules", json={"rounds": 2}).status_code == 403
        finally:
            second.close()


def test_admin_disabled_without_code_and_grants_revoked_on_restart(tmp_path, monkeypatch, authorize_organizer):
    with TestClient(create_app(tmp_path)) as client:
        authorize_organizer(client)
        identity = client.get("/api/session").json()["participant"]
        token = client.cookies[COOKIE_NAME]
    with TestClient(create_app(tmp_path)) as restarted:
        restarted.cookies.set(COOKIE_NAME, token)
        session = restarted.get("/api/session").json()
        assert session["participant"] == identity and session["role"] == "player"
        assert restarted.put("/api/rules", json={"max_turns": 1}).status_code == 403
    monkeypatch.delenv("ARENA_ADMIN_CODE")
    with TestClient(create_app(tmp_path)) as disabled:
        assert disabled.get("/api/session").json()["organizer_available"] is False
        assert disabled.post("/api/session/organizer", json={"code": "anything"}).status_code == 503
        assert disabled.put("/api/games/selected", json={"game_id": "ott_v2"}).status_code == 403


def test_locked_game_rejects_implicit_incompatible_bot_pair(tmp_path, authorize_organizer, open_competition):
    app = create_app(tmp_path, tick_seconds=0.001)
    with TestClient(app) as organizer:
        authorize_organizer(organizer)
        organizer.put("/api/games/robot_battle/rules", json={"max_turns": 2})
        player = TestClient(app)
        player.portal = organizer.portal
        try:
            submission = bot(player)
            assert organizer.put("/api/games/selected", json={"game_id": "ott_v2"}).status_code == 200
            open_competition(organizer, "ott_v2")
            response = player.post("/api/matches", json={"bot_a": submission["id"], "bot_b": submission["id"]})
            assert response.status_code == 403
        finally:
            player.close()


def test_replay_appends_have_linear_growth_and_old_records_unchanged(tmp_path):
    store = Store(tmp_path, create_registry())
    frame = lambda i: {"turn": f"{i:04}", "payload": "x" * 1000, "text": "Lập trình mạng"}
    store.start_replay("linear", frame(0))
    path = store.replays / "linear.jsonl"
    for i in range(1, 100):
        store.append_replay_frame("linear", frame(i))
    first = path.read_bytes()
    for i in range(100, 200):
        store.append_replay_frame("linear", frame(i))
    second = path.read_bytes()
    assert len(second) == 2 * len(first)
    assert second.startswith(first)
    assert store.get_replay("linear") == {"version": 1, "frames": [frame(i) for i in range(200)]}
    with pytest.raises(FileExistsError):
        store.start_replay("linear", frame(0))


def test_legacy_replay_and_incomplete_final_record_survive_restart(tmp_path):
    store = Store(tmp_path, create_registry())
    legacy = {"version": 1, "frames": [{"turn": 0}, {"turn": 1}]}
    (store.replays / "legacy.json").write_text(json.dumps(legacy), encoding="utf-8")
    store.start_replay("partial", {"turn": 0})
    store.append_replay_frame("partial", {"turn": 1})
    with (store.replays / "partial.jsonl").open("ab") as stream:
        stream.write(b'{"turn":2,"text":"\xe1\xba')  # Broken UTF-8 and JSON at crash boundary.
    store.save_match({"id": "partial", "game_id": "robot_battle", "status": "running"})
    restarted = Store(tmp_path, create_registry())
    assert restarted.get_replay("legacy") == legacy
    assert restarted.get_replay("partial") == legacy
    assert restarted.get_match("partial")["status"] == "interrupted"
    assert (store.replays / "legacy.json").read_text(encoding="utf-8") == json.dumps(legacy)


def test_long_match_saved_replay_equal_live_without_whole_history_rewrites(tmp_path, authorize_organizer, open_competition):
    with TestClient(create_app(tmp_path, tick_seconds=0)) as client:
        authorize_organizer(client)
        submission = bot(client)
        open_competition(client, rules={"max_turns": 120})
        match = official_match(client, {"bot_a": submission["id"], "bot_b": submission["id"]}).json()
        frames, metadata = watch(client, match["id"])
        assert len(frames) == 121 and metadata["result"]["reason"] == "turn_limit"
        assert client.get(f"/api/matches/{match['id']}/replay").json()["frames"] == frames
        path = tmp_path / "data/replays" / f"{match['id']}.jsonl"
        assert len(path.read_bytes().splitlines()) == 121
        assert not path.with_suffix(".json").exists()
    with TestClient(create_app(tmp_path)) as restarted:
        assert restarted.get(f"/api/matches/{match['id']}/replay").json()["frames"] == frames


def test_failed_replay_write_never_broadcasts_phantom_frame(tmp_path, monkeypatch, authorize_organizer, open_competition):
    with TestClient(create_app(tmp_path, tick_seconds=0)) as client:
        authorize_organizer(client)
        submission = bot(client)
        open_competition(client)

        def disk_error(*args):
            raise OSError("test disk full")

        monkeypatch.setattr(client.app.state.store, "append_replay_frame", disk_error)
        match = official_match(client, {"bot_a": submission["id"], "bot_b": submission["id"]}).json()
        frames, metadata = watch(client, match["id"])
        assert len(frames) == 1 and frames[0]["turn"] == 0
        assert metadata["status"] == "interrupted" and metadata["result"]["reason"] == "server_error"
        assert client.get(f"/api/matches/{match['id']}/replay").json()["frames"] == frames
