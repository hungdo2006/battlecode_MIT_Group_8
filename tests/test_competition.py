from workflow import official_match
"""Competition authority, persistence, broadcast and concurrent admission."""
from concurrent.futures import ThreadPoolExecutor
import asyncio
import json
import threading

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.storage import Store
from backend.engine import create_registry

WAIT = b"import sys,json\nfor line in sys.stdin:\n print(json.dumps({'type':'wait'}),flush=True)\n"


@pytest.fixture
def room(tmp_path, authorize_organizer):
    with TestClient(create_app(tmp_path, tick_seconds=0.04)) as organizer:
        authorize_organizer(organizer)
        player = TestClient(organizer.app)
        player.portal = organizer.portal
        try:
            yield organizer, player
        finally:
            player.close()


def upload(client, game_id="robot_battle"):
    response = client.post("/api/bots", files={"file": ("wait.py", WAIT)}, data={"game_id": game_id})
    assert response.status_code == 201, response.text
    return response.json()


def create_match(client, bot, **extra):
    return official_match(client, {"bot_a": bot["id"], "bot_b": bot["id"], **extra})


def watch(client, match_id):
    frames = []
    with client.websocket_connect(f"/ws/matches/{match_id}") as socket:
        while True:
            message = socket.receive_json()
            if message["type"] == "state":
                frames.append(message["state"])
            if message["type"] == "complete":
                return frames, message["match"]


def next_state(socket, predicate):
    for _ in range(20):
        message = socket.receive_json()
        if message["type"] == "competition" and predicate(message["state"]):
            return message["state"]
    raise AssertionError("Expected competition update missing")


def test_default_closed_player_cannot_open_close_or_select(room):
    organizer, player = room
    state = player.get("/api/competition").json()
    assert state["phase"] == "setup" and state["active_rules_snapshot"] is None
    for path in ("/api/competition/open", "/api/competition/close"):
        assert player.post(path).status_code == 403
    assert player.put("/api/games/selected", json={"game_id": "ott_v2"}).status_code == 403
    bot = upload(player)
    assert create_match(player, bot).status_code == 409
    assert organizer.get("/api/matches").json() == []


def test_locked_game_and_rules_cannot_be_spoofed(room, open_competition):
    organizer, player = room
    bot = upload(player)
    snapshot = open_competition(organizer, rules={"max_turns": 3, "initial_hp": 60})["active_rules_snapshot"]
    for actor in (organizer, player):
        assert actor.post("/api/matches", json={"bot_a": bot["id"], "bot_b": bot["id"], "game_id": "ott_v2"}).status_code == 403
        assert actor.post("/api/matches", json={"bot_a": bot["id"], "bot_b": bot["id"], "game": "ott_v2"}).status_code == 403
        override = create_match(actor, bot, rules={"max_turns": 1})
        assert override.status_code == 403
    assert player.put("/api/rules", json={"max_turns": 1}).status_code == 403
    for method, path, payload in (("PUT", "/api/rules", {"max_turns": 1}),
                                 ("PUT", "/api/games/robot_battle/rules", {"max_turns": 1}),
                                 ("PUT", "/api/games/ott_v2/rules", {"rounds": 5}),
                                 ("POST", "/api/games/robot_battle/rules/reset", {}),
                                 ("POST", "/api/games/ott_v2/rules/reset", {}),
                                 ("PUT", "/api/games/selected", {"game_id": "ott_v2"})):
        assert organizer.request(method, path, json=payload).status_code == 409
    response = create_match(player, bot)
    assert response.status_code == 200
    frames, match = watch(player, response.json()["id"])
    assert match["game_id"] == "robot_battle" and match["rules_snapshot"] == snapshot
    assert match["rules"] == snapshot and all(f["rules"] == snapshot for f in frames)
    assert organizer.get("/api/competition").json()["active_rules_snapshot"] == snapshot


def test_submissions_and_sample_cache_only_current_game(room, open_competition):
    organizer, player = room
    first = player.post("/api/samples/python/submit").json()
    open_competition(organizer)
    assert player.post("/api/samples/python/submit").json()["id"] == first["id"]
    for actor in (organizer, player):
        response = actor.post("/api/bots", files={"file": ("wrong.py", WAIT)}, data={"game_id": "ott_v2"})
        assert response.status_code == (403 if actor is organizer else 409)
        assert actor.post("/api/games/ott_v2/samples/python/submit").status_code == (403 if actor is organizer else 409)
    assert organizer.post("/api/competition/close").status_code == 200
    assert organizer.put("/api/games/selected", json={"game_id": "ott_v2"}).status_code == 200
    # Legacy sample alias follows server-selected game, not a caller's old preference.
    ott = player.post("/api/samples/python/submit").json()
    assert ott["game_id"] == "ott_v2"
    assert {b["id"] for b in organizer.get("/api/bots").json()} == {first["id"], ott["id"]}


