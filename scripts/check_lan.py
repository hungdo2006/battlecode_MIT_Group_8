"""Exercise HTTP and two independent WebSocket spectators at a LAN URL.

Run on another group laptop, or on the host to test its private IPv4 listener:
python scripts/check_lan.py --url http://HOST-LAN-IP:8000 --game ott_v2
No claim of two physical devices is made by this automated client check.
"""
import argparse
import asyncio
import json
from urllib.request import ProxyHandler, Request, build_opener
import websockets


def request(base, path, body=None):
    call = Request(base.rstrip("/") + path,
                   data=json.dumps(body).encode() if body is not None else None,
                   headers={"Content-Type": "application/json"},
                   method="POST" if body is not None else "GET")
    with build_opener(ProxyHandler({})).open(call, timeout=40) as response:
        return json.load(response)


async def watch(url, match_id):
    endpoint = url.rstrip("/").replace("http://", "ws://").replace("https://", "wss://")
    frames = []
    async with websockets.connect(f"{endpoint}/ws/matches/{match_id}", origin=url.rstrip("/")) as socket:
        async for raw in socket:
            message = json.loads(raw)
            if message["type"] == "state":
                assert message["seq"] == len(frames)
                frames.append(message["state"])
            if message["type"] == "complete":
                return frames, message["match"]
    raise AssertionError("WebSocket closed before completion")


async def check(args):
    health = await asyncio.to_thread(request, args.url, "/api/health")
    assert health["status"] == "ok"
    game_id = args.game or (await asyncio.to_thread(request, args.url, "/api/games"))["selected_game_id"]
    bots = []
    for language in ("python", "cpp"):
        bot = await asyncio.to_thread(request, args.url, f"/api/games/{game_id}/samples/{language}/submit", {})
        assert bot["status"] == "ready", bot["logs"]
        bots.append(bot)
    rules = await asyncio.to_thread(request, args.url, f"/api/games/{game_id}/rules")
    rules["max_turns"] = args.max_turns
    match = await asyncio.to_thread(request, args.url, "/api/matches", {
        "game_id": game_id, "bot_a": bots[0]["id"], "bot_b": bots[1]["id"], "rules": rules})
    first, second = await asyncio.gather(watch(args.url, match["id"]), watch(args.url, match["id"]))
    replay = await asyncio.to_thread(request, args.url, f"/api/matches/{match['id']}/replay")
    assert first[0] == second[0] == replay["frames"]
    assert first[1]["result"] == second[1]["result"] == replay["match"]["result"]
    assert first[1]["result"]["reason"] != "bot_error"
    print(f"LAN PASS: {args.url}; 2 independent WS spectators; {len(first[0])} frames equal persisted replay.")
    print(f"Open on both devices: {args.url}/?match={match['id']}#home")
    print("Result:", json.dumps(replay["match"]["result"], ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--game")
    parser.add_argument("--max-turns", type=int, default=30)
    asyncio.run(check(parser.parse_args()))
