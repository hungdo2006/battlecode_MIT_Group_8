"""Multi-user workflow, persistent identities and safe read-only proxy mode."""
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from backend.main import create_app
from backend.network import NetworkSettings, demo_host, same_origin
from backend.sessions import COOKIE_NAME

WAIT = b"import sys,json\nfor line in sys.stdin:\n print(json.dumps({'type':'wait'}),flush=True)\n"


def upload(client, name):
    response = client.post("/api/bots", files={"file": ("bot.py", WAIT)},
                           data={"name": name, "game_id": "robot_battle", "owner": "forged"})
    assert response.status_code == 201
    return response.json()


def frames_until_complete(socket):
    frames = []
    while True:
        message = socket.receive_json()
        if message["type"] == "state":
            assert message["seq"] == len(frames)
            frames.append(message["state"])
        if message["type"] == "complete":
            return frames, message["match"]


def test_two_players_upload_discover_watch_and_reconnect(tmp_path):
    app = create_app(tmp_path, tick_seconds=0.025)
    with TestClient(app, base_url="http://192.168.1.20:8000") as a:
        # B shares the running app but has an independent browser cookie jar.
        b = TestClient(app, base_url="http://192.168.1.20:8000")
        b.portal = a.portal  # One server event loop, separate HTTP cookie jars.
        try:
            alice = a.put("/api/session", json={"name": "  Laptop A  "}).json()["participant"]
            bob = b.put("/api/session", json={"name": "Laptop B"}).json()["participant"]
            assert alice["id"] != bob["id"]
            assert a.cookies[COOKIE_NAME] != b.cookies[COOKIE_NAME]
            bot_a, bot_b = upload(a, "A-bot"), upload(b, "B-bot")
            assert bot_a["owner"] == alice and bot_b["owner"] == bob
            assert {bot["id"] for bot in b.get("/api/bots").json()} == {bot_a["id"], bot_b["id"]}
            rules = {"map_size": 7, "initial_hp": 50, "damage": 10, "max_turns": 8}
            created = a.post("/api/matches", json={"bot_a": bot_a["id"], "bot_b": bot_b["id"],
                                                    "game_id": "robot_battle", "rules": rules})
            assert created.status_code == 201
            match = created.json()
            assert match["created_by"] == alice
            assert match["bots"]["B"]["owner"] == bob
            assert b.get("/api/matches").json()[0]["id"] == match["id"]
            endpoint = f"ws://192.168.1.20:8000/ws/matches/{match['id']}"
            origin = {"Origin": "http://192.168.1.20:8000"}
            with a.websocket_connect(endpoint, headers=origin) as first, b.websocket_connect(endpoint, headers=origin) as second:
                assert first.receive_json()["type"] == second.receive_json()["type"] == "hello"
                first_frames, first_meta = frames_until_complete(first)
                second_frames, second_meta = frames_until_complete(second)
            replay = b.get(f"/api/matches/{match['id']}/replay").json()
            assert first_frames == second_frames == replay["frames"]
            assert first_meta["result"] == second_meta["result"] == replay["match"]["result"]
            assert len(first_frames) == 9
            with b.websocket_connect(endpoint + "?after=4", headers=origin) as reconnect:
                assert reconnect.receive_json()["type"] == "hello"
                assert [reconnect.receive_json()["seq"] for _ in range(4)] == [5, 6, 7, 8]
                assert reconnect.receive_json()["type"] == "complete"
        finally:
            b.close()


