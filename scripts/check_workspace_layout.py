"""Role/state regression for the task-oriented workspace, with disposable data.

Run with .venv/Scripts/python scripts/check_workspace_layout.py. Requires local
Chrome and Playwright. All mutations target a temporary localhost server. No
Docker matches are executed; scheduled matches stay several hours in the future.
"""
import json
import sys
import tempfile
import threading
from contextlib import ExitStack
from pathlib import Path

import uvicorn
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_account_ui import PASSWORD, available_port, seed, wait_ready
from backend.account_database import AccountDatabase
from backend.auth_http import HTTPAuthSettings
from backend.auth_limits import AuthRateLimiter, RateLimits
from backend.auth_service import AuthService
from backend.main import create_app
from backend.writer_lock import WriterLock

EVIDENCE = ROOT / ".qa-evidence" / "workspace-layout"
WIDTHS = (1366, 1440, 360, 390, 768)


def run():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="neon-workspace-layout-") as folder:
        base = Path(folder)
        seed(base)
        data = base / "data"
        with WriterLock(data) as writer, AccountDatabase(data).writer_connection(writer) as connection:
            auth = AuthService(connection, writer, login_limiter=AuthRateLimiter())
            admin = auth.login("qa.admin", PASSWORD, audience="ADMIN", source_key="layout-qa").principal
            for username in ("qa.member", "qa.opponent"):
                grant = auth.issue_invitation(admin, username, name=username)
                auth.activate(grant.token, PASSWORD)
            # Exercise real account pagination without needing 50 passwords.
            for index in range(51):
                auth.issue_invitation(admin, f"qa.pending{index:02}", name=f"Tài khoản kiểm thử {index:02}")
        port = available_port()
        origin = f"http://127.0.0.1:{port}"
        settings = HTTPAuthSettings(enabled=True, account_only=True, self_registration=True,
                                    origins=(origin,), allow_http=True,
                                    # This fast layout matrix uses its own temporary server;
                                    # production auth budgets are covered by the existing suite.
                                    limits=RateLimits(request_source=10000, session_token=5000))
        application = create_app(base, tick_seconds=.01, account_http=settings)
        server = uvicorn.Server(uvicorn.Config(application, host="127.0.0.1", port=port, log_level="error", timeout_graceful_shutdown=2))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        errors, measurements = [], []
        try:
            wait_ready(origin)
            with sync_playwright() as playwright, ExitStack() as resources:
                browser = playwright.chromium.launch(channel="chrome", headless=True)
                resources.callback(browser.close)

                def login(username):
                    context = browser.new_context(viewport={"width": 1366, "height": 900}, locale="vi-VN")
                    page = context.new_page()
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(origin)
                    page.click("#landing-login")
                    page.fill("#account-username", username)
                    page.fill("#account-login-form [name=password]", PASSWORD)
                    page.click("#account-login-form [type=submit]")
                    page.wait_for_function("app.initialized && !app.initializing")
                    return page

                def view(page, name):
                    page.evaluate("name => { location.hash = name; }", name)
                    expect(page.locator(f"#view-{name}")).to_be_visible()
                    page.wait_for_function("name => document.body.dataset.view === name", arg=name)

                def shot(page, name):
                    page.screenshot(path=str(EVIDENCE / f"{name}.png"), full_page=True, animations="disabled")

                def matrix(page, role, views):
                    for width in WIDTHS:
                        page.set_viewport_size({"width": width, "height": 900})
                        for name in views:
                            view(page, name)
                            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (role, width, name)
                            assert page.locator(".view.active h1:visible").count() == 1, (role, name)
                            assert page.title().endswith("· NEON ARENA")
                            # Duplicate IDs break labels, keyboard routing and form contracts.
                            assert page.evaluate("new Set([...document.querySelectorAll('[id]')].map(n=>n.id)).size === document.querySelectorAll('[id]').length")
                            measurements.append({"role": role, "width": width, "view": name,
                                                 "h1_y": round(page.locator(".view.active h1:visible").bounding_box()["y"], 1),
                                                 "height": page.evaluate("document.documentElement.scrollHeight")})
                        if width == 390:
                            shot(page, role + "-mobile")
                    page.set_viewport_size({"width": 1366, "height": 900})

                admin = login("qa.admin")
                shot(admin, "admin-home-empty")
                expect(admin.locator("#overview-primary")).to_have_attribute("href", "#rules")
                assert admin.locator('#view-home a[href="#official"]:visible, #view-home [data-go=official]:visible').count() <= 1
                view(admin, "profile")
                expect(admin.locator(".workspace-context")).to_be_hidden()
                expect(admin.locator("#competition-open")).to_be_hidden()
                view(admin, "administration")
                expect(admin.locator("#admin-account-count")).to_contain_text("55 tài khoản")
                expect(admin.locator("#admin-invite-form")).to_be_hidden()
                admin.click("#admin-accounts-next")
                expect(admin.locator("#admin-account-count")).to_contain_text("51–55")
                admin.click("#admin-accounts-prev")
                expect(admin.locator("#admin-account-count")).to_contain_text("1–50")
                # Opening invitation/recovery UI must not issue any grant.
                writes = []
                admin.on("request", lambda request: writes.append(request.url) if request.method == "POST" else None)
                admin.click("#admin-invite-disclosure > summary")
                expect(admin.locator("#admin-invite-form")).to_be_visible()
                admin.locator("#admin-invite-form input").first.focus()
                admin.keyboard.press("Escape")
                expect(admin.locator("#admin-invite-disclosure > summary")).to_be_focused()
                admin.locator("#admin-accounts-body").get_by_role("button", name="Khôi phục mật khẩu").first.click()
                expect(admin.locator("#admin-player-recovery-form input")).to_be_focused()
                admin.keyboard.press("Escape")
                assert writes == [], writes
                admin.locator("#admin-tab-accounts").focus()
                admin.keyboard.press("ArrowRight")
                expect(admin.locator("#admin-tab-teams")).to_be_focused()
                expect(admin.locator("#admin-pane-teams")).to_be_visible()
                expect(admin.locator("#admin-pane-accounts")).to_be_hidden()
                admin.keyboard.press("End")
                expect(admin.locator("#admin-pane-bots")).to_be_visible()
                view(admin, "tournaments")
                expect(admin.locator("#team-tournament-create")).to_be_hidden()
                admin.click("#team-tournament-admin-panel > summary")
                expect(admin.locator("#team-tournament-create [type=submit]")).to_be_disabled()
                view(admin, "official")
                expect(admin.locator("#official-schedule-form [type=submit]")).to_be_disabled()
                expect(admin.locator("#official-schedule-eligibility")).to_contain_text("Chưa đủ hai đội")

                player = login("qa.player")
                shot(player, "player-home-new")
                expect(player.locator("#overview-primary")).to_have_text("Tạo hoặc tham gia đội ↗")
                view(player, "upload")
                expect(player.locator("#upload-form")).to_be_hidden()
                expect(player.locator("#bot-file")).to_be_disabled()
                shot(player, "team-bot-new")
                player.click("#upload-workflow-details > summary")
                expect(player.locator("#drop-zone")).to_have_attribute("aria-disabled", "true")
                expect(player.locator("#sample-list a").first).to_be_visible()
                response = player.request.get(origin + player.locator("#sample-list a").first.get_attribute("href"))
                assert response.status == 200
                player.click("#upload-team-link")
                expect(player.locator("#account-team-create [name=slug]")).to_be_focused()
                player.click("#upload-workflow-details > summary")
                matrix(player, "new-player", ("home", "upload", "official", "scrimmage", "profile", "rules"))
                view(player, "rules")
                expect(player.locator("#rules-form")).to_be_hidden()
                expect(player.locator("#rules-summary")).to_be_visible()
                expect(player.locator("#workspace-game-select")).to_be_hidden()
                player.locator("#user-menu > summary").focus()
                player.keyboard.press("Enter")
                expect(player.locator("#user-menu [data-view=profile]")).to_be_visible()
                player.keyboard.press("Escape")
                expect(player.locator("#user-menu > summary")).to_be_focused()

                # Real local Captain transitions: no team -> DRAFT -> ACTIVE -> ready bot -> Active Bot.
                view(player, "upload")
                player.fill("#account-team-create [name=slug]", "qa-layout-alpha")
                player.fill("#account-team-create [name=display_name]", "Đội chiến thuật với tên dài để kiểm tra xuống dòng trên mobile")
                player.click("#account-team-create [type=submit]")
                expect(player.locator("#account-team-activate")).to_be_visible()
                view(player, "home")
                expect(player.locator("#overview-title")).to_contain_text("chưa được kích hoạt")
                view(player, "upload")
                player.click("#account-team-activate")
                expect(player.locator("#account-team-status")).to_contain_text("ACTIVE")
                view(player, "home")
                expect(player.locator("#overview-primary")).to_have_text("Nộp bot cho đội ↗")
                view(player, "upload")
                player.click("[data-sample=python]")
                expect(player.locator("#bot-library")).to_contain_text("ready", timeout=30000)
                view(player, "home")
                expect(player.locator("#overview-primary")).to_have_text("Chọn Active Bot ↗")
                view(player, "upload")
                player.click(".team-management > summary")
                player.fill("#account-team-invite [name=username]", "qa.member")
                player.click("#account-team-invite [type=submit]")
                expect(player.locator("#toast")).to_contain_text("mời")
                member = login("qa.member")
                view(member, "upload")
                member.locator("#account-team-inbox").get_by_role("button", name="Tham gia", exact=True).click()
                expect(member.locator("#account-team-status")).to_contain_text("MEMBER")
                view(member, "home")
                expect(member.locator("#overview-primary")).to_have_text("Xem bot của đội ↗")
                expect(member.locator("#overview-note")).to_contain_text("Captain cần chọn")
                view(member, "upload")
                assert member.get_by_role("button", name="Chọn Active Bot", exact=True).count() == 0
                player.locator("#bot-library").get_by_role("button", name="Chọn Active Bot", exact=True).click()
                expect(player.locator("#bot-library")).to_contain_text("Active Bot ✓")
                view(player, "home")
                expect(player.locator("#overview-title")).to_have_text("Đội đã sẵn sàng")
                shot(player, "captain-home-ready")

                opponent = login("qa.opponent")
                view(opponent, "upload")
                opponent.fill("#account-team-create [name=slug]", "qa-layout-beta")
                opponent.fill("#account-team-create [name=display_name]", "Đội đối thủ kiểm thử")
                opponent.click("#account-team-create [type=submit]")
                opponent.click("#account-team-activate")
                expect(opponent.locator("#account-team-status")).to_contain_text("ACTIVE")

                view(admin, "rules")
                admin.fill("#rule-max_turns", "80")
                expect(admin.locator("#rules-state")).to_have_text("Chưa lưu")
                expect(admin.locator("#competition-open")).to_be_disabled()
                admin.click("#rules-form [type=submit]")
                expect(admin.locator("#rules-state")).to_have_text("Đã lưu")
                admin.click("#competition-open")
                expect(admin.locator("#rules-state")).to_have_text("Đã khóa")
                expect(admin.locator("#rule-max_turns")).to_be_disabled()
                view(admin, "official")
                admin.click("#official-refresh")
                expect(admin.locator("#official-team-a")).to_be_enabled()
                admin.locator("#official-team-a").select_option(index=0)
                admin.locator("#official-team-b").select_option(index=1)
                admin.evaluate("""() => {
                  const form=document.querySelector('#official-schedule-form');
                  form.elements.bot_lock_at.value=officialLocalInput(Date.now()+10800000);
                  form.elements.scheduled_at.value=officialLocalInput(Date.now()+14400000);
                }""")
                admin.click("#official-schedule-form [type=submit]")
                expect(admin.locator("#official-match-list")).to_contain_text("SCHEDULED")
                view(admin, "tournaments")
                admin.click("#refresh-team-tournaments")
                expect(admin.locator('#team-tournament-team-options input')).to_have_count(2)
                admin.locator("#team-tournament-admin-panel").evaluate("node => { node.open = true; }")
                admin.fill("#team-tournament-create [name=name]", "Giải kiểm thử bố cục")
                for checkbox in admin.locator('#team-tournament-team-options input').all():
                    checkbox.check()
                admin.click("#team-tournament-create [type=submit]")
                expect(admin.locator("#team-tournaments-list")).to_contain_text("Giải kiểm thử bố cục")
                view(admin, "seasons")
                admin.click("#season-admin-panel > summary")
                admin.fill("#season-create [name=name]", "Mùa thi đấu kiểm thử")
                admin.click("#season-create [type=submit]")
                expect(admin.locator("#season-list")).to_contain_text("Mùa thi đấu kiểm thử")
                view(admin, "administration")
                admin.click("#admin-tab-teams")
                expect(admin.locator("#admin-teams-list")).to_contain_text("qa-layout-alpha")
                shot(admin, "admin-teams-populated")
                admin.fill("#admin-team-query", "khong-co-doi-nay")
                expect(admin.locator("#admin-teams-list")).to_contain_text("Không tìm thấy")
                admin.fill("#admin-team-query", "")
                admin.click("#admin-tab-bots")
                expect(admin.locator("#admin-submissions-list")).to_contain_text("python")
                admin.fill("#admin-bot-query", "khong-co-bot-nay")
                expect(admin.locator("#admin-submissions-list")).to_contain_text("Không tìm thấy")
                admin.fill("#admin-bot-query", "")

                # Fault injection stays within this browser and is reversible.
                admin.route("**/api/admin/accounts?*", lambda route: route.fulfill(status=500, json={"detail": "QA load failure"}))
                admin.click("#admin-refresh-bots")
                expect(admin.locator("#admin-load-feedback")).to_contain_text("Không tải được")
                admin.unroute("**/api/admin/accounts?*")
                admin.click("#admin-refresh-bots")
                expect(admin.locator("#admin-load-feedback")).to_be_hidden()
                matrix(admin, "admin", ("home", "profile", "administration", "seasons", "tournaments", "official", "rules"))
                matrix(player, "captain", ("home", "upload", "official", "scrimmage", "rules", "profile"))
                member.reload()
                member.wait_for_function("app.initialized && !app.initializing")
                matrix(member, "member", ("home", "upload", "official", "scrimmage", "profile"))
                view(admin, "home")
                shot(admin, "admin-home-populated")
                view(player, "upload")
                shot(player, "team-bot-ready")
                view(player, "home")
                shot(player, "player-home-ready")
                # An interrupted replay can have no frames. Loading it must
                # still reveal the arena after the overview hid its empty UI.
                member.route("**/official-matches/qa-layout-replay/replay", lambda route: route.fulfill(json={
                    "match": {"id": "qa-layout-replay", "game_id": "robot_battle", "status": "interrupted"},
                    "frames": [],
                }))
                member.evaluate("async () => { await loadMatch('qa-layout-replay', true); }")
                expect(member.locator(".arena-layout")).to_be_visible()
                player.click("#user-menu > summary")
                player.click("#organizer-toggle")
                expect(player.locator("#account-landing")).to_be_visible()
                assert player.url.endswith("#home")
                assert player.title() == "NEON ARENA · Nền tảng thi đấu bot"
                # Wake the server's revocation watchers before closing the
                # remaining test browsers, including the context that reloaded.
                # Real logout both revokes the token and notifies open sockets.
                for page in (admin, member, opponent):
                    page.evaluate("async () => { await accountLogout(); }")
                    expect(page.locator("#account-landing")).to_be_visible()
                assert not errors, errors
                browser.close()
        finally:
            server.should_exit = True
            thread.join(timeout=20)
            if thread.is_alive():
                raise RuntimeError("Disposable layout server did not stop")
        (EVIDENCE / "measurements.json").write_text(json.dumps(measurements, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"PASS workspace layout: {len(measurements)} role/view/width combinations; real Captain/member/bot transitions; grants, keyboard, pagination, search, local schedules/seasons/tournaments, error recovery, logout")


if __name__ == "__main__":
    run()
