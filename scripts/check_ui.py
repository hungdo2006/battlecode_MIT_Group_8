"""Optional real Chrome QA of the multi-game platform (no API mocks).

pip install playwright
python scripts/check_ui.py --url http://127.0.0.1:8000 --spectator-url http://HOST-LAN-IP:8000
Uses installed Chrome. Creates real submissions/matches, then restores configs.
"""
import argparse
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent


def main(args):
    output = ROOT / "docs/screenshots/v2"
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width": 1512, "height": 1080})
        spectator_context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        catalog = page.request.get(args.url + "/api/games").json()
        original_game = catalog["selected_game_id"]
        original_competition = page.request.get(args.url + "/api/competition").json()
        original_rules = {game["game_id"]: game["rules"] for game in catalog["games"]}

        def screenshot(name):
            page.wait_for_function("getComputedStyle(document.querySelector('.view.active')).opacity === '1'")
            page.evaluate("window.scrollTo(0,0)")
            page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => resolve()))")
            page.screenshot(path=str(output / name), full_page=True)

        def select_game(game_id):
            page.locator(".nav-item[data-view=rules]").click()
            page.locator(f'.game-card[data-game-id="{game_id}"]').click()
            page.wait_for_function("id => app.selectedGameId === id && !app.switchingGame", arg=game_id)

        def close_room():
            assert page.request.post(args.url + "/api/competition/close").ok
            page.wait_for_function("app.competition?.phase === 'setup'", timeout=45000)

        def open_room():
            page.locator("#competition-open").click()
            page.wait_for_function("app.competition?.competition_locked && !app.competitionBusy")
            assert page.locator("#rules-form [type=submit]").is_disabled()
            assert page.locator("#workspace-game-select").is_disabled()

        def save_rules(values):
            for key, value in values.items():
                page.locator(f'#rules-form [name="{key}"]').fill(str(value))
            page.locator("#rules-form [type=submit]").click()
            page.wait_for_function("values => Object.entries(values).every(([key,value]) => app.rules[key] === value)", arg=values)

        def seed():
            page.locator(".nav-item[data-view=home]").click()
            page.locator("#seed-samples").click()
            page.wait_for_function("!document.querySelector('#seed-samples').disabled", timeout=90000)

        def launch(game_id):
            bots = page.request.get(args.url + f"/api/bots?game_id={game_id}").json()
            a = next(bot for bot in bots if bot["language"] == "py" and bot["status"] == "ready")
            b = next(bot for bot in bots if bot["language"] == "cpp" and bot["status"] == "ready")
            page.locator("#quick-match .bot-a").select_option(a["id"])
            page.locator("#quick-match .bot-b").select_option(b["id"])
            page.locator("#quick-match [type=submit]").click()
            page.wait_for_function("id => app.match?.game_id === id && app.frames.length > 1", arg=game_id, timeout=15000)
            page.locator("#play-pause").click()
            return page.evaluate("app.match.id")

        def replay_to_end():
            page.locator("#play-reset").click()
            assert page.locator("#timeline").input_value() == "0"
            page.locator("#play-speed").select_option("4")
            page.locator("#play-start").click()
            page.locator("#victory-overlay").wait_for(state="visible", timeout=30000)

        try:
            page.goto(args.url)
            page.get_by_text("SYSTEM ONLINE", exact=True).wait_for()
            if not os.environ.get("ARENA_ADMIN_CODE"):
                raise RuntimeError("Set ARENA_ADMIN_CODE to run Organizer UI checks.")
            page.locator("#organizer-toggle").click()
            page.locator("#organizer-code").fill(os.environ["ARENA_ADMIN_CODE"])
            page.locator("#organizer-form [type=submit]").click()
            page.wait_for_function("app.role === 'organizer'")
            assert page.locator("#organizer-code").input_value() == ""
            close_room()
            select_game("robot_battle")
            assert page.locator("#rules-fields [name=initial_hp]").count() == 1
            assert page.locator("#rules-fields [name=rounds]").count() == 0
            robot_rules = {"map_size": 8, "initial_hp": 90, "damage": 30, "max_turns": 40}
            save_rules(robot_rules)
            screenshot("rules-robot.png")
            seed()
            # Lock reads saved server configuration, not unsaved browser fields.
            page.locator(".nav-item[data-view=rules]").click()
            page.locator('#rules-form [name="initial_hp"]').fill("91")
            open_room()
            page.wait_for_function("document.querySelector('#rules-form [name=initial_hp]').value === '90'")
            page.locator(".nav-item[data-view=home]").click()
            robot_match_id = launch("robot_battle")
            cursor = page.evaluate("app.cursor")
            page.wait_for_function("app.match.status === 'completed'", timeout=20000)
            assert page.evaluate("app.cursor") == cursor
            robot = page.request.get(f"{args.url}/api/matches/{robot_match_id}/replay").json()
            assert robot["match"]["rules"] == robot_rules
            assert robot["frames"][0]["robots"]["A"]["hp"] == 90
            assert robot["match"]["result"]["reason"] == "knockout"
            replay_to_end()
            screenshot("robot-victory.png")
            page.locator("#dismiss-victory").click()

            close_room()
            select_game("ott_v2")
            assert page.locator("#rules-fields [name=initial_hp]").count() == 0
            assert page.locator("#rules-fields [name=map_size]").count() == 0
            assert page.locator("#rules-fields [name=rounds]").count() == 1
            page.locator("#rules-form [name=rounds]").fill("0")
            assert page.locator("#rules-form").evaluate("form => !form.checkValidity()")
            ott_rules = {"max_turns": 20, "rounds": 2}
            save_rules(ott_rules)
            screenshot("rules-ott.png")
            seed()
            open_room()
            assert "ROBOT" in page.locator("#arena-game").inner_text(), "Selecting OTT must not repaint the existing robot replay"
            ott_match_id = launch("ott_v2")
            cursor = page.evaluate("app.cursor")
            spectator = spectator_context.new_page()
            spectator.on("pageerror", lambda error: errors.append(str(error)))
            spectator.goto(f"{args.spectator_url or args.url}/?match={ott_match_id}#home")
            spectator.wait_for_function("id => app.match?.id === id", arg=ott_match_id, timeout=15000)
            spectator.locator("#play-pause").click()
            page.wait_for_function("app.match.status === 'completed'", timeout=30000)
            spectator.wait_for_function("app.match.status === 'completed'", timeout=30000)
            assert page.evaluate("app.cursor") == cursor
            saved = page.request.get(f"{args.url}/api/matches/{ott_match_id}/replay").json()
            assert saved["match"]["rules"] == ott_rules
            assert saved["match"]["result"]["reason"] == "series_complete"
            assert len(saved["frames"][-1]["round_results"]) == 2
            assert page.evaluate("app.frames") == spectator.evaluate("app.frames") == saved["frames"]
            assert "OTT" in page.locator("#arena-game").inner_text()
            assert "R:" in page.locator("#hp-a-text").inner_text()
            screenshot("ott-board.png")
            replay_to_end()
            screenshot("ott-victory.png")
            page.locator("#dismiss-victory").click()

            page.locator(".nav-item[data-view=upload]").click()
            assert page.locator("#upload-game").input_value() == "ott_v2"
            page.locator("#upload-form [name=name]").fill("QA / OTT UPLOAD")
            page.locator("#bot-file").set_input_files(str(ROOT / "samples/ott_v2/runner.py"))
            page.locator("#upload-form [type=submit]").click()
            page.wait_for_function("!document.querySelector('#upload-form [type=submit]').disabled")
            assert "đã sẵn sàng" in page.locator("#upload-feedback").inner_text()
            assert page.locator("#upload-game").input_value() == "ott_v2"
            screenshot("upload-ott.png")

            page.locator(".nav-item[data-view=watch]").click()
            page.locator(f'#all-matches [data-match-id="{robot_match_id}"] button').click()
            page.wait_for_function("id => app.match?.id === id && app.cursor <= 1", arg=robot_match_id)
            assert "ROBOT" in page.locator("#arena-game").inner_text()
            assert page.evaluate("app.frames") == robot["frames"]
            page.locator("#play-pause").click()
            close_room()
            page.locator(".nav-item[data-view=rules]").click()
            page.locator("#default-rules").click()
            page.wait_for_function("app.rules.max_turns === 100 && app.rules.rounds === 1")
            assert page.request.get(args.url + "/api/games/ott_v2/rules").json() == {"max_turns": 100, "rounds": 1}
            page.set_viewport_size({"width": 390, "height": 844})
            for view in ("home", "upload", "create", "watch", "rules"):
                page.locator(f".nav-item[data-view={view}]").click()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), view
            screenshot("mobile-rules.png")
            assert not errors, errors
            print(f"UI PASS: dynamic schemas, both games, real rule effects, game-specific upload, live/replay, Pause/Reset/Start, defaults, 390px and two independent spectator contexts. Robot={robot_match_id}; OTT={ott_match_id}")
        finally:
            if page.evaluate("app.role") == "organizer":
                close_room()
            for game_id, rules in original_rules.items():
                assert page.request.put(f"{args.url}/api/games/{game_id}/rules", data=rules).ok
            assert page.request.put(args.url + "/api/games/selected", data={"game_id": original_game}).ok
            if original_competition["competition_locked"]:
                assert page.request.post(args.url + "/api/competition/open").ok
            if page.evaluate("app.role") == "organizer":
                page.locator("#organizer-toggle").click()
                page.wait_for_function("app.role === 'player'")
                assert page.locator("#rules-form [type=submit]").is_disabled()
            browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--spectator-url", help="Use the host's LAN URL for the second browser context")
    main(parser.parse_args())
