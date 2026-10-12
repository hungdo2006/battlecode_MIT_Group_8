"""Run an actual mixed-language match against the running HTTP + WebSocket server.

Usage: python scripts/demo_match.py --a python --b cpp
"""
import argparse
import asyncio
import json
import websockets
from check_lan import Player


async def demo(args):
    player = Player(args.url)
    catalog = await asyncio.to_thread(player.request, "/api/games")
    game_id = args.game or catalog["selected_game_id"]
    bot_a = await asyncio.to_thread(player.request, f"/api/games/{game_id}/samples/{args.a}/submit", {})
    bot_b = await asyncio.to_thread(player.request, f"/api/games/{game_id}/samples/{args.b}/submit", {})
    for bot in (bot_a, bot_b):
        if bot["status"] != "ready":
            raise RuntimeError(bot["logs"])
    payload = {"game_id": game_id, "bot_a": bot_a["id"], "bot_b": bot_b["id"]}
    if args.max_turns is not None or args.rounds is not None:
        await asyncio.to_thread(player.organizer)
        rules = await asyncio.to_thread(player.request, f"/api/games/{game_id}/rules")
        if args.max_turns is not None:
            rules["max_turns"] = args.max_turns
        if args.rounds is not None:
            rules["rounds"] = args.rounds
        payload["rules"] = rules
    match = await asyncio.to_thread(player.request, "/api/matches", payload)
    print(f"MATCH {match['id']}: {bot_a['name']} vs {bot_b['name']}")
    url = args.url.replace("http://", "ws://").replace("https://", "wss://")
    states = []
    async with websockets.connect(f"{url}/ws/matches/{match['id']}") as socket:
        async for raw in socket:
            message = json.loads(raw)
            if message["type"] == "state":
                state = message["state"]
                states.append(state)
                print(f"Turn {state['turn']:03}: actions={json.dumps(state['actions'], ensure_ascii=False)}")
            if message["type"] == "complete":
                print("RESULT:", json.dumps(message["match"]["result"], ensure_ascii=False))
                assert message["match"]["result"]["reason"] != "bot_error", "A sample bot faulted"
                break
    replay = await asyncio.to_thread(player.request, f"/api/matches/{match['id']}/replay")
    assert states == replay["frames"], "Saved replay differs from the live WebSocket feed"
    print(f"VERIFIED: {len(states)} live frames equal saved JSON replay.")
    print(f"REPLAY: {args.url}/api/matches/{match['id']}/replay")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--a", choices=["python", "cpp", "java"], default="python")
    parser.add_argument("--b", choices=["python", "cpp", "java"], default="cpp")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--game", help="Installed game_id; omitted means the organizer's selected game")
    parser.add_argument("--max-turns", type=int)
    parser.add_argument("--rounds", type=int, help="OTT v2 only")
    asyncio.run(demo(parser.parse_args()))
