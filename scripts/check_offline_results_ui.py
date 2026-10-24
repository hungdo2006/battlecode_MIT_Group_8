"""Native localhost browser acceptance with a synthetic signed event.

Does NOT run Docker, an offline competition, LAN TLS or independent online staging.
Secrets stay in memory; only public/preview screenshots and a summary are saved.
"""
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading

import uvicorn
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.auth_http import HTTPAuthSettings
from backend.main import create_app
from backend.offline_results import export_package
from scripts.check_account_ui import PASSWORD, available_port, seed, wait_ready


def run():
    evidence = ROOT / ".qa-evidence" / "phase-a"
    evidence.mkdir(parents=True, exist_ok=True)
    previous = {key: os.environ.get(key) for key in ("ARENA_OFFLINE_RESULTS_KEY", "ARENA_OFFLINE_SITE_ID")}
    os.environ["ARENA_OFFLINE_RESULTS_KEY"] = secrets.token_urlsafe(48)
    os.environ["ARENA_OFFLINE_SITE_ID"] = "qa-synthetic-school"
    try:
        with tempfile.TemporaryDirectory(prefix="neon-offline-ui-") as folder:
            base = Path(folder)
            seed(base)
            detail = {
                "id": "qa-synthetic-final", "name": "QA Offline School", "game_id": "robot_battle",
                "format": "single_elimination", "status": "COMPLETED",
                "teams": [{"team_id": "a", "team_name_snapshot": "QA Alpha"},
                          {"team_id": "b", "team_name_snapshot": "QA Beta"}],
                "standings": [], "groups": [],
                "fixtures": [{"round_number": 1, "stage": "KNOCKOUT", "team_a_id": "a",
                              "team_b_id": "b", "match_status": "COMPLETED", "outcome": {}}],
                "bracket": [{"round_number": 1, "status": "COMPLETED", "team_a_id": "a",
                             "team_b_id": "b", "winner_team_id": "b"},
                            {"round_number": 2, "status": "BYE", "conditional_status": "SKIPPED",
                             "team_a_id": None, "team_b_id": None, "winner_team_id": "b"}],
            }
            package = export_package(detail)
            good = base / "synthetic-results.json"
            good.write_text(json.dumps(package), encoding="utf-8")
            bad = base / "tampered-results.json"
            bad.write_text(good.read_text().replace("QA Offline School", "Tampered School"), encoding="utf-8")
            origin = f"http://127.0.0.1:{available_port()}"
            settings = HTTPAuthSettings(enabled=True, account_only=True, origins=(origin,), allow_http=True)
            server = uvicorn.Server(uvicorn.Config(create_app(base, account_http=settings),
                host="127.0.0.1", port=int(origin.rsplit(":", 1)[1]), log_level="error"))
            thread = threading.Thread(target=server.run, daemon=True)
            thread.start()
            try:
                wait_ready(origin)
                errors = []
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(channel="chrome", headless=True)
                    try:
                        admin = browser.new_page(viewport={"width": 1440, "height": 1000})
                        admin.on("pageerror", lambda error: errors.append(str(error)))
                        admin.goto(origin)
                        admin.click("#landing-login")
                        admin.fill("#account-username", "qa.admin")
                        admin.fill("#account-login-form [name=password]", PASSWORD)
                        admin.click("#account-login-form [type=submit]")
                        admin.wait_for_function("app.initialized && !app.initializing")
                        admin.evaluate("location.hash='tournaments'")
                        expect(admin.locator("#offline-import-panel")).to_be_visible()
                        admin.click("#offline-import-panel > summary")

                        def preview(file):
                            admin.locator("#offline-import-file").set_input_files(str(file))
                            expect(admin.locator("#offline-import-confirm")).to_be_disabled()
                            admin.click("#offline-import-preview")

                        preview(good)
                        expect(admin.locator("#offline-import-confirm")).to_be_enabled()
                        expect(admin.locator("#offline-import-summary")).to_contain_text("2 đội · 1 trận")
                        assert not (base / "data/offline_publications.json").exists()
                        admin.screenshot(path=str(evidence / "verified-preview.png"), full_page=True, animations="disabled")
                        preview(bad)
                        expect(admin.locator("#offline-import-feedback")).to_contain_text("Chữ ký không hợp lệ")
                        expect(admin.locator("#offline-import-confirm")).to_be_disabled()
                        assert not (base / "data/offline_publications.json").exists()

                        def publish():
                            preview(good)
                            expect(admin.locator("#offline-import-confirm")).to_be_enabled()
                            admin.click("#offline-import-confirm")
                            admin.locator("dialog[open]").get_by_role("button", name="Công bố", exact=True).click()

                        publish()
                        expect(admin.locator("#offline-import-feedback")).to_contain_text("Đã công bố kết quả")
                        publish()
                        expect(admin.locator("#offline-import-feedback")).to_contain_text("đã được công bố trước đó")

                        public = browser.new_page(viewport={"width": 1440, "height": 1000})
                        public.on("pageerror", lambda error: errors.append(str(error)))
                        public.goto(origin + "/results")
                        expect(public.locator("#results article")).to_have_count(1)
                        expect(public.locator("#results h2")).to_have_text("QA Offline School")
                        public.get_by_text("Nhánh đấu offline", exact=True).click()
                        expect(public.locator("#results")).to_contain_text("Thắng: QA Beta")
                        expect(public.locator("#results")).to_contain_text("Không cần thi đấu")
                        public.get_by_text("Kết quả 1 trận", exact=True).click()
                        expect(public.locator("#results")).to_contain_text("QA Alpha – QA Beta · Hòa")
                        assert public.locator('a[href*="replay"], a[href*="source"]').count() == 0
                        public.screenshot(path=str(evidence / "public-results-desktop.png"), full_page=True)
                        public.set_viewport_size({"width": 390, "height": 844})
                        assert public.evaluate("document.documentElement.scrollWidth <= innerWidth")
                        public.screenshot(path=str(evidence / "public-results-mobile.png"), full_page=True)
                        assert not errors, errors
                    finally:
                        browser.close()
            finally:
                server.should_exit = True
                thread.join(timeout=20)
                if thread.is_alive():
                    raise RuntimeError("Temporary offline-results UI server did not stop")
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    print("PASS native browser: signed synthetic preview without publish, file-change invalidation, tamper rejection, explicit publication, duplicate import, anonymous results/bracket/history, desktop/mobile")


if __name__ == "__main__":
    run()
