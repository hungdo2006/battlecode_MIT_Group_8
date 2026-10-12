"""Optional real Chrome QA: separate sessions, uploads, discovery and WS playback."""
import argparse
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent


def main(args):
    output = ROOT / "docs/screenshots/network"
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        contexts = [browser.new_context(viewport={"width": 1440, "height": 1000}) for _ in range(2)]
        pages = [context.new_page() for context in contexts]
        errors = []
        sockets = [[], []]
        organizer = playwright.request.new_context(base_url=args.url)
        original_rules = None
        original_game = None

        def screenshot(page, filename):
            page.evaluate("window.scrollTo(0, 0)")
            page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => resolve()))")
            page.screenshot(path=str(output / filename), full_page=True)
        try:
            for index, page in enumerate(pages):
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("websocket", lambda socket, index=index: sockets[index].append(socket.url))
                page.goto(args.url)
                page.get_by_text("SYSTEM ONLINE", exact=True).wait_for()
                page.locator("#session-name").fill(f"Laptop {'AB'[index]}")
                page.locator("#session-form button").click()
                page.wait_for_function("name => app.participant?.name === name", arg=f"Laptop {'AB'[index]}")
            identities = [page.evaluate("app.participant") for page in pages]
            assert identities[0]["id"] != identities[1]["id"]
            assert contexts[0].cookies()[0]["value"] != contexts[1].cookies()[0]["value"]
            a, b = pages
            if not os.environ.get("ARENA_ADMIN_CODE"):
                raise RuntimeError("Set ARENA_ADMIN_CODE for the separate Organizer fixture.")
            assert organizer.post("/api/session/organizer", data={"code": os.environ["ARENA_ADMIN_CODE"]}).ok
            assert a.evaluate("app.role") == b.evaluate("app.role") == "player"
            catalog = organizer.get("/api/games").json()
            original_game = catalog["selected_game_id"]
            original_rules = organizer.get(f"/api/games/{args.game}/rules").json()
            # Give B time to discover/join the live match through the 2-second poll.
            demo_rules = ({"map_size": 18, "initial_hp": 200, "damage": 10, "max_turns": 60}
                          if args.game == "robot_battle" else {"max_turns": 60, "rounds": 2})
            assert organizer.put(f"/api/games/{args.game}/rules", data=demo_rules).ok
            bots = []
            for index, page in enumerate(pages):
                page.locator('.nav-item[data-view="upload"]').click()
                page.locator("#upload-game").select_option(args.game)
                page.wait_for_function("game => app.selectedGameId === game && !app.switchingGame", arg=args.game)
                form = page.locator("#upload-form")
                form.locator('[name="name"]').fill(f"NET {'AB'[index]} {identities[index]['id'][:4]}")
                filename = "runner.py" if index == 0 and args.game == "ott_v2" else "hunter.py" if index == 0 else "runner.cpp" if args.game == "ott_v2" else "hunter.cpp"
                source = ROOT / "samples" / ("ott_v2" if args.game == "ott_v2" else "") / filename
                form.locator("#bot-file").set_input_files(str(source))
                with page.expect_response(lambda response: response.url.endswith("/api/bots") and response.request.method == "POST", timeout=45000) as uploaded:
                    form.locator('[type="submit"]').click()
                bot = uploaded.value.json()
                assert bot["status"] == "ready", bot["logs"]
                assert bot["owner"] == identities[index]
                bots.append(bot)
            # Ordinary selection is a browser preference, not a global default mutation.
            other_game = "ott_v2" if args.game == "robot_battle" else "robot_battle"
            a.locator("#upload-game").select_option(other_game)
            a.wait_for_function("game => app.selectedGameId === game && !app.switchingGame", arg=other_game)
            assert b.evaluate("app.selectedGameId") == args.game
            assert organizer.get("/api/games").json()["selected_game_id"] == original_game
            for page, expected in ((a, other_game), (b, args.game)):
                page.reload(); page.get_by_text("SYSTEM ONLINE", exact=True).wait_for()
                assert page.evaluate("app.selectedGameId") == expected
            assert organizer.put("/api/games/selected", data={"game_id": other_game}).ok
            b.reload(); b.get_by_text("SYSTEM ONLINE", exact=True).wait_for()
            assert b.evaluate("app.selectedGameId") == args.game
            assert organizer.put("/api/games/selected", data={"game_id": original_game}).ok
            a.locator("#workspace-game-select").select_option(args.game)
            a.wait_for_function("game => app.selectedGameId === game && !app.switchingGame", arg=args.game)
            assert a.request.put(args.url + f"/api/games/{args.game}/rules", data={"max_turns": 1}).status == 403
            a.wait_for_function("id => app.bots.some(bot => bot.id === id)", arg=bots[1]["id"], timeout=10000)
            b.wait_for_function("id => app.bots.some(bot => bot.id === id)", arg=bots[0]["id"], timeout=10000)
            assert "Laptop B" in a.locator("#bot-library").inner_text()
            screenshot(a, "shared-bots.png")
            a.locator('.nav-item[data-view="create"]').click()
            a.locator("#create-match .bot-a").select_option(bots[0]["id"])
            a.locator("#create-match .bot-b").select_option(bots[1]["id"])
            b.locator('.nav-item[data-view="watch"]').click()
            a.locator("#create-match [type=submit]").click()
            a.wait_for_function("app.match?.id && app.frames.length > 0")
            match_id = a.evaluate("app.match.id")
            a.locator("#play-pause").click()
            paused_cursor = a.evaluate("app.cursor")
            row = b.locator(f'#all-matches [data-match-id="{match_id}"]')
            row.wait_for(timeout=10000)
            assert "Laptop A" in row.inner_text()
            assert row.locator("button").inner_text().startswith("Live"), "Use enough turns so B joins while running."
            row.locator("button").click()
            b.wait_for_function("id => app.match?.id === id && app.frames.length > 1", arg=match_id)
            a.wait_for_function("app.match?.status === 'completed'", timeout=45000)
            b.wait_for_function("app.match?.status === 'completed'", timeout=45000)
            assert a.evaluate("app.cursor") == paused_cursor
            assert b.evaluate("app.cursor") > 0
            first, second = a.evaluate("app.frames"), b.evaluate("app.frames")
            assert first == second
            replay = b.request.get(args.url + f"/api/matches/{match_id}/replay").json()
            assert first == replay["frames"]
            assert replay["match"]["created_by"] == identities[0]
            assert replay["match"]["result"]["reason"] != "bot_error"
            for index in range(2):
                assert any(f"/ws/matches/{match_id}" in url for url in sockets[index])
            b.locator("#play-pause").click()
            screenshot(b, "client-b-live.png")
            a.locator('.nav-item[data-view="watch"]').click()
            screenshot(a, "shared-match.png")
            b.goto(args.url + "/lan")
            b.locator("#current-origin").filter(has_text="WEBSITE").wait_for()
            screenshot(b, "lan-guide.png")
            b.set_viewport_size({"width": 390, "height": 844})
            assert b.evaluate("document.documentElement.scrollWidth <= innerWidth")
            b.goto(args.url)
            b.get_by_text("SYSTEM ONLINE", exact=True).wait_for()
            assert b.evaluate("app.participant.id") == identities[1]["id"]
            assert b.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert not errors, errors
            print(f"NETWORK UI PASS: {args.game}; two Players; protected rules; isolated game choice after reload/default change; uploads/discovery; two WS; independent Pause; replay; guide/mobile; match={match_id}")
        finally:
            if original_rules is not None:
                organizer.put(f"/api/games/{args.game}/rules", data=original_rules)
                organizer.put("/api/games/selected", data={"game_id": original_game})
            organizer.dispose()
            browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--game", choices=("robot_battle", "ott_v2"), default="robot_battle")
    main(parser.parse_args())
