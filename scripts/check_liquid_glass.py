"""Phase 3.1 browser/material/cache regression on a disposable Docker sandbox.

Reuses the real three-client and Liquid Light workflows; never touches the
normal Compose project, volumes, credentials or live user data.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import shutil

from playwright.sync_api import sync_playwright

from check_docker import DockerCheck
import check_liquid_ui as liquid
from check_multiplayer_ui import check as multiplayer_check

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "docs/screenshots/glass-refinement/after"
VIEWPORTS = ((1920, 1080), (1440, 900), (1366, 768), (768, 1024))


def visible_blur_layers(page):
    return page.evaluate("""() => [...document.querySelectorAll('.glass-surface')].filter(n => {
      const r=n.getBoundingClientRect(), s=getComputedStyle(n);
      return s.backdropFilter !== 'none' && r.width && r.height && r.bottom>0 && r.top<innerHeight && r.right>0 && r.left<innerWidth;
    }).length""")


def secondary_contrast(page):
    """Measure real background pixels beside three text samples after compositing."""
    result = {}
    for selector in ('.stat-label', '.identity-bar small', '.competition-banner p'):
        node = page.locator(selector).first
        node.scroll_into_view_if_needed()
        box = node.bounding_box()
        color = node.evaluate('n => getComputedStyle(n).color')
        png = base64.b64encode(page.screenshot(animations='disabled')).decode('ascii')
        result[selector] = page.evaluate("""async ({png,box,color}) => {
          const picture=new Image(); picture.src='data:image/png;base64,'+png; await picture.decode();
          const canvas=document.createElement('canvas'); canvas.width=picture.width; canvas.height=picture.height;
          const ctx=canvas.getContext('2d'); ctx.drawImage(picture,0,0);
          const bg=[...ctx.getImageData(Math.max(0,Math.round(box.x)-3),Math.round(box.y+box.height/2),1,1).data].slice(0,3);
          const fg=color.match(/[\\d.]+/g).slice(0,3).map(Number);
          const lum = rgb => {const c=rgb.map(x=>x/255).map(x=>x<=.04045?x/12.92:((x+.055)/1.055)**2.4); return .2126*c[0]+.7152*c[1]+.0722*c[2];};
          return (Math.max(lum(fg),lum(bg))+.05)/(Math.min(lum(fg),lum(bg))+.05);
        }""", {'png':png, 'box':box, 'color':color})
        assert result[selector] >= 4.5, (selector, result[selector])
    return result


def verify_assets(request, url):
    assets = {}
    for route in ("/", "/lan", "/static/protocol.html"):
        response = request.get(url + route)
        assert response.status == 200
        references = re.findall(r'/static/(styles\.css|app\.js|renderers\.js|favicon\.svg)\?v=([a-f0-9]{12})', response.text())
        expected = {"styles.css", "favicon.svg", "app.js", "renderers.js"} if route == "/" else {"styles.css", "favicon.svg"}
        assert {name for name, _ in references} == expected, (route, references)
        for name, digest in references:
            body = (ROOT / "frontend" / name).read_bytes()
            assert digest == hashlib.sha256(body).hexdigest()[:12], (route, name, "stale HTML")
            asset = request.get(url + f"/static/{name}?v={digest}")
            assert asset.status == 200 and asset.body() == body, (route, name, "stale Docker asset")
            assert asset.headers.get("etag"), name
            cached = request.get(url + f"/static/{name}?v={digest}", headers={"If-None-Match": asset.headers["etag"]})
            assert cached.status == 304, (name, cached.status)
            assert "no-store" not in asset.headers.get("cache-control", "")
            assets[name] = digest
    assert len(assets) == 4, assets
    return assets


def material_checks(url, code):
    checks, errors = [], []
    def passed(name):
        checks.append(name)
        print("PASS", name, flush=True)

    liquid.OUTPUT = OUTPUT
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        contexts = [browser.new_context(viewport={"width":1440,"height":900}) for _ in range(2)]
        org, player = [context.new_page() for context in contexts]
        for page, name in ((org, "Organizer"), (player, "Nova")):
            page.on("pageerror", lambda error: errors.append(str(error)))
            liquid.initialize(page, url, name)
        assets = verify_assets(player.request, url)
        passed("Docker HTML/CSS/JS/SVG hashes match current source; ETag returns 304")

        glass = player.locator(".sidebar").evaluate("""node => {
          const s=getComputedStyle(node);
          return {background:s.backgroundColor, filter:s.backdropFilter, image:s.backgroundImage, shadow:s.boxShadow};
        }""")
        alpha = float(glass['background'].rstrip(')').split(',')[-1])
        assert 0 < alpha < .65 and "blur(" in glass["filter"], glass
        assert "linear-gradient" in glass["image"] and "inset" in glass["shadow"], glass
        assert player.locator(".glass-surface .glass-surface").count() == 0, "Avoid nested filters"
        assert player.locator('.glass-subtle').first.evaluate('n => getComputedStyle(n).backdropFilter') == 'none'
        for selector in (".canvas-wrap", "#arena", "input[name=name]", ".compiler-log"):
            assert player.locator(selector).first.evaluate("n => getComputedStyle(n).backdropFilter") == "none", selector
        transport = player.locator(".playback-bar").evaluate("n => {const s=getComputedStyle(n);return {margin:parseFloat(s.marginTop),radius:parseFloat(s.borderRadius),filter:s.backdropFilter};}")
        assert transport["margin"] > 0 and transport["radius"] >= 19 and "blur" in transport["filter"], transport
        passed("selective translucent materials/reflections; solid inputs/diagnostics/Canvas; floating transport")
        contrast = secondary_contrast(player)
        passed('three secondary text samples retain 4.5:1 contrast against actual composed background pixels')

        liquid.save(player, "overview.png")
        player.locator("#organizer-toggle").click()
        player.screenshot(path=str(OUTPUT / "organizer-dialog.png"), animations="disabled")
        player.keyboard.press("Escape")
        player.wait_for_function('!document.querySelector("#organizer-dialog").open')
        liquid.organize(org, code)
        if org.evaluate("app.competition.competition_locked"):
            org.locator("#competition-close").click(); liquid.confirm(org)
        org.wait_for_function("app.competition.can_edit")
        liquid.select_game(org, "robot_battle")
        liquid.save(org, "organizer.png")
        player.locator(".nav-item[data-view=upload]").click(); liquid.save(player, "submission.png")
        player.locator(".nav-item[data-view=create]").click(); liquid.save(player, "lobby.png")
        org.locator(".nav-item[data-view=create]").click(); liquid.save(org, "organizer-lobby.png")

        # Actual OS media preference, not an injected replacement stylesheet.
        cdp = contexts[1].new_cdp_session(player)
        cdp.send("Emulation.setEmulatedMedia", {"features":[{"name":"prefers-reduced-transparency","value":"reduce"}]})
        assert player.evaluate('matchMedia("(prefers-reduced-transparency: reduce)").matches')
        assert player.locator(".sidebar").evaluate('n => getComputedStyle(n).backdropFilter') == "none"
        assert player.locator(".sidebar").evaluate('n => getComputedStyle(n).backgroundColor') == "rgb(255, 255, 255)"
        cdp.send("Emulation.setEmulatedMedia", {"features":[]})
        passed("prefers-reduced-transparency uses opaque, blur-free surfaces")

        route_checks = 0
        matches = player.request.get(url + "/api/matches").json()
        for width, height in VIEWPORTS:
            for page, views in ((org, ("home","create","watch","rules")), (player, ("home","upload","create","watch","rules"))):
                page.set_viewport_size({"width":width,"height":height})
                for view in views:
                    page.locator(f".nav-item[data-view={view}]").click()
                    liquid.no_overflow(page)
                    assert visible_blur_layers(page) <= 4, (width, view, 'too many visible blur layers')
                    route_checks += 1
            for game in ("robot_battle", "ott_v2"):
                match = next(m for m in matches if m["game_id"] == game and m["status"] == "completed")
                player.evaluate("id => loadMatch(id)", match["id"])
                player.locator("#play-pause").click()
                player.locator("#timeline").evaluate("n => {n.value=Math.floor(Number(n.max)/2); n.dispatchEvent(new Event('input',{bubbles:true}));}")
                assert player.evaluate("app.paused && app.cursor > 0")
                liquid.no_overflow(player)
                # Transport is below the stage and its controls remain reachable.
                board = player.locator(".canvas-wrap").bounding_box()
                bar = player.locator(".playback-bar").bounding_box()
                assert bar["y"] >= board["y"] + board["height"], (board, bar)
                player.locator("#play-start").click()
                assert player.evaluate("!app.paused")
                player.locator("#play-pause").click()
                route_checks += 1
                if width in (1440, 1366):
                    liquid.save(player, f"arena-{game}-{width}.png")
            if width == 768:
                org.locator(".nav-item[data-view=rules]").click(); liquid.save(org, "organizer-768.png")
                player.locator(".nav-item[data-view=upload]").click(); liquid.save(player, "submission-768.png")
        passed(f"{route_checks} Organizer/Player/replay viewport checks at 1920, 1440x900, 1366x768, 768px")
        passed('at most four visible backdrop-filter surfaces on tested application routes')
        assert not errors, errors
        browser.close()
    return {"checks":checks, "assets":assets, "material":glass, "secondary_contrast":contrast, "javascript_errors":errors}


def main():
    global OUTPUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT, help="Separate screenshot/report directory for each visual pass")
    args = parser.parse_args()
    OUTPUT = args.output_dir.resolve()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    qa = DockerCheck()
    print("Liquid Glass QA project:", qa.project, flush=True)
    try:
        if not args.no_build:
            qa.compose("build", "arena", capture=False)
        qa.up(); qa.inspect()
        multiplayer_check(qa.url, qa.code, output_dir=OUTPUT)
        liquid.OUTPUT = OUTPUT
        existing = liquid.extra_checks(qa.url, qa.code)
        shutil.copyfile(OUTPUT / "submission.png", OUTPUT / "submission-ready.png")
        materials = material_checks(qa.url, qa.code)
        report = {"project":qa.project, "regression":existing, "liquid_glass":materials}
        (OUTPUT.parent / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=True, indent=2))
    finally:
        qa.cleanup()
        print("Dedicated QA resources removed; application data untouched.", flush=True)


if __name__ == "__main__":
    main()