def test_cookie_identity_survives_restart_without_exposing_tokens(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        response = client.get("/api/session")
        participant = response.json()["participant"]
        cookie = client.cookies[COOKIE_NAME]
        assert "httponly" in response.headers["set-cookie"].lower()
        assert "samesite=lax" in response.headers["set-cookie"].lower()
        assert response.headers["cache-control"] == "no-store"
        assert cookie not in response.text
        assert cookie not in (tmp_path / "data/sessions.json").read_text(encoding="utf-8")
        assert client.put("/api/session", json={"name": "Nhóm mạng"}).status_code == 200
        assert client.put("/api/session", json={"name": " "}).status_code == 422
        assert client.put("/api/session", json={"name": "x\ny"}).status_code == 422
        assert client.put("/api/session", json={"name": "x" * 33}).status_code == 422
        assert client.put("/api/session", json={"name": "X", "id": "forged"}).status_code == 422
    with TestClient(create_app(tmp_path)) as restarted:
        restarted.cookies.set(COOKIE_NAME, cookie)
        identity = restarted.get("/api/session").json()["participant"]
        assert identity == {"id": participant["id"], "name": "Nhóm mạng"}
    with TestClient(create_app(tmp_path)) as forged:
        forged.cookies.set(COOKIE_NAME, participant["id"])
        assert forged.get("/api/session").json()["participant"]["id"] != participant["id"]


def test_sample_cache_is_per_player_but_still_compiles_once(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as a:
        b = TestClient(app)
        b.portal = a.portal
        try:
            first = a.post("/api/samples/python/submit").json()
            again = a.post("/api/samples/python/submit").json()
            other = b.post("/api/samples/python/submit").json()
            assert first["id"] == again["id"] != other["id"]
            assert first["owner"]["id"] != other["owner"]["id"]
        finally:
            b.close()


def test_expired_session_is_replaced(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        original = client.get("/api/session").json()["participant"]
        record = next(iter(client.app.state.sessions.records.values()))
        record["expires_at"] = 0
        assert client.get("/api/session").json()["participant"]["id"] != original["id"]


def test_read_only_domain_replay_and_proxy_https(tmp_path):
    with TestClient(create_app(tmp_path, tick_seconds=0.001)) as lan:
        bot = upload(lan, "trusted")
        match = lan.post("/api/matches", json={"bot_a": bot["id"], "bot_b": bot["id"], "rules": {"max_turns": 2}}).json()
        with lan.websocket_connect(f"/ws/matches/{match['id']}") as ws:
            ws.receive_json()
            frames, _ = frames_until_complete(ws)
    config = NetworkSettings(read_only=True, allowed_hosts=("arena.example.com",))
    app = create_app(tmp_path, network=config)
    # Simulate the headers passed by a trusted TLS-terminating reverse proxy.
    proxy = ProxyHeadersMiddleware(app, trusted_hosts=["testclient"])
    with TestClient(proxy, base_url="http://arena.example.com") as client:
        headers = {"X-Forwarded-Proto": "https", "Origin": "https://arena.example.com"}
        response = client.get("/api/session", headers=headers)
        assert response.status_code == 200
        assert "secure" in response.headers["set-cookie"].lower()
        assert response.json()["read_only"] is True
        assert client.get("/api/network", headers=headers).json() == {
            "origin": "https://arena.example.com", "read_only": True, "lan_urls": []}
        assert client.get(f"/api/matches/{match['id']}/replay", headers=headers).json()["frames"] == frames
        endpoints = [("POST", "/api/bots"), ("POST", "/api/samples/python/submit"),
                     ("POST", "/api/games/ott_v2/samples/java/submit"), ("POST", "/api/matches"),
                     ("PUT", "/api/rules"), ("PUT", "/api/games/selected"),
                     ("PUT", "/api/games/ott_v2/rules"), ("POST", "/api/games/ott_v2/rules/reset")]
        for method, path in endpoints:
            assert client.request(method, path, headers=headers, json={}).status_code == 403, path
        with client.websocket_connect(f"ws://arena.example.com/ws/matches/{match['id']}", headers=headers) as ws:
            assert ws.receive_json()["type"] == "hello"
            replay_frames, _ = frames_until_complete(ws)
            assert replay_frames == frames
        assert client.get("/api/health", headers={"Host": "evil.example", "X-Forwarded-Proto": "https"}).status_code == 403
        assert client.get("/api/health", headers={**headers, "Origin": "http://arena.example.com"}).status_code == 403


def test_untrusted_forwarded_scheme_is_not_accepted(tmp_path):
    app = create_app(tmp_path)
    proxy = ProxyHeadersMiddleware(app, trusted_hosts=["127.0.0.1"])
    with TestClient(proxy, base_url="http://192.168.1.20:8000") as client:
        response = client.get("/api/session", headers={"X-Forwarded-Proto": "https"})
        assert response.status_code == 200 and "secure" not in response.headers["set-cookie"].lower()
        assert client.get("/api/health", headers={"X-Forwarded-Proto": "https", "Origin": "https://192.168.1.20:8000"}).status_code == 403
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/matches/unknown", headers={"Origin": "https://evil.example"}):
                pass


def test_network_configuration_and_origin_validation(monkeypatch):
    with pytest.raises(ValueError, match="READ_ONLY"):
        NetworkSettings(allowed_hosts=("arena.example.com",))
    with pytest.raises(ValueError):
        NetworkSettings(read_only=True, allowed_hosts=("*.example.com",))
    monkeypatch.setenv("ARENA_READ_ONLY", "1")
    monkeypatch.setenv("ARENA_ALLOWED_HOSTS", "arena.example.com")
    settings = NetworkSettings.from_environment()
    assert settings.read_only and settings.allows_host("arena.example.com:443")
    assert not settings.allows_host("evil.example")
    assert not demo_host("attacker@192.168.1.2")
    assert not demo_host("192.168.1.2/path")
    assert same_origin("https://arena.example.com:443", "arena.example.com", "https")
    assert same_origin("http://[::1]:8000", "[::1]:8000", "ws")
    assert not same_origin("https://arena.example.com", "arena.example.com", "http")
    assert not same_origin("http://192.168.1.2:8001", "192.168.1.2:8000", "ws")


def test_lan_guide_and_runtime_network_info(tmp_path):
    with TestClient(create_app(tmp_path), base_url="http://192.168.1.20:8000") as client:
        assert "MULTI-CLIENT" in client.get("/lan").text
        info = client.get("/api/network").json()
        assert info["origin"] == "http://192.168.1.20:8000"
        assert info["read_only"] is False
