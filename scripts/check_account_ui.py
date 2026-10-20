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
                page = browser.new_page(viewport={"width": 1440, "height": 900})
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
                page.click("#account-register-form [type=submit]")
                page.locator("#account-login-form").wait_for(state="visible")
                assert page.locator("#account-username").input_value() == "qa_new"
                assert ("/api/account/auth/register", False) in auth_posts, auth_posts
                page.fill("#account-login-form [name=password]", PASSWORD)
                page.click("#account-login-form [type=submit]")
                page.wait_for_function("document.querySelector('#participant-role').textContent === 'PLAYER'")
                assert ("/api/account/auth/login", False) in auth_posts, auth_posts
                assert not any("/account/auth/" in path and path != "/api/account/auth/register"
                               and path != "/api/account/auth/login" for path, _ in auth_posts), auth_posts
                assert not dialog.is_visible()
                assert not landing.is_visible()
                assert page.locator("#account-mode-note").is_visible()
                page.click("#organizer-toggle")
                landing.wait_for(state="visible")
                assert not dialog.is_visible()
                page.click("#landing-login")
                dialog.wait_for(state="visible")

                page.fill("#account-username", "qa.admin")
                page.fill("#account-login-form [name=password]", PASSWORD)
                page.click("#account-login-form [type=submit]")
                page.wait_for_function("document.querySelector('#participant-role').textContent === 'ADMIN'")
                assert page.locator("#participant-role").inner_text() == "ADMIN"
                assert not dialog.is_visible() and page.locator("#organizer-toggle").inner_text() == "Đăng xuất"
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
                    page.click("#organizer-toggle")
                    page.wait_for_function("document.querySelector('#organizer-toggle').textContent === 'Thử lại đăng xuất'")
                    assert not dialog.is_visible()
                    assert page.locator("#participant-role").inner_text() == "ADMIN"
                    assert "Chưa xác nhận đăng xuất" in page.locator("#toast").inner_text()
                    assert page.evaluate("fetch('/api/admin/auth/me').then(r => r.status)") == 200
                    page.unroute(logout_url, fail_logout)

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
                assert page.locator('.nav-item[data-view="upload"]').is_visible()
                # A returning authenticated Player must skip the welcome screen.
                page.reload(wait_until="domcontentloaded")
                page.wait_for_function("document.querySelector('#participant-role').textContent === 'PLAYER'")
                assert not landing.is_visible() and not dialog.is_visible()
                assert page.locator('.nav-item[data-view="create"]').is_hidden()
                assert page.locator('.nav-item[data-view="watch"]').is_hidden()
                # Team workspace intentionally lives in Upload, not Home.
                # Navigate through the real UI before asserting its visibility.
                page.locator('.nav-item[data-view="upload"]').click()
                page.wait_for_function("window.location.hash === '#upload'")
                page.locator("#account-team-panel").wait_for(state="visible")
                assert page.locator("#account-team-create").is_visible()
                assert page.locator("#account-team-inbox").is_visible()
                assert page.locator("#workspace-game-select").is_disabled()
                assert page.evaluate("fetch('/api/session').then(r => r.status)") == 410

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
                assert not errors, errors
                browser.close()
        finally:
            server.should_exit = True
            thread.join(timeout=20)
            if thread.is_alive():
                raise RuntimeError("Temporary Account-Only server did not stop cleanly")
    print("PASS Account-Only browser UI: landing, signup/login, session restore, logout/retry, revocation, legacy 410")


if __name__ == "__main__":
    run()
