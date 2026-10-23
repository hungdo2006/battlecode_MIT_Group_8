"""Browser QA for Account-Only UI using only a temporary native data directory."""
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright
import uvicorn

from backend.account_database import AccountDatabase, transaction
from backend.admin_cli import bootstrap_admin
from backend.auth_http import HTTPAuthSettings
from backend.auth_limits import AuthRateLimiter
from backend.auth_service import AuthService
from backend.main import create_app
from backend.writer_lock import WriterLock


PASSWORD = "account-only browser QA passphrase 93"


def available_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def seed(base):
    data = base / "data"
    bootstrap_admin(data, "qa.admin", PASSWORD, "QA Admin")
    with WriterLock(data) as writer, AccountDatabase(data).writer_connection(writer) as connection:
        auth = AuthService(connection, writer, login_limiter=AuthRateLimiter())
        admin = auth.login("qa.admin", PASSWORD, audience="ADMIN", source_key="browser-qa").principal
        invitation = auth.issue_invitation(admin, "qa.player", name="QA Player")
        auth.activate(invitation.token, PASSWORD)


def wait_ready(url):
    opener = build_opener(ProxyHandler({}))
    for _ in range(100):
        try:
            with opener.open(url + "/api/health", timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(.05)
    raise RuntimeError("Temporary Account-Only server did not become ready")


def run():
    with tempfile.TemporaryDirectory(prefix="neon-account-ui-") as folder:
        base, port = Path(folder), available_port()
        seed(base)
        origin = f"http://127.0.0.1:{port}"
        settings = HTTPAuthSettings(enabled=True, account_only=True, self_registration=True,
                                    origins=(origin,), allow_http=True)
        application = create_app(base, tick_seconds=.01, account_http=settings)
        server = uvicorn.Server(uvicorn.Config(
            application, host="127.0.0.1",
            port=port, log_level="error"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            wait_ready(origin)
            errors = []
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="chrome", headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 900})
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                auth_posts = []
                def record_auth_post(request):
                    path = urlsplit(request.url).path
                    if request.method == "POST" and "/auth/" in path:
                        auth_posts.append((path, "x-csrf-token" in request.headers))
                page.on("request", record_auth_post)
                page.goto(origin, wait_until="domcontentloaded")
                dialog = page.locator("#account-dialog")
                landing = page.locator("#account-landing")
                landing.wait_for(state="visible")
                page.wait_for_function("!document.querySelector('#landing-login').disabled")
                assert not dialog.is_visible()
                assert page.locator(".shell").is_hidden()
                assert page.locator("#landing-register").is_enabled()
                # Public self-registration: one login, no user-selected role.
                assert page.locator("#account-login-form [name=audience]").count() == 0
                page.click("#landing-register")
                dialog.wait_for(state="visible")
                assert page.locator("#account-register-form").is_visible()
                page.fill("#account-register-form [name=username]", "qa_new")
                if page.locator("#account-register-name-field").is_visible():
                    page.fill("#account-register-form [name=display_name]", "QA New")
                if page.locator("#account-register-email-field").is_visible():
                    page.fill("#account-register-form [name=email]", "qa.new@example.org")
                page.fill("#account-register-form [name=password]", PASSWORD)
                page.fill("#account-register-form [name=confirm_password]", PASSWORD)
                page.click("#account-register-form [type=submit]")
                page.locator("#account-login-form").wait_for(state="visible")
                assert page.locator("#account-username").input_value() == "qa_new"
                assert ("/api/account/auth/register", False) in auth_posts, auth_posts
                page.fill("#account-login-form [name=password]", PASSWORD)
                page.click("#account-login-form [type=submit]")
                page.wait_for_function("document.querySelector('#participant-role').textContent === 'PLAYER'")
                page.wait_for_function("app.initialized && !app.initializing")
                assert ("/api/account/auth/login", False) in auth_posts, auth_posts
                assert not any("/account/auth/" in path and path != "/api/account/auth/register"
                               and path != "/api/account/auth/login" for path, _ in auth_posts), auth_posts
                assert not dialog.is_visible()
                assert not landing.is_visible()
                assert page.locator(".workspace-context").is_visible()
                page.click("#user-menu > summary")
                page.click("#organizer-toggle")
                landing.wait_for(state="visible")
                assert not dialog.is_visible()
                page.click("#landing-login")
                dialog.wait_for(state="visible")

                page.fill("#account-username", "qa.admin")
                page.fill("#account-login-form [name=password]", PASSWORD)
                page.click("#account-login-form [type=submit]")
                page.wait_for_function("document.querySelector('#participant-role').textContent === 'ADMIN'")
                page.wait_for_function("app.initialized && !app.initializing")
                assert page.locator("#participant-role").text_content() == "ADMIN"
                assert not dialog.is_visible() and page.locator("#organizer-toggle").text_content() == "Đăng xuất"
                assert page.locator('.nav-item[data-view="upload"]').is_hidden()
                assert page.locator('.nav-item[data-view="create"]').is_hidden()
                assert page.locator('.nav-item[data-view="watch"]').is_visible()
                assert page.locator('.docs-link').is_hidden()
                page.wait_for_function("!document.querySelector('#workspace-game-select').disabled")
                assert page.locator("#workspace-game-select").is_enabled()

                # Failed/ambiguous logout must retain identity and offer retry;
                # none of these responses confirms server-side revocation.
                logout_url = origin + "/api/admin/auth/logout"
                for failure in ("unavailable", "network", "unconfirmed"):
                    def fail_logout(route, failure=failure):
                        if failure == "network":
                            route.abort("failed")
                        else:
                            route.fulfill(status=503 if failure == "unavailable" else 200,
                                          content_type="application/json",
                                          body='{"detail":"QA unavailable"}' if failure == "unavailable" else '{}')
                    page.route(logout_url, fail_logout)
                    page.click("#user-menu > summary")
                    page.click("#organizer-toggle")
                    page.wait_for_function("document.querySelector('#organizer-toggle').textContent === 'Thử lại đăng xuất'")
                    assert not dialog.is_visible()
                    assert page.locator("#participant-role").text_content() == "ADMIN"
                    assert "Chưa xác nhận đăng xuất" in page.locator("#toast").inner_text()
                    assert page.evaluate("fetch('/api/admin/auth/me').then(r => r.status)") == 200
                    page.unroute(logout_url, fail_logout)

                page.click("#user-menu > summary")
                page.click("#organizer-toggle")
                landing.wait_for(state="visible")
                assert not dialog.is_visible()
                assert "Đã đăng xuất an toàn" in page.locator("#landing-status").inner_text()
                page.click("#landing-login")
                dialog.wait_for(state="visible")
                page.fill("#account-username", "qa.player")
                page.fill("#account-login-form [name=password]", PASSWORD)
                page.click("#account-login-form [type=submit]")
                page.wait_for_function("document.querySelector('#participant-role').textContent === 'PLAYER'")
                page.wait_for_function("app.initialized && !app.initializing")
                assert page.locator('.nav-item[data-view="upload"]').is_visible()
                # A returning authenticated Player must skip the welcome screen.
                page.goto(origin + "/#official", wait_until="domcontentloaded")
                page.reload(wait_until="domcontentloaded")
                page.wait_for_function("app.initialized && document.querySelector('#participant-role').textContent === 'PLAYER'")
                assert not landing.is_visible() and not dialog.is_visible()
                assert page.locator("#view-official").is_visible()
                assert page.locator('.nav-item[data-view="create"]').is_hidden()
                assert page.locator('.nav-item[data-view="watch"]').is_visible()
                assert page.locator('.nav-item[data-view="scrimmage"]').is_visible()
                # Team workspace intentionally lives in Upload, not Home.
                # Navigate through the real UI before asserting its visibility.
                page.locator('.nav-item[data-view="upload"]').click()
                page.wait_for_function("window.location.hash === '#upload'")
                page.locator("#account-team-panel").wait_for(state="visible")
                assert page.locator("#account-team-create").is_visible()
                assert page.locator("#account-team-inbox").is_hidden()  # No pending invitations.
                assert page.locator("#workspace-game-select").is_disabled()
                # Team preparation has its own game scope, independent of
                # the read-only server default and its legacy lock.
                global_game_writes = []
                page.on("request", lambda request: global_game_writes.append(request.url)
                        if request.method == "PUT" and request.url.endswith("/games/selected") else None)
                page.click("#upload-workflow-details > summary")
                expect_game = page.locator("#upload-game")
                assert expect_game.is_enabled()
                expect_game.select_option("ott_advanced")
                page.wait_for_function("document.querySelector('#sample-list [data-game-id=ott_advanced]') !== null")
                assert page.evaluate("app.competition.selected_game_id") == "robot_battle"
                assert global_game_writes == []
                expect_game.select_option("robot_battle")
                page.click("#upload-workflow-details > summary")
                assert page.evaluate("""() => [...document.querySelectorAll('input[pattern]')].every(input => {
                    const pattern = new RegExp('^(?:' + input.pattern + ')$', 'v');
                    return pattern instanceof RegExp;
                })""")
                assert page.evaluate("fetch('/api/session').then(r => r.status)") == 410

                # The responsive shell uses one real navigation tree. Check
                # keyboard containment, dismissal and role-gated destinations.
                page.set_viewport_size({"width": 390, "height": 844})
                navigation = page.locator("#workspace-navigation")
                toggle = page.locator("#nav-toggle")
                navigation.wait_for(state="hidden")
                toggle.click()
                page.wait_for_function("document.activeElement.id === 'nav-close'")
                assert toggle.get_attribute("aria-expanded") == "true"
                assert navigation.get_attribute("aria-modal") == "true"
                assert page.locator(".shell").evaluate("node => node.inert")
                assert navigation.locator('[data-view="create"]').is_hidden()
                assert navigation.locator('[data-view="watch"]').is_visible()
                assert navigation.locator('[data-view="scrimmage"]').is_visible()
                # Last visible link -> Tab returns to the first control.
                controls = navigation.locator('a[href], button:not(:disabled), summary, [tabindex="0"]').filter(visible=True)
                controls.last.focus()
                page.keyboard.press("Tab")
                assert controls.first.evaluate("node => node === document.activeElement")
                page.keyboard.press("Shift+Tab")
                assert controls.last.evaluate("node => node === document.activeElement")
                # Closed details must contribute its summary, but not hidden
                # child links, to the modal's keyboard cycle.
                navigation.locator("#nav-advanced > summary").focus()
                page.keyboard.press("Enter")
                controls = navigation.locator('a[href], button:not(:disabled), summary, [tabindex="0"]').filter(visible=True)
                controls.last.focus()
                page.keyboard.press("Tab")
                assert controls.first.evaluate("node => node === document.activeElement")
                page.keyboard.press("Escape")
                assert toggle.evaluate("node => node === document.activeElement")
                assert not page.locator(".shell").evaluate("node => node.inert")
                assert navigation.evaluate("node => node.inert")
                toggle.click()
                page.locator("#nav-backdrop").click(position={"x": 370, "y": 100})
                assert toggle.get_attribute("aria-expanded") == "false"

                for width, height in ((360, 800), (390, 844), (768, 1024)):
                    page.set_viewport_size({"width": width, "height": height})
                    for view in ("home", "upload", "standings", "tournaments", "official", "scrimmage", "watch", "seasons", "profile", "rules"):
                        if view == "profile":
                            page.click("#user-menu > summary")
                            page.locator('#user-menu [data-view="profile"]').click()
                            assert page.locator("#view-profile").is_visible()
                            assert not page.locator(".workspace-context").is_visible()
                            continue
                        toggle.click()
                        navigation.locator(f'[data-view="{view}"]').click()
                        assert page.locator(f"#view-{view}").is_visible()
                        assert toggle.get_attribute("aria-expanded") == "false"
                        assert not page.evaluate(
                            "document.documentElement.scrollWidth > window.innerWidth"
                        ), (width, view)
                    if width < 768:
                        assert page.locator("#upload-form [name=name]").evaluate(
                            "node => getComputedStyle(node).fontSize === '16px'"
                        )
                # Resizing an open drawer restores desktop navigation and
                # releases the workspace instead of leaving it inert.
                toggle.click()
                page.set_viewport_size({"width": 1440, "height": 900})
                assert navigation.is_visible()
                assert not navigation.evaluate("node => node.inert")
                assert not page.locator(".shell").evaluate("node => node.inert")
                assert navigation.get_attribute("aria-modal") is None

                runtime = application.state.account_http
                with runtime.database.writer_connection(runtime.writer) as connection, transaction(connection):
                    connection.execute("""UPDATE auth_sessions SET revoked_at=created_at
                        WHERE audience='PLAYER' AND revoked_at IS NULL""")
                # Account-Only's official calendar refreshes every 10 seconds;
                # allow a full interval plus headroom for the auth WS fallback.
                landing.wait_for(state="visible", timeout=16000)
                page.wait_for_function("document.querySelector('#participant-role').textContent === 'SIGNED OUT'")
                assert not dialog.is_visible()
                assert page.locator(".shell").is_hidden()
                assert page.locator("#workspace-game-select").is_disabled()
                # PR #17's password field is named new_password, while signup
                # uses password. Shared confirmation validation must support
                # both and still reject a mismatched confirmation.
                page.click("#landing-login")
                page.fill("#account-username", "qa.player")
                page.fill("#account-login-form [name=password]", PASSWORD)
                page.click("#account-login-form [type=submit]")
                page.wait_for_function("app.initialized && !app.initializing")
                other = page.context.new_page()
                other.goto(origin)
                other.wait_for_function("app.initialized && !app.initializing")
                page.evaluate("visitWorkspace(workspaceLink('profile'))")
                page.fill("#profile-password-form [name=current_password]", PASSWORD)
                changed = "QA changed profile password test-only 2026"
                page.fill("#profile-password-form [name=new_password]", changed)
                page.fill("#profile-password-form [name=confirm_password]", changed + " mismatch")
                page.click("#profile-password-form [type=submit]")
                assert "Hai mật khẩu chưa trùng" in page.locator("#profile-password-form .field-error:visible").inner_text()
                page.fill("#profile-password-form [name=confirm_password]", changed)
                page.click("#profile-password-form [type=submit]")
                landing.wait_for(state="visible")
                other.locator("#account-landing").wait_for(state="visible", timeout=16000)
                assert not other.evaluate("!!app.account || !!app.match || app.frames.length > 0")
                assert not errors, errors
                browser.close()
        finally:
            server.should_exit = True
            thread.join(timeout=20)
            if thread.is_alive():
                raise RuntimeError("Temporary Account-Only server did not stop cleanly")
    print("PASS Account-Only browser UI: landing, signup/login, session restore, logout/retry, mobile navigation/focus/layout, revocation, profile password confirmation and multi-tab logout, legacy 410")


if __name__ == "__main__":
    run()
