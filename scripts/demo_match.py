"""Run an actual mixed-language match against the running HTTP + WebSocket server.

Usage: python scripts/demo_match.py --a python --b cpp
"""
import argparse
import asyncio
import json
from check_lan import Player, presence, invited_match, watch


async def demo(args):
    player, opponent, organizer = Player(args.url), Player(args.url), Player(args.url)
    await asyncio.to_thread(organizer.organizer)
    catalog = await asyncio.to_thread(player.request, "/api/games")
    game_id = args.game or catalog["selected_game_id"]
    if args.open_competition or args.max_turns is not None or args.rounds is not None:
        rules = await asyncio.to_thread(player.request, f"/api/games/{game_id}/rules")
        if args.max_turns is not None:
            rules["max_turns"] = args.max_turns
        if args.rounds is not None:
            rules["rounds"] = args.rounds
        await asyncio.to_thread(organizer.prepare_competition, game_id, rules)
    bot_a = await asyncio.to_thread(player.request, f"/api/games/{game_id}/samples/{args.a}/submit", {})
    bot_b = await asyncio.to_thread(opponent.request, f"/api/games/{game_id}/samples/{args.b}/submit", {})
    for bot in (bot_a, bot_b):
        if bot["status"] != "ready":
            raise RuntimeError(bot["logs"])
    async with presence(organizer), presence(player), presence(opponent):
        match = await invited_match(organizer, player, opponent, [bot_a, bot_b])
        print(f"MATCH {match['id']}: {bot_a['name']} vs {bot_b['name']}")
        streams = await asyncio.gather(*(watch(p, match['id']) for p in (organizer, player, opponent)))
        assert streams[0] == streams[1] == streams[2]
        states = streams[0][0]
        print("RESULT:", json.dumps(streams[0][1]["result"], ensure_ascii=False))
        assert streams[0][1]["result"]["reason"] != "bot_error"
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
    parser.add_argument("--open-competition", action="store_true", help="Organizer config/open; reads ARENA_ADMIN_CODE")
    parser.add_argument("--max-turns", type=int)
    parser.add_argument("--rounds", type=int, help="OTT v2 only")
    asyncio.run(demo(parser.parse_args()))
