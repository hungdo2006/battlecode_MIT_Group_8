"""Real-browser landing review on temporary localhost data; never runs Docker/AWS.

python scripts/check_retro_landing_ui.py
python scripts/check_retro_landing_ui.py --output-dir .qa-evidence/typography-a-final
python scripts/check_retro_landing_ui.py --serve --port 8876

Checks the adopted Handjet typography; screenshots and JSON evidence default to
ignored .qa-evidence/retro-pixel/ (or the requested --output-dir).
The existing check_account_ui.py exercises full auth and workspace journeys.
"""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import uvicorn
from playwright.sync_api import sync_playwright
from backend.auth_http import HTTPAuthSettings
from backend.main import create_app
from backend.network import NetworkSettings
from scripts.check_account_ui import available_port, seed, wait_ready

EVIDENCE = ROOT / ".qa-evidence" / "retro-pixel"


@contextmanager
def temporary_app(port, *, self_registration=True):
    # These overrides apply only to this process and its disposable fixture.
    # In particular, do not attach a configured operational Sandbox/Remote Runner.
    previous = dict(os.environ)
    for key in list(os.environ):
        if key.startswith(("ARENA_", "SANDBOX_")):
            del os.environ[key]
    os.environ["ARENA_RUNNER"] = "legacy"
    try:
        with tempfile.TemporaryDirectory(prefix="neon-retro-review-") as folder:
            base = Path(folder)
            seed(base)
            origin = f"http://127.0.0.1:{port}"
            settings = HTTPAuthSettings(enabled=True, account_only=True,
                                        self_registration=self_registration,
                                        origins=(origin,), allow_http=True)
            yield create_app(base, tick_seconds=.01, account_http=settings,
                             network=NetworkSettings()), origin
    finally:
        os.environ.clear()
        os.environ.update(previous)


