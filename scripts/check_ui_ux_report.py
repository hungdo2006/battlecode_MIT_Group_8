"""Exercise the October 2026 UI review against disposable Account-Only data.

Requires Playwright and local Chrome. Does not access a deployed arena.
"""
import json
import sys
import tempfile
import threading
from types import SimpleNamespace
from pathlib import Path

import uvicorn
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.check_account_ui import PASSWORD, available_port, seed, wait_ready
from backend.auth_http import HTTPAuthSettings
from backend.main import create_app


def run():
    with tempfile.TemporaryDirectory(prefix="neon-ui-review-") as folder:
        base = Path(folder)
        seed(base)
        origin = f"http://127.0.0.1:{available_port()}"
        settings = HTTPAuthSettings(enabled=True, account_only=True, self_registration=True,
                                    require_email_verification=True,
                                    email_sender=SimpleNamespace(send=lambda *_: None),
                                    origins=(origin,), allow_http=True)
        application = create_app(base, tick_seconds=.01, account_http=settings)
        server = uvicorn.Server(uvicorn.Config(application, host="127.0.0.1",
                                              port=int(origin.rsplit(":", 1)[1]), log_level="error"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            wait_ready(origin)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="chrome", headless=True)
                context = browser.new_context(viewport={"width": 1363, "height": 936}, locale="en-US")
                page = context.new_page()
                errors = []
                evidence = ROOT / ".qa-evidence" / "ui-ux-review"
                evidence.mkdir(parents=True, exist_ok=True)
                page.on("pageerror", lambda error: errors.append(str(error)))

                def workspace():
                    page.wait_for_function("typeof app !== 'undefined' && app.initialized && !app.initializing")

                def aligned(first, second):
                    # Read both rects in a single animation frame; view entry
                    # animations and browser focus scrolling can move the page.
                    boxes = page.evaluate("selectors => selectors.map(selector => document.querySelector(selector).getBoundingClientRect().toJSON())", [first, second])
                    assert abs(boxes[0]["y"] - boxes[1]["y"]) < 1, boxes

                def login(username):
                    if not page.locator("#account-dialog").is_visible():
                        page.click("#landing-login")
                    page.fill("#account-username", username)
                    page.fill("#account-login-form [name=password]", PASSWORD)
                    page.click("#account-login-form [type=submit]")

                def view(name):
                    page.evaluate("name => { location.hash = name; }", name)
                    expect(page.locator(f"#view-{name}")).to_be_visible()

                def logout():
                    page.click("#organizer-toggle")
                    expect(page.locator("#account-landing")).to_be_visible()
                    assert page.url.endswith("#home"), page.url
                    assert page.title() == "NEON ARENA · Nền tảng thi đấu bot"

                # UI-01..11: localized forms, constraints, a reachable contact,
                # persistent close controls, stable gutter, and button semantics.
                page.goto(origin)
                expect(page.locator("#landing-register")).to_be_enabled()
                page.screenshot(path=str(evidence / "landing-desktop.png"), full_page=True, animations="disabled")
                page.click("#landing-register")
                expect(page.locator("#account-description")).to_contain_text("Tạo tài khoản")
                expect(page.locator("#account-feedback")).to_contain_text("Tạo tài khoản")
                expect(page.locator("#account-register-choice")).to_have_attribute("aria-pressed", "true")
                expect(page.locator("#account-login-choice")).to_have_attribute("aria-pressed", "false")
                page.screenshot(path=str(evidence / "register-desktop.png"), animations="disabled")
                username = page.locator("#account-register-form [name=username]")
                assert "username-help" in username.get_attribute("aria-describedby")
                page.click("#account-register-form [type=submit]")
                expect(username).to_have_attribute("aria-invalid", "true")
                expect(page.locator("#account-register-form .field-error:visible").first).to_contain_text("Vui lòng")
                page.fill("#account-register-form [name=password]", PASSWORD)
                toggle = page.locator("#account-register-form .password-toggle").first
                toggle.click()
                expect(page.locator("#account-register-form [name=password]")).to_have_attribute("type", "text")
                assert page.locator("#account-register-form [name=password]").input_value() == PASSWORD
                before = username.bounding_box()["width"]
                page.locator("#account-password-tools").evaluate("node => { node.open = true; }")
                expect(page.locator("#account-password-tools")).to_be_visible()
                page.locator("#account-activation-form").evaluate("node => { node.closest('details').open = true; }")
                assert abs(before - username.bounding_box()["width"]) < 1
                assert page.locator("#account-support-link").get_attribute("href") == "mailto:hungdonxqvbn@gmail.com"
                assert page.locator("#account-recovery-note").evaluate(
                    "node => !!(node.compareDocumentPosition(document.querySelector('#account-reset-password-form')) & Node.DOCUMENT_POSITION_FOLLOWING)")
                assert page.locator("#account-activation-form [name=confirm_password]").count() == 1
                page.locator("#account-dialog").evaluate("node => { node.scrollTop = node.scrollHeight; }")
                close_box = page.locator("#account-close").bounding_box()
                assert close_box["y"] >= 0 and close_box["y"] + close_box["height"] < 936
                page.click("#account-close")
                expect(page.locator("#account-dialog")).not_to_be_visible()
                page.click("#landing-register")
                page.keyboard.press("Escape")
                expect(page.locator("#landing-register")).to_be_focused()

                # UI-12/13/15: public documentation offers sign-in with an exact
                # return destination, retry on transport/registry failure, JSONL copy.
                page.goto(origin + "/static/protocol.html#examples-section")
                expect(page.locator("#examples a")).to_contain_text("Đăng nhập")
                pretty = page.locator("pre[data-copy-source]")
                assert "\n" in pretty.inner_text()
                assert "\n" not in pretty.get_attribute("data-copy-source")
                json.loads(pretty.get_attribute("data-copy-source"))
                page.evaluate("Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async text => { window.qaCopiedText = text; } } })")
                page.click("pre[data-copy-source] + .copy-code")
                assert page.evaluate("window.qaCopiedText") == pretty.get_attribute("data-copy-source")
                page.evaluate("Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined }); document.execCommand = () => false")
                page.click("pre[data-copy-source] + .copy-code")
                assert page.locator(".copy-fallback").input_value() == pretty.get_attribute("data-copy-source")
                page.route("**/api/health", lambda route: route.abort())
                page.reload()
                expect(page.locator("#examples-retry")).to_be_visible()
                page.unroute("**/api/health")
                page.click("#examples-retry")
                expect(page.locator("#examples a")).to_be_visible()
                page.click("#examples a")
                expect(page.locator("#account-dialog")).to_be_visible()
                login("qa.player")
                page.wait_for_url("**/static/protocol.html#examples-section")
                expect(page.locator("#examples a").first).to_be_visible()
                page.route("**/api/player/games", lambda route: route.fulfill(status=500, json={"detail": "QA registry outage"}))
                page.reload()
                expect(page.locator("#examples-retry")).to_be_visible()
                expect(page.locator("#examples")).to_contain_text("danh sách game")
                page.unroute("**/api/player/games")
                page.click("#examples-retry")
                expect(page.locator("#examples a").first).to_be_visible()
                page.click("#protocol-back")
                workspace()
                expect(page.locator("#view-upload")).to_be_visible()
                aligned("#workspace-game-select", ".workspace-game button")

                # UI-19/22..25: a new Player gets clear Team prerequisites.
                expect(page.locator("#bot-file")).to_be_disabled()
                expect(page.locator("#upload-form [type=submit]")).to_be_disabled()
                for button in page.locator("[data-sample]").all():
                    expect(button).to_be_disabled()
                    assert "đội" in button.get_attribute("title")
                expect(page.locator("#bot-library-title")).to_have_text("Bot của đội")
                assert "team-slug-help" in page.locator("#account-team-create [name=slug]").get_attribute("aria-describedby")
                view("official")
                expect(page.locator("#official-match-list")).to_contain_text("Bạn chưa tham gia đội")
                view("scrimmage")
                expect(page.locator("#scrimmage-opponent")).to_be_disabled()
                expect(page.locator("#scrimmage-opponent")).to_contain_text("chưa tham gia đội")
                view("rules")
                expect(page.locator("#rules-access-note")).to_contain_text("không cần online")
                assert "TOURNAMENT" not in page.locator("#rules-guide").inner_text()
                view("standings")
                expect(page.locator("#view-standings .eyebrow")).to_have_text("BẢNG ĐIỂM GIẢI ĐẤU TEAM")
                page.goto(origin + "/#system")
                workspace()
                assert page.url.endswith("#home")
                page.evaluate("location.hash = 'administration'")
                page.wait_for_function("location.hash === '#home'")
                view("rules")
                logout()

                # UI-16/17/19..21/26/33: both roles, aligned controls, disabled
                # creation without two teams, and mode-specific empty guidance.
                login("qa.admin")
                workspace()
                aligned("#workspace-game-select", ".workspace-game button")
                expect(page.locator("#recent-matches")).not_to_contain_text("Player READY")
                view("tournaments")
                expect(page.locator("#view-tournaments > .tournament-create-panel")).to_be_hidden()
                expect(page.locator("#team-tournament-create [type=submit]")).to_be_disabled()
                aligned("#team-tournament-admin-panel h2", "#account-team-tournaments > .tournament-list-panel h2")
                page.screenshot(path=str(evidence / "admin-tournaments.png"), full_page=True, animations="disabled")
                view("official")
                expect(page.locator("#official-team-a")).to_be_disabled()
                expect(page.locator("#official-team-a")).to_contain_text("Chưa có đội ACTIVE")
                expect(page.locator("#official-schedule-eligibility")).to_contain_text("Chưa đủ hai đội")
                expect(page.locator("#official-schedule-form [type=submit]")).to_be_disabled()

                # Simulate HTTPS behind a proxy without trusting backend-origin
                # metadata or making a request to a deployed instance.
                page.route("https://arena.example.org/lan", lambda route: route.fulfill(
                    content_type="text/html", body=(ROOT / "frontend/lan.html").read_text(encoding="utf-8")))
                page.route("https://arena.example.org/static/**", lambda route: route.fulfill(
                    path=str(ROOT / "frontend" / route.request.url.split("/static/", 1)[1].split("?", 1)[0])))
                page.route("https://arena.example.org/api/health", lambda route: route.fulfill(
                    json={"account_only": True, "read_only": False}))
                page.goto("https://arena.example.org/lan")
                expect(page.locator("#current-origin")).to_have_text("WEBSITE / https://arena.example.org")
                expect(page.locator("#network-mode")).to_contain_text("HTTPS")
                assert page.locator('a[href*="172.18."]').count() == 0
                expect(page.locator("#account-workflow + ol")).to_contain_text("Captain")

                # An active Team can use both file upload and sample submission.
                page.goto(origin)
                workspace()
                view("system")
                logout()
                login("qa.player")
                workspace()
                view("upload")
                page.fill("#account-team-create [name=slug]", "qa-review-team")
                page.fill("#account-team-create [name=display_name]", "Đội kiểm thử giao diện")
                page.click("#account-team-create [type=submit]")
                expect(page.locator("#account-team-activate")).to_be_visible()
                expect(page.locator("#bot-file")).to_be_enabled()
                expect(page.locator("[data-sample=python]")).to_be_enabled()
                page.click("[data-sample=python]")
                expect(page.locator("#bot-library")).to_contain_text("Bot mẫu python", timeout=30000)
                page.click("#account-team-activate")
                expect(page.locator("#account-team-status")).to_contain_text("ACTIVE")
                view("official")
                expect(page.locator("#official-match-list")).to_contain_text("Đội chưa có lịch đấu")

                for width in (360, 375, 390, 414, 768, 1024, 1366, 1440):
                    page.set_viewport_size({"width": width, "height": 936})
                    for name in ("upload", "official", "scrimmage", "rules", "standings"):
                        view(name)
                        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, name)
                    if width == 390:
                        page.screenshot(path=str(evidence / "player-mobile.png"), full_page=True, animations="disabled")
                logout()
                for width in (360, 390, 768, 1363):
                    page.set_viewport_size({"width": width, "height": 936})
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, "landing")
                page.set_viewport_size({"width": 1363, "height": 936})
                assert float(page.locator("#landing-status").evaluate("node => parseFloat(getComputedStyle(node).fontSize)")) >= 13
                assert not errors, errors
                browser.close()
        finally:
            server.should_exit = True
            thread.join(timeout=20)
            if thread.is_alive():
                raise RuntimeError("Temporary UI review server did not stop")
    print("PASS UI review: account forms/contact, docs/retry/return, role routing, Team/upload/sample, empty states, alignment, HTTPS LAN, 8 widths")


if __name__ == "__main__":
    run()