def test_close_blocks_new_matches_but_waits_for_running_and_cancel(room, open_competition):
    organizer, player = room
    open_competition(organizer, rules={"max_turns": 50})
    bot = upload(player)
    match = create_match(player, bot).json()
    closed = organizer.post("/api/competition/close").json()
    assert closed["phase"] == "draining" and closed["competition_locked"] is False
    assert create_match(organizer, bot).status_code == 409
    assert create_match(player, bot).status_code == 409
    assert organizer.put("/api/games/selected", json={"game_id": "ott_v2"}).status_code == 409
    assert organizer.put("/api/rules", json={"max_turns": 1}).status_code == 409
    assert organizer.post("/api/competition/open").status_code == 409
    assert player.post(f"/api/matches/{match['id']}/cancel").status_code == 403
    canceled = organizer.post(f"/api/matches/{match['id']}/cancel")
    assert canceled.status_code == 200
    assert canceled.json()["status"] == "interrupted"
    assert canceled.json()["result"]["reason"] == "organizer_cancelled"
    assert organizer.get("/api/competition").json()["phase"] == "setup"
    assert organizer.put("/api/games/selected", json={"game_id": "ott_v2"}).status_code == 200
    assert organizer.put("/api/games/ott_v2/rules", json={"rounds": 2}).status_code == 200
    assert organizer.post("/api/competition/open").status_code == 200
    assert canceled.json()["game_id"] == "robot_battle"


def test_two_ws_clients_late_join_and_restart_persistence(tmp_path, room, open_competition, stop_backend):
    organizer, player = room
    with organizer.websocket_connect("/ws/competition") as a, player.websocket_connect("/ws/competition") as b:
        initial_a = a.receive_json()["state"]
        initial_b = b.receive_json()["state"]
        assert initial_a == initial_b and initial_a["phase"] == "setup"
        opened = open_competition(organizer, "ott_v2", {"max_turns": 8, "rounds": 2})
        assert next_state(a, lambda s: s["phase"] == "open") == opened
        assert next_state(b, lambda s: s["phase"] == "open") == opened
        with player.websocket_connect("/ws/competition") as late:
            assert late.receive_json()["state"] == opened
    stop_backend(organizer)
    with TestClient(create_app(tmp_path)) as restarted:
        state = restarted.get("/api/competition").json()
        assert state["competition_locked"] is True and state["selected_game_id"] == "ott_v2"
        assert state["active_rules_snapshot"] == opened["active_rules_snapshot"]
        with restarted.websocket_connect("/ws/competition") as socket:
            assert socket.receive_json()["state"] == state
    saved = json.loads((tmp_path / "data/rules.json").read_text(encoding="utf-8"))
    assert saved["competition_locked"] and saved["active_rules_snapshot"] == opened["active_rules_snapshot"]


def test_natural_completion_broadcasts_unlocked_setup(room, open_competition):
    organizer, player = room
    open_competition(organizer, rules={"max_turns": 3})
    bot = upload(player)
    with player.websocket_connect("/ws/competition") as socket:
        socket.receive_json()
        match = create_match(player, bot).json()
        organizer.post("/api/competition/close")
        draining = next_state(socket, lambda s: s["phase"] == "draining")
        assert draining["pending_matches"] == 1
        setup = next_state(socket, lambda s: s["phase"] == "setup")
        assert setup["pending_matches"] == 0
        frames, meta = watch(player, match["id"])
        assert len(frames) == 4 and meta["status"] == "completed"


def test_old_replay_and_incompatible_bot_retained_after_switch(room, open_competition):
    organizer, player = room
    opened = open_competition(organizer, rules={"max_turns": 2})
    robot = upload(player)
    match = create_match(player, robot).json()
    frames, _ = watch(player, match["id"])
    # Complete is sent before final bot cleanup; wait on the real task, not a timer.
    organizer.post("/api/competition/close")
    async def finish_cleanup():
        await asyncio.gather(*list(organizer.app.state.manager.tasks), return_exceptions=True)
    organizer.portal.call(finish_cleanup)
    open_competition(organizer, "ott_v2")
    assert player.put("/api/players/active-bot", json={"bot_id": robot["id"]}).status_code == 409
    payload = player.get(f"/api/matches/{match['id']}/replay").json()
    assert payload["frames"] == frames
    assert payload["match"]["game_id"] == "robot_battle"
    assert payload["match"]["rules_snapshot"] == opened["active_rules_snapshot"]
    assert robot["id"] in {b["id"] for b in player.get("/api/bots").json()}


