"""Two independent LAN players upload Python/C++, discover and watch one match.

Run on the host or a second laptop; automation alone does not prove two physical
devices. Each player has its own persistent HTTP cookie jar and WebSocket.
"""
import argparse
import asyncio
from http.cookiejar import CookieJar
import json
import os
import time
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener
from uuid import uuid4

from websockets.asyncio.client import connect


class Player:
    def __init__(self, url):
        self.url = url.rstrip("/")
        self.cookies = CookieJar()
        self.opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(self.cookies))

    def request(self, path, body=None, method=None, raw=False):
        request = Request(self.url + path, data=json.dumps(body).encode() if body is not None else None,
                          headers={"Content-Type": "application/json"},
                          method=method or ("POST" if body is not None else "GET"))
        with self.opener.open(request, timeout=45) as response:
            return response.read() if raw else json.load(response)

    def upload(self, game_id, language, name):
        source = self.request(f"/api/games/{game_id}/samples/{language}", raw=True)
        boundary = "arena-" + uuid4().hex
        parts = []
        for field, value in (("name", name), ("game_id", game_id)):
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"\r\n\r\n{value}\r\n'.encode())
        suffix = {"python": "py", "cpp": "cpp", "java": "java"}[language]
        filename = "Main.java" if language == "java" else "bot." + suffix
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: text/plain\r\n\r\n'.encode())
        parts.extend((source, f"\r\n--{boundary}--\r\n".encode()))
        request = Request(self.url + "/api/bots", data=b"".join(parts), method="POST",
                          headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with self.opener.open(request, timeout=45) as response:
            return json.load(response)

    def cookie_header(self):
        request = Request(self.url + "/")
        self.cookies.add_cookie_header(request)
        return request.get_header("Cookie", "")

    def organizer(self):
        code = os.environ.get("ARENA_ADMIN_CODE")
        if not code:
            raise RuntimeError("This check changes rules; set ARENA_ADMIN_CODE in the shell running the check.")
        return self.request("/api/session/organizer", {"code": code})

    def prepare_competition(self, game_id, rules=None):
        self.organizer()
        self.request("/api/competition/close", {})
        state = self.request("/api/competition")
        deadline = time.monotonic() + 5
        while not state["can_edit"]:
            if time.monotonic() > deadline:
                raise RuntimeError("Existing matches must finish/cancel before configuring a competition.")
            time.sleep(0.05)
            state = self.request("/api/competition")
        self.request("/api/games/selected", {"game_id": game_id}, "PUT")
        if rules is not None:
            self.request(f"/api/games/{game_id}/rules", rules, "PUT")
        return self.request("/api/competition/open", {})


async def watch(player, match_id, after=-1):
    endpoint = player.url.replace("http://", "ws://").replace("https://", "wss://")
    frames, sequences = [], []
    async with connect(f"{endpoint}/ws/matches/{match_id}?after={after}", origin=player.url,
                       additional_headers={"Cookie": player.cookie_header()}) as socket:
        async for raw in socket:
            message = json.loads(raw)
            if message["type"] == "state":
                assert message["seq"] == after + 1 + len(frames)
                frames.append(message["state"])
                sequences.append(message["seq"])
            if message["type"] == "complete":
                return frames, message["match"], sequences
    raise AssertionError("WebSocket closed before completion")


async def check(args):
    a, b = Player(args.url), Player(args.url)
    health = await asyncio.to_thread(a.request, "/api/health")
    assert health["status"] == "ok" and not health["read_only"]
    identities = []
    for player, name in ((a, "LAN Laptop A"), (b, "LAN Laptop B")):
        session = await asyncio.to_thread(player.request, "/api/session", {"name": name}, "PUT")
        identities.append(session["participant"])
    assert identities[0]["id"] != identities[1]["id"]
    assert a.cookie_header() != b.cookie_header()
    game_id = args.game or (await asyncio.to_thread(a.request, "/api/games"))["selected_game_id"]
    if args.max_turns is not None or args.open_competition:
        rules = await asyncio.to_thread(a.request, f"/api/games/{game_id}/rules")
        if args.max_turns is not None:
            rules["max_turns"] = args.max_turns
        await asyncio.to_thread(a.prepare_competition, game_id, rules)
    bots = []
    for index, (player, language) in enumerate(((a, "python"), (b, args.language_b))):
        bot = await asyncio.to_thread(player.upload, game_id, language, f"LAN {language.upper()} {identities[index]['id'][:4]}")
        assert bot["status"] == "ready", bot["logs"]
        assert bot["owner"] == identities[index]
        bots.append(bot)
    discovered = await asyncio.to_thread(b.request, "/api/bots")
    assert {bot["id"] for bot in bots} <= {bot["id"] for bot in discovered}
    payload = {"game_id": game_id, "bot_a": bots[0]["id"], "bot_b": bots[1]["id"]}
    match = await asyncio.to_thread(a.request, "/api/matches", payload)
    assert match["created_by"] == identities[0]
    shared_list = await asyncio.to_thread(b.request, "/api/matches")
    assert match["id"] in {item["id"] for item in shared_list}
    first, second = await asyncio.gather(watch(a, match["id"]), watch(b, match["id"]))
    replay = await asyncio.to_thread(b.request, f"/api/matches/{match['id']}/replay")
    assert first[0] == second[0] == replay["frames"]
    assert first[1]["result"] == second[1]["result"] == replay["match"]["result"]
    assert first[1]["result"]["reason"] != "bot_error"
    after = len(first[0]) // 2
    reconnected = await watch(b, match["id"], after=after)
    assert reconnected[0] == first[0][after + 1:]
    print(f"LAN PASS: {args.url}; distinct sessions; each player uploaded a bot; shared discovery;")
    print(f"2 independent WS spectators; {len(first[0])} frames equal replay; reconnect after={after} passed.")
    print(f"Open on both devices: {args.url}/?match={match['id']}#home")
    print("Result:", json.dumps(replay["match"]["result"], ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--game")
    parser.add_argument("--open-competition", action="store_true", help="Organizer setup/open before demo; requires ARENA_ADMIN_CODE")
    parser.add_argument("--language-b", choices=("cpp", "java"), default="cpp")
    parser.add_argument("--max-turns", type=int, help="Organizer-only override; reads ARENA_ADMIN_CODE from environment")
    asyncio.run(check(parser.parse_args()))
