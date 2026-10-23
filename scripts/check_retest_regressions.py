"""Replay/session/navigation regressions on a disposable localhost server.

Use --reproduce to record the original R01-R04 failures without stopping early.
Replay fixtures are browser-local; authentication and logout use the real server.
"""
import argparse
import json
import sys
import tempfile
import threading
from pathlib import Path

import uvicorn
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_account_ui import PASSWORD, available_port, seed, wait_ready
from backend.auth_http import HTTPAuthSettings
from backend.auth_limits import RateLimits
from backend.main import create_app

EVIDENCE = ROOT / ".qa-evidence" / "retest"


def run(reproduce=False):
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="neon-retest-") as folder:
        base = Path(folder)
        seed(base)
        port = available_port()
        origin = f"http://127.0.0.1:{port}"
        settings = HTTPAuthSettings(enabled=True, account_only=True, origins=(origin,), allow_http=True,
                                    limits=RateLimits(request_source=10000, session_token=5000))
        server = uvicorn.Server(uvicorn.Config(create_app(base, tick_seconds=.01, account_http=settings),
                                               host="127.0.0.1", port=port, log_level="error",
                                               timeout_graceful_shutdown=2))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        checks, errors = {}, []
        try:
            wait_ready(origin)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="chrome", headless=True)
                page = browser.new_page(viewport={"width": 1366, "height": 900}, locale="vi-VN")
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(origin)

                def login(username):
                    page.click("#landing-login")
                    page.fill("#account-username", username)
                    page.fill("#account-login-form [name=password]", PASSWORD)
                    page.click("#account-login-form [type=submit]")
                    page.wait_for_function("app.initialized && !app.initializing")

                def view(name):
                    page.evaluate("name => { location.hash = name; }", name)
                    expect(page.locator(f"#view-{name}")).to_be_visible()

                def check(name, passed):
                    checks[name] = bool(passed)
                    if not reproduce:
                        assert passed, name

                login("qa.admin")
                frame = page.evaluate("structuredClone(selectedGame().preview_state)")
                final = {**frame, "turn": 18, "events": [], "result": {"winner": "A", "reason": "qa"}}
                replay = {"match": {"id": "fixture-replay", "game_id": frame["game_id"], "status": "completed",
                                    "player_a_name_snapshot": "Fixture Alpha", "player_b_name_snapshot": "Fixture Beta",
                                    "bots": {"A": {"name": "Fixture Alpha", "language": "py"}, "B": {"name": "Fixture Beta", "language": "py"}},
                                    "result": final["result"]}, "frames": [frame, final]}
                page.route("**/api/admin/matches/fixture-replay/replay", lambda route: route.fulfill(json=replay))
                page.evaluate("scrollTo(0, document.documentElement.scrollHeight)")
                page.evaluate("async () => { await loadMatch('fixture-replay'); }")
                check("R03_replay_scroll_and_focus", page.evaluate("""() => {
                    const heading = document.querySelector('#replay-heading');
                    return !!heading && document.activeElement === heading && heading.getBoundingClientRect().top >= 0
                      && heading.getBoundingClientRect().top < innerHeight / 2;
                }"""))
                page.locator('.nav-item[data-view="home"]').click()
                check("R02_home_exits_replay", page.evaluate("!app.match && !new URL(location.href).searchParams.has('match')"))
                page.evaluate("async () => { await loadMatch('fixture-replay'); }")
                page.evaluate("app.paused = true")
                page.evaluate("async () => { await accountLogout(); }")
                login("qa.player")
                check("R01_no_previous_session_replay", page.evaluate("!app.match && !app.frames.length && !document.body.classList.contains('has-match') && !document.querySelector('#combat-log').textContent"))
                if reproduce:
                    page.reload()
                    page.wait_for_function("app.initialized && !app.initializing")
                view("upload")
                page.fill("#account-team-create [name=slug]", "fixture-retest-team")
                page.fill("#account-team-create [name=display_name]", "Fixture Captain Team")
                page.click("#account-team-create [type=submit]")
                page.click("#account-team-activate")
                expect(page.locator("#account-team-status")).to_contain_text("Đã sẵn sàng đăng ký")
                page.locator("#upload-workflow-details").evaluate("node => { node.open = true; }")
                for count in range(1, 3):
                    page.click("[data-sample=python]")
                    page.wait_for_function("count => app.bots.length === count && !app.seeding", arg=count)
                page.locator("#upload-workflow-details .disclosure-close").click()
                view("home")
                page.click("#overview-primary")
                expect(page.locator("#view-upload")).to_be_visible()
                check("R04_active_bot_cta_reveals_list", page.locator("#bot-library").is_visible()
                      and page.locator("#bot-library button").first.is_visible()
                      and page.evaluate("!app.activeTeamBot?.bot"))
                if not reproduce:
                    extended_checks(page, replay, checks, login, origin)
                page.evaluate("async () => { await accountLogout(); }")
                assert not errors, errors
                browser.close()
        finally:
            server.should_exit = True
            thread.join(timeout=20)
        (EVIDENCE / ("before.json" if reproduce else "after.json")).write_text(
            json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(checks, ensure_ascii=False))