def test_compile_race_rechecks_game_before_commit(tmp_path, room, monkeypatch):
    organizer, player = room
    import backend.main as module
    original = module.prepare_submission
    started, release = threading.Event(), threading.Event()

    def slow_compile(*args):
        result = original(*args)
        started.set()
        assert release.wait(5)
        return result

    monkeypatch.setattr(module, "prepare_submission", slow_compile)
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(player.post, "/api/bots", files={"file": ("wait.py", WAIT)}, data={"game_id": "robot_battle"})
        try:
            assert started.wait(5)
            assert organizer.put("/api/games/selected", json={"game_id": "ott_v2"}).status_code == 200
            assert organizer.post("/api/competition/open").status_code == 200
        finally:
            release.set()
        assert pending.result(timeout=5).status_code == 409
    assert organizer.get("/api/bots").json() == []
    assert not list((tmp_path / "uploads").iterdir())


def test_match_admission_and_close_are_serialized(room, open_competition, monkeypatch):
    organizer, player = room
    open_competition(organizer, rules={"max_turns": 50})
    bot = upload(player)
    started, release = threading.Event(), threading.Event()
    original = organizer.app.state.store.save_match

    def slow_save(meta):
        if meta["status"] == "queued":
            started.set()
            assert release.wait(5)
        original(meta)

    monkeypatch.setattr(organizer.app.state.store, "save_match", slow_save)
    with ThreadPoolExecutor(max_workers=2) as executor:
        start = executor.submit(create_match, player, bot)
        assert started.wait(5)
        close = executor.submit(organizer.post, "/api/competition/close")
        release.set()
        match = start.result(timeout=5)
        assert match.status_code == 200
        assert close.result(timeout=5).json()["phase"] == "draining"
    assert create_match(player, bot).status_code == 409
    assert organizer.put("/api/games/selected", json={"game_id": "ott_v2"}).status_code == 409
    assert organizer.post(f"/api/matches/{match.json()['id']}/cancel").status_code == 200


def test_queued_cancel_persists_valid_interrupted_state(room, open_competition, monkeypatch):
    organizer, player = room
    open_competition(organizer)
    bot = upload(player)

    async def queue_only(*args):
        import asyncio
        await asyncio.Event().wait()

    monkeypatch.setattr(organizer.app.state.manager, "_run", queue_only)
    match = create_match(player, bot).json()
    assert organizer.get(f"/api/matches/{match['id']}").json()["status"] == "queued"
    organizer.post("/api/competition/close")
    assert organizer.put("/api/games/selected", json={"game_id": "ott_v2"}).status_code == 409
    canceled = organizer.post(f"/api/matches/{match['id']}/cancel").json()
    assert canceled["status"] == "interrupted" and canceled["result"]["reason"] == "organizer_cancelled"
    assert organizer.get("/api/competition").json()["can_edit"]


def test_terminal_match_cannot_be_recanceled_during_bot_cleanup(room, open_competition, monkeypatch):
    from backend.runner import BotProcess
    organizer, player = room
    open_competition(organizer, rules={"max_turns": 1})
    bot = upload(player)
    started, release = threading.Event(), threading.Event()
    original_close = BotProcess.close
    def slow_close(process):
        started.set()
        assert release.wait(5)
        original_close(process)
    monkeypatch.setattr(BotProcess, "close", slow_close)
    try:
        match = create_match(player, bot).json()
        frames, completed = watch(player, match["id"])
        assert started.wait(5) and completed["status"] == "completed"
        assert organizer.post("/api/competition/close").json()["phase"] == "draining"
        assert organizer.post(f"/api/matches/{match['id']}/cancel").status_code == 409
        assert organizer.put("/api/games/selected", json={"game_id": "ott_v2"}).status_code == 409
        assert player.get(f"/api/matches/{match['id']}/replay").json()["frames"] == frames
    finally:
        release.set()
        async def finish_cleanup():
            await asyncio.gather(*list(organizer.app.state.manager.tasks), return_exceptions=True)
        organizer.portal.call(finish_cleanup)
    assert organizer.get("/api/competition").json()["can_edit"]
    assert player.get(f"/api/matches/{match['id']}").json() == completed


def test_invalid_locked_persistence_does_not_silently_select_another_game(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "rules.json").write_text(json.dumps({"selected_game_id": "missing", "competition_locked": True, "active_rules_snapshot": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="không còn"):
        Store(tmp_path, create_registry())


def test_failed_config_write_does_not_open_in_memory(tmp_path, monkeypatch):
    store = Store(tmp_path, create_registry())
    write_config = store._save_config
    before = store.get_competition()
    def fail_write():
        raise OSError("test config disk full")
    monkeypatch.setattr(store, "_save_config", fail_write)
    with pytest.raises(OSError):
        store.open_competition()
    assert store.get_competition() == before
    with pytest.raises(OSError):
        store.select_game("ott_v2")
    assert store.get_competition() == before
    monkeypatch.setattr(store, "_save_config", write_config)
    store.open_competition()
    store.close_competition()
    previous_closed_snapshot = store.get_competition()
    monkeypatch.setattr(store, "_save_config", fail_write)
    with pytest.raises(OSError):
        store.open_competition()
    assert store.get_competition() == previous_closed_snapshot