@contextmanager
def running_server(*, self_registration=True):
    port = available_port()
    with temporary_app(port, self_registration=self_registration) as (application, origin):
        server = uvicorn.Server(uvicorn.Config(application, host="127.0.0.1", port=port, log_level="error"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            wait_ready(origin)
            yield origin
        finally:
            server.should_exit = True
            thread.join(timeout=20)
            if thread.is_alive():
                raise RuntimeError("Disposable landing server did not stop")


def ready(page, origin):
    page.goto(origin, wait_until="domcontentloaded")
    page.wait_for_function("!document.querySelector('#landing-login').disabled")
    page.evaluate("document.fonts.ready")
    page.wait_for_timeout(950)


AUDIT = """() => {
  const root = document.getElementById('account-landing');
  const width = document.documentElement.clientWidth;
  const ids = [...document.querySelectorAll('[id]')].map(n => n.id);
  return {
    width, scrollWidth: document.documentElement.scrollWidth,
    overflow: [...root.querySelectorAll('*')].filter(n => {
      if (!n.getClientRects().length || n.closest('.landing-skip')) return false;
      const r = n.getBoundingClientRect();
      return r.width > 0 && (r.left < -1 || r.right > width + 1);
    }).map(n => n.id || n.className.baseVal || n.className).slice(0, 12),
    duplicateIds: ids.filter((id, i) => ids.indexOf(id) !== i),
    fontLoaded: [...document.fonts].some(f => f.family.includes('Handjet') && f.status === 'loaded'),
    headingFont: getComputedStyle(document.getElementById('landing-title')).fontFamily,
    mainLandmarks: [...document.querySelectorAll('main')].filter(n => n.getClientRects().length).length,
    artwork: root.querySelector('.landing-art img').naturalWidth,
    runningAnimations: root.getAnimations({subtree:true}).filter(a => a.playState === 'running').length,
    functionalType: Object.fromEntries(['.landing-lead','.landing-feature p','.landing-action','.landing-status'].map(s=>[s,getComputedStyle(root.querySelector(s)).fontSize])),
    colors: ['--retro-bg','--retro-accent','--retro-cream','--retro-muted'].map(k=>[k,getComputedStyle(root).getPropertyValue(k).trim()]),
    motionTokens: ['--retro-motion-feedback','--retro-motion-hover','--retro-motion-panel','--retro-motion-reveal','--retro-motion-hero'].map(k=>[k,getComputedStyle(root).getPropertyValue(k).trim()]),
    featureCardHeights: [...root.querySelectorAll('.landing-feature')].map(n=>Math.round(n.getBoundingClientRect().height))
  };
}"""


def actual_fonts(page, selector):
    client = page.context.new_cdp_session(page)
    try:
        client.send("DOM.enable")
        client.send("CSS.enable")
        root = client.send("DOM.getDocument")["root"]["nodeId"]
        node = client.send("DOM.querySelector", {"nodeId": root, "selector": selector})["nodeId"]
        return client.send("CSS.getPlatformFontsForNode", {"nodeId": node})["fonts"]
    finally:
        client.detach()


def check(evidence=EVIDENCE):
    evidence.mkdir(parents=True, exist_ok=True)
    errors, report = [], {"viewports": [], "checks": [], "assetFailures": []}
    with running_server() as origin, sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        try:
            for width, height, label in [(1440, 1000, "desktop"), (768, 1024, "tablet"),
                                         (390, 844, "mobile"), (360, 800, "small-mobile"),
                                         (320, 760, "minimum-mobile")]:
                context = browser.new_context(viewport={"width": width, "height": height})
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("response", lambda response: report["assetFailures"].append({"url":response.url,"status":response.status})
                        if "/static/" in response.url and response.status >= 400 else None)
                ready(page, origin)
                audit = page.evaluate(AUDIT)
                assert audit["scrollWidth"] <= audit["width"], audit
                assert not audit["overflow"] and not audit["duplicateIds"], audit
                assert audit["fontLoaded"] and audit["artwork"] > 0, audit
                assert audit["mainLandmarks"] == 1 and audit["runningAnimations"] == 0, audit
                display_fonts = {}
                for selector in ("#landing-title", "#landing-title > span", "#landing-features-title", "#landing-workflow-title", "#landing-closing-title"):
                    fonts = actual_fonts(page, selector)
                    assert fonts and all(f["isCustomFont"] and f["postScriptName"].startswith("Handjet") for f in fonts), (selector, fonts)
                    display_fonts[selector] = fonts
                audit["displayFonts"] = display_fonts
                audit["featureTitleFonts"] = actual_fonts(page, ".landing-feature h3")
                assert all(f["isCustomFont"] and f["postScriptName"].startswith("Inter") for f in audit["featureTitleFonts"]), audit
                clipped_text = page.evaluate("""() => {
                    const root=document.querySelector('#account-landing'), w=document.documentElement.clientWidth, result=[];
                    const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);
                    while(walker.nextNode()) {
                        const n=walker.currentNode, p=n.parentElement;
                        if(!n.textContent.trim() || !p.getClientRects().length || p.closest('.landing-skip, svg')) continue;
                        const range=document.createRange(); range.selectNodeContents(n);
                        if([...range.getClientRects()].some(r=>r.left < -1 || r.right > w+1)) result.push(n.textContent.trim());
                    }
                    return result;
                }""")
                assert not clipped_text, clipped_text
                audit["clippedText"] = clipped_text
                # Finish one-time section reveals before exporting full-page evidence.
                for section in page.locator("[data-reveal]").all():
                    section.scroll_into_view_if_needed()
                    page.wait_for_timeout(560)
                page.evaluate("window.scrollTo({top:0, behavior:'instant'})")
                page.screenshot(path=str(evidence / f"{label}.png"), full_page=True)
                page.locator(".landing-main").screenshot(path=str(evidence / f"{label}-hero.png"))
                report["viewports"].append({"viewport": [width, height], **audit})
                if width == 390:
                    toggle = page.locator("#landing-menu-toggle")
                    toggle.focus()
                    page.keyboard.press("Enter")
                    assert toggle.get_attribute("aria-expanded") == "true"
                    page.keyboard.press("Tab")
                    assert page.evaluate("document.activeElement.textContent.trim()") == "Khám phá"
                    page.keyboard.press("Escape")
                    assert toggle.get_attribute("aria-expanded") == "false"
                    assert toggle.evaluate("n => n === document.activeElement")
                    toggle.click()
                    page.locator('#landing-navigation a[href="#landing-features"]').click()
                    page.wait_for_function("window.scrollY > 300")
                    assert page.locator("#toast").is_hidden()
                    assert page.locator("#landing-features").evaluate("n => n === document.activeElement")
                    page.evaluate("window.scrollTo({top:0, behavior:'instant'})")
                    toggle.click()
                    page.locator('.landing-nav-auth [data-landing-auth="register"]').click()
                    assert page.locator("#account-register-form").is_visible()
                    page.wait_for_function("document.querySelector('#account-dialog').getAnimations().every(a => a.playState !== 'running')")
                    page.screenshot(path=str(evidence / "mobile-registration.png"))
                    page.click("#account-close")
                    page.locator('.landing-closing [data-landing-auth="login"]').click()
                    assert page.locator("#account-login-form").is_visible()
                    page.click("#account-close")
                    report["checks"].append("mobile menu: keyboard, Escape/focus return, section navigation; navbar registration and closing login proxy")
                context.close()

            reduced = browser.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
            page = reduced.new_page()
            ready(page, origin)
            assert page.evaluate("document.querySelector('#account-landing').getAnimations({subtree:true}).length") == 0
            page.locator("#landing-workflow").scroll_into_view_if_needed()
            assert page.locator("#landing-workflow").evaluate("n => getComputedStyle(n).opacity") == "1"
            report["checks"].append("reduced motion: no animations, all sections visible")
            reduced.close()

            fallback = browser.new_context(viewport={"width": 390, "height": 844}, java_script_enabled=False)
            page = fallback.new_page()
            page.goto(origin, wait_until="load")
            assert page.locator(".landing-feature:visible").count() == 3
            assert page.locator("#landing-navigation").is_visible()
            assert page.locator("#landing-title").is_visible()
            report["checks"].append("JavaScript disabled: readable content, visible navigation, no hidden reveal content")
            fallback.close()

            offline = browser.new_context(viewport={"width": 390, "height": 844})
            page = offline.new_page()
            page.route("**/api/health", lambda route: route.abort("failed"))
            page.goto(origin)
            page.locator("#landing-retry").wait_for(state="visible")
            assert page.locator("#landing-login").is_disabled()
            assert all(n.is_disabled() for n in page.locator("[data-landing-auth]").all())
            page.unroute("**/api/health")
            page.click("#landing-retry")
            page.wait_for_function("!document.querySelector('#landing-login').disabled")
            assert page.locator('.landing-closing [data-landing-auth="login"]').is_enabled()
            report["checks"].append("failed bootstrap: disabled auth entries, visible retry, successful real reconnect")
            offline.close()

            with running_server(self_registration=False) as closed_origin:
                context = browser.new_context(viewport={"width": 390, "height": 844})
                page = context.new_page()
                ready(page, closed_origin)
                assert page.locator("#landing-register").is_disabled()
                assert page.locator('[data-landing-auth="register"]').is_disabled()
                assert "chưa mở" in page.locator("#landing-register-note").inner_text()
                report["checks"].append("real server with registration closed: both registration entries disabled")
                context.close()
            assert not errors and not report["assetFailures"], {"errors":errors,"assets":report["assetFailures"]}
            report["pageErrors"] = errors
        finally:
            browser.close()
    (evidence / "browser-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PASS retro landing: 5 viewport layouts, pixel font, original SVG, keyboard/mobile navigation, auth proxies, reduced motion, no-JS, closed registration and reconnect")
    print(f"Screenshots and browser-report.json: {evidence}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=8876)
    parser.add_argument("--output-dir", type=Path, default=EVIDENCE)
    args = parser.parse_args()
    if args.serve:
        with temporary_app(args.port) as (application, origin):
            print(f"Disposable review: {origin}", flush=True)
            uvicorn.run(application, host="127.0.0.1", port=args.port, log_level="error")
    else:
        check(args.output_dir)