def extended_checks(page, replay, checks, login, origin):
    page.route("**/api/player/official-matches/fixture-player-replay/replay", lambda route: route.fulfill(json=replay))
    page.evaluate("visitWorkspace(workspaceLink('home'))")
    page.evaluate("async () => { await loadMatch('fixture-player-replay', true); }")
    expect(page.locator("#view-replay")).to_be_visible()
    expect(page.locator("#replay-heading")).to_be_focused()
    expect(page.locator("#page-label")).to_have_text("Diễn biến trận đấu")
    page.locator("#timeline").fill("1")
    expect(page.locator("#turn-counter")).to_have_text("018")
    expect(page.locator("#turn-max")).to_have_text("18")
    assert page.locator("#timeline").get_attribute("max") == "1"
    assert "Giới hạn" in page.locator("#replay-rule-limit").inner_text()
    page.go_back()
    expect(page.locator("#view-home")).to_be_visible()
    assert page.evaluate("!app.match && !app.frames.length")
    page.go_forward()
    expect(page.locator("#view-replay")).to_be_visible()
    page.wait_for_function("app.match?.id === 'fixture-replay'")
    page.reload()
    page.wait_for_function("app.initialized && !app.initializing && app.match?.id === 'fixture-replay'")
    # Old shared URLs ending in #home still resolve to the replay screen.
    page.goto(origin + "/?official=fixture-player-replay#home")
    page.wait_for_function("app.initialized && !app.initializing && app.match?.id === 'fixture-replay'")
    expect(page.locator("#view-replay")).to_be_visible()
    checks["R02_history_reload_and_old_deep_link"] = True
    checks["R12_actual_turn_and_slider_bounds"] = True
    for width in (1366, 1440, 360, 390, 768):
        page.set_viewport_size({"width": width, "height": 900})
        page.evaluate("focusWorkspaceTarget(document.querySelector('#replay-heading'))")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
        assert page.locator(".view.active h1:visible").count() == 1
        page.screenshot(path=str(EVIDENCE / f"replay-{width}.png"), full_page=True, animations="disabled")
    page.set_viewport_size({"width": 1366, "height": 900})
    ott = page.evaluate("async () => (await api('/api/games/ott_v2')).preview_state")
    ott["rules"] = {**ott["rules"], "max_turns": 100, "rounds": 1}
    terminal = {**ott, "turn": 18, "round_turn": 18, "result": {"winner": "A", "reason": "qa"}, "events": []}
    ott_replay = {"match": {**replay["match"], "game_id": "ott_v2"}, "frames": [ott, terminal]}
    page.route("**/api/player/official-matches/fixture-ott/replay", lambda route: route.fulfill(json=ott_replay))
    page.evaluate("async () => { await loadMatch('fixture-ott', true); }")
    page.locator("#timeline").fill("1")
    expect(page.locator("#turn-max")).to_have_text("18")
    expect(page.locator("#replay-rule-limit")).to_have_text("Giới hạn ván: 100 lượt")
    assert "18/100" not in page.locator("#arena-phase").inner_text()
    page.screenshot(path=str(EVIDENCE / "ott-progress.png"), full_page=True, animations="disabled")
    page.evaluate("visitWorkspace(workspaceLink('scrimmage'))")
    expect(page.locator("#scrimmage-bot-link")).to_be_visible()
    page.click("#scrimmage-bot-link")
    expect(page.locator("#bot-library-title")).to_be_focused()
    checks["R10_captain_missing_bot_action"] = True
    page.evaluate("visitWorkspace(workspaceLink('tournaments'))")
    expect(page.locator("#team-tournaments-list")).to_contain_text("Chưa có giải đấu của đội bạn")
    page.evaluate("visitWorkspace(workspaceLink('standings'))")
    expect(page.locator("#standings-body")).to_contain_text("trong các giải đội bạn tham gia")
    checks["R11_player_empty_states_explain_team_scope"] = True

    page.evaluate("async () => { await accountLogout(); }")
    login("qa.admin")
    # A transport that ignores AbortSignal must still fail the session epoch
    # check, for both a late success and a late unauthenticated response.
    for status in (200, 401):
        page.evaluate("""({replay, status}) => {
            const original = window.fetch;
            window.fetch = (url, options) => String(url).includes('/matches/late-fixture/replay')
              ? new Promise(resolve => { window.finishOldResponse = () => resolve(new Response(JSON.stringify(replay), {status})); })
              : original(url, options);
            window.pendingOldReplay = loadMatch('late-fixture');
        }""", {"replay": replay, "status": status})
        page.wait_for_function("!!window.finishOldResponse")
        page.evaluate("async () => { await accountLogout(); }")
        login("qa.player")
        page.evaluate("async () => { finishOldResponse(); await pendingOldReplay; window.finishOldResponse = null; }")
        assert page.evaluate("!app.match && !app.frames.length && app.accountAudience === 'player' && !document.querySelector('#combat-log').textContent")
        page.evaluate("async () => { await accountLogout(); }")
        login("qa.admin")
    checks["R01_late_success_and_401_cannot_update_new_session"] = True

    # Two ready same-name uploads from the actual Player are identifiable via
    # existing metadata and the Admin-only ownership projection.
    page.evaluate("visitWorkspace(workspaceLink('administration'))")
    page.click("#admin-tab-bots")
    expect(page.locator("#admin-submissions-list .bot-row")).to_have_count(2)
    texts = page.locator("#admin-submissions-list .bot-row").all_inner_texts()
    assert texts[0] != texts[1] and all("Fixture Captain Team" in text and "ID " in text for text in texts)
    page.fill("#admin-bot-query", "Fixture Captain Team")
    expect(page.locator("#admin-submissions-list .bot-row")).to_have_count(2)
    checks["R09_duplicate_bot_metadata_and_team_search"] = True

    fixture = page.evaluate("""() => {
      const now = Date.now()/1000;
      const base = {team_a_id:'fixture-alpha', team_b_id:'fixture-beta', game_id:app.selectedGameId, slots:[], bot_lock_at:now+300};
      return [ {...base,id:'future',status:'SCHEDULED',scheduled_at:now+600},
        {...base,id:'blocked',status:'BLOCKED',status_reason:'ACTIVE_BOT_MISSING',scheduled_at:now-3600},
        {...base,id:'overdue',status:'LOCKED',scheduled_at:now-120},
        {...base,id:'completed',status:'COMPLETED',scheduled_at:now-7200} ];
    }""")
    page.route("**/api/admin/official-matches", lambda route: route.fulfill(json={"requests": fixture}) if route.request.method == "GET" else route.continue_())
    page.route("**/api/admin/teams", lambda route: route.fulfill(json={"teams": [
        {"id": "fixture-alpha", "display_name": "Fixture Alpha", "status": "ACTIVE", "member_count": 1},
        {"id": "fixture-beta", "display_name": "Fixture Beta", "status": "ACTIVE", "member_count": 1}]}))
    page.evaluate("async () => { await refreshOfficialMatches(); visitWorkspace(workspaceLink('home')); }")
    expect(page.locator("#overview-next-title")).to_contain_text(fixture[0]["game_id"])
    assert "Bị chặn" not in page.locator("#overview-next-note").inner_text()
    page.click("#overview-primary")
    expect(page.locator("#official-status-filter")).to_have_value("attention")
    expect(page.locator("#official-match-list > article")).to_have_count(2)
    expect(page.locator("#official-schedule-form")).to_be_hidden()
    expect(page.locator("#official-match-list")).to_contain_text("Một đội chưa chọn Active Bot")
    page.evaluate("async () => { app.officialMatches = app.officialMatches.filter(item => item.id !== 'future'); renderWorkspaceOverview(); visitWorkspace(workspaceLink('home')); }")
    expect(page.locator("#overview-next-title")).to_have_text("Chưa có lịch thi đấu sắp tới")
    page.click("#overview-primary")
    checks["R05_R07_upcoming_attention_filter_and_explanation"] = True

    page.click("#official-admin-panel > summary")
    expect(page.locator("#official-schedule-form [type=submit]")).to_be_enabled()
    page.evaluate("""() => {
      const form = document.querySelector('#official-schedule-form');
      form.elements.bot_lock_at.value = officialLocalInput(Date.now()-120000);
      form.elements.bot_lock_at.dispatchEvent(new Event('input', {bubbles:true}));
    }""")
    expect(page.locator("#official-schedule-form [type=submit]")).to_be_disabled()
    expect(page.locator("#official-lock-error")).to_contain_text("đã qua")
    old = page.locator('#official-schedule-form [name=bot_lock_at]').input_value()
    page.click("#official-admin-panel > summary")
    page.click("#official-admin-panel > summary")
    assert page.locator('#official-schedule-form [name=bot_lock_at]').input_value() == old
    page.evaluate("""() => {
      app.officialTimesDirty = false; initializeOfficialTimes(); updateOfficialEligibility();
    }""")
    expect(page.locator("#official-schedule-form [type=submit]")).to_be_enabled()
    page.select_option("#official-team-b", "fixture-alpha")
    expect(page.locator("#official-schedule-form [type=submit]")).to_be_disabled()
    page.select_option("#official-team-b", "fixture-beta")
    checks["R08_time_validation_defaults_and_edited_values"] = True
    for width in (1366, 1440, 360, 390, 768):
        page.set_viewport_size({"width": width, "height": 900})
        page.evaluate("() => { document.activeElement.blur(); scrollTo(0, 0); }")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
        page.screenshot(path=str(EVIDENCE / f"official-{width}.png"), full_page=True, animations="disabled")
    checks["responsive_replay_and_official_five_widths"] = True
    tournament = {"id": "fixture-tournament", "name": "Fixture tournament", "status": "ACTIVE", "format": "round_robin",
                  "game_id": fixture[0]["game_id"], "teams": [], "standings": [], "groups": [], "bracket": [],
                  "fixtures": [{"id": "fixture-slot", "round_number": 1, "match_status": "BLOCKED", "official_request_id": "blocked"}]}
    tournaments = [tournament, {**tournament, "id": "fixture-tournament-two", "name": "Second fixture tournament"}]
    page.route("**/api/admin/team-tournaments", lambda route: route.fulfill(json={"tournaments": tournaments}))
    page.evaluate("visitWorkspace(workspaceLink('tournaments'))")
    expect(page.locator(".team-tournament-details")).to_have_count(2)
    first = page.locator(".team-tournament-details").first
    expect(first.locator(".tournament-schedule")).to_be_hidden()
    first.locator("summary").first.click()
    expect(first.locator(".tournament-schedule")).to_contain_text("Một đội chưa chọn Active Bot")
    page.evaluate("renderTeamTournaments()")
    assert page.locator(".team-tournament-details[open]").count() == 1
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.screenshot(path=str(EVIDENCE / "tournament-mobile.png"), full_page=True, animations="disabled")
    checks["R07_compact_tournaments_keep_explanation_and_expansion"] = True


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reproduce", action="store_true")
    run(parser.parse_args().reproduce)
