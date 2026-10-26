"""Development-only typography comparisons; production frontend stays unchanged.

python scripts/compare_landing_typography.py --prepare-fonts
python scripts/compare_landing_typography.py --capture
python scripts/compare_landing_typography.py --serve --port 8877

Candidates, licenses, generated preview CSS and screenshots are local artifacts
under ignored .qa-evidence/typography-refinement/. No production font switcher.
"""
import argparse
from contextlib import ExitStack, contextmanager
import hashlib
import json
from pathlib import Path
import sys
import threading
import unicodedata
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EVIDENCE = ROOT / ".qa-evidence" / "typography-refinement"
VARIANTS = {
    "a": {"label": "Refined Pixel", "font": "Review Handjet", "postscript": "Handjet",
          "size": "94px", "tablet": "78px", "mobile": "76px", "narrow": "68px",
          "section": "48px", "weight": "550", "tracking": "-.5px"},
    "b": {"label": "Modern Retro Hybrid", "font": "Review Space Grotesk", "postscript": "SpaceGrotesk",
          "size": "72px", "tablet": "60px", "mobile": "56px", "narrow": "48px",
          "section": "38px", "weight": "600", "tracking": "-2px"},
    "c": {"label": "Retro Monospace", "font": "Review IBM Plex Mono", "postscript": "IBMPlexMono",
          "size": "68px", "tablet": "52px", "mobile": "52px", "narrow": "44px",
          "section": "35px", "weight": "500", "tracking": "-1.8px"},
}
SOURCES = {
    "Handjet": ("handjet", "Handjet[ELGR,ELSH,wght].ttf"),
    "SpaceGrotesk": ("spacegrotesk", "SpaceGrotesk[wght].ttf"),
    "IBMPlexMono": ("ibmplexmono", "IBMPlexMono-Medium.ttf"),
    "PixelifySans": ("pixelifysans", "PixelifySans[wght].ttf"),
}
SAMPLE = "Viết code. Đấu trí. Để bot lo. Chơi bằng trí tưởng tượng. Cùng đội bước vào giải đấu. Ý tưởng của bạn."

COMMON_CSS = """
/* This stylesheet is served ONLY by the disposable localhost comparison app. */
@font-face { font-family: 'Review Handjet'; src: url('/__typography_assets/Handjet.woff2') format('woff2'); font-weight: 100 900; font-display: block; }
@font-face { font-family: 'Review Space Grotesk'; src: url('/__typography_assets/SpaceGrotesk.woff2') format('woff2'); font-weight: 300 700; font-display: block; }
@font-face { font-family: 'Review IBM Plex Mono'; src: url('/__typography_assets/IBMPlexMono.woff2') format('woff2'); font-weight: 500; font-display: block; }
.account-landing { --retro-muted: #b9b8b0; }
.account-landing .landing-copy h1 {
  font-family: var(--review-display), sans-serif; font-weight: var(--review-weight);
  font-size: var(--review-hero); line-height: 88px; min-height: 264px;
  letter-spacing: var(--review-tracking); font-synthesis: none;
}
.account-landing :is(.landing-section-heading h2, .landing-workflow-intro h2, .landing-closing h2) {
  font-family: var(--review-display), sans-serif; font-weight: var(--review-weight);
  font-size: var(--review-section); line-height: 1.26; letter-spacing: -.8px; font-synthesis: none;
}
.account-landing .landing-feature h3 {
  font-family: var(--retro-font-body); font-weight: 600; font-size: 22px;
  line-height: 1.4; letter-spacing: -.55px; min-height: 2.8em; max-width: none;
}
.account-landing .landing-lead { font-size: 16px; line-height: 1.8; }
.account-landing .landing-navigation, .account-landing .landing-navigation > a,
.account-landing .landing-nav-auth button { font-size: 14px; }
.account-landing .landing-action { font-size: 14px; }
.account-landing :is(.landing-feature p, .landing-workflow p, .landing-section-heading > p:last-child) { font-size: 14px; line-height: 1.85; }
.account-landing .landing-workflow h3 { font-size: 16px; line-height: 1.6; }
.account-landing :is(.landing-feature a, .landing-inline-link) { font-size: 14px; }
.account-landing :is(.landing-status, .landing-register-note, .landing-art h2) { font-size: 13px; line-height: 1.8; }
.account-landing .landing-languages { font-size: 12px; }
.account-landing .landing-languages .landing-language-note { font-size: 12px; }
.account-landing :is(.landing-window-bar, .landing-feature-top > span) { font-size: 11px; }
.account-landing .landing-eyebrow { font-size: 11px; line-height: 1.8; letter-spacing: .65px; }
.account-landing .landing-footer { font-size: 11px; }
.account-landing .landing-footer a { font-size: 13px; }
.account-landing .landing-footer-note { font-size: 10px; }
.account-landing .landing-closing h2 { font-size: calc(var(--review-section) * .8); }
.account-landing .landing-menu-toggle { font-size: 13px; }
body.account-landing-active #account-dialog h2 { font: 600 24px/1.5 Inter, sans-serif; letter-spacing: -.5px; }
@media (max-width: 1100px) {
  .account-landing .landing-copy h1 { font-size: var(--review-tablet); line-height: 74px; min-height: 222px; }
  .account-landing .landing-navigation { gap: 20px; }
}
@media (max-width: 900px) {
  .account-landing .landing-navigation { gap: 16px; }
  .account-landing .landing-feature h3 { font-size: 19px; }
  .account-landing .landing-feature-top > span { font-size: 10px; letter-spacing: 0; }
  .account-landing .landing-action { font-size: 13px; }
}
@media (max-width: 640px) {
  .account-landing .landing-copy h1 { font-size: var(--review-mobile); line-height: 74px; min-height: 222px; }
  .account-landing :is(.landing-section-heading h2, .landing-workflow-intro h2) { font-size: calc(var(--review-section) * .92); }
  .account-landing .landing-feature h3 { font-size: 22px; min-height: 0; }
  .account-landing .landing-actions { flex-direction: column; }
  .account-landing .landing-action { font-size: 14px; }
  .account-landing .landing-lead { font-size: 15px; }
  .account-landing .landing-art h2 { font-size: 12px; }
  .account-landing .landing-eyebrow { font-size: 10px; letter-spacing: .25px; }
  .account-landing .landing-footer > div { flex-wrap: wrap; font-size: 11px; }
  .account-landing .landing-workflow h3 { font-size: 15px; }
}
@media (max-width: 360px) {
  .account-landing .landing-copy h1 { font-size: var(--review-narrow); line-height: 66px; min-height: 198px; }
  .account-landing .landing-feature h3 { font-size: 20px; }
}
"""


def get(url):
    with urlopen(Request(url, headers={"User-Agent": "NEON-ARENA-local-typography-review"}), timeout=45) as response:
        return response.read()


def prepare_fonts():
    # fontTools/Brotli are review tools only, never application dependencies.
    for path in (EVIDENCE / "font-tools", ROOT / ".qa-evidence/retro-pixel/font-tools"):
        if path.exists():
            sys.path.insert(0, str(path))
    from fontTools.ttLib import TTFont
    folder = EVIDENCE / "fonts"
    folder.mkdir(parents=True, exist_ok=True)
    revision = json.loads(get("https://api.github.com/repos/google/fonts/commits/main"))["sha"]
    report = {"google_fonts_revision": revision, "fonts": {}}
    required = set(SAMPLE + "".join(chr(n) for n in range(0x1EA0, 0x1EFA)) + "ĐđĂăÂâÊêÔôƠơƯư")
    required |= set(unicodedata.normalize("NFD", SAMPLE))
    for key, (family, name) in SOURCES.items():
        root = f"https://raw.githubusercontent.com/google/fonts/{revision}/ofl/{family}/"
        data = get(root + quote(name, safe=""))
        source = folder / name
        source.write_bytes(data)
        license_data = get(root + "OFL.txt")
        (folder / f"{key}-OFL.txt").write_bytes(license_data)
        font = TTFont(source)
        cmap = font.getBestCmap()
        missing = sorted(c for c in required if not c.isspace() and ord(c) not in cmap)
        entry = {"url": root + quote(name, safe=""), "source_sha256": hashlib.sha256(data).hexdigest(),
                 "license": "SIL OFL 1.1", "missing_characters": missing,
                 "axes": {a.axisTag: [a.minValue, a.defaultValue, a.maxValue] for a in font["fvar"].axes} if "fvar" in font else {}}
        if key == "PixelifySans":
            entry["decision"] = "excluded: incomplete Vietnamese coverage" if missing else "not selected"
        else:
            if missing:
                raise ValueError(f"{key} lacks required Vietnamese glyphs: {missing!r}")
            font.flavor = "woff2"
            destination = folder / f"{key}.woff2"
            font.save(destination)
            entry["woff2_bytes"] = destination.stat().st_size
        report["fonts"][key] = entry
        print(f"{key}: {len(missing)} missing Vietnamese/sample characters", flush=True)
    (EVIDENCE / "font-coverage.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def write_styles():
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    for key, values in VARIANTS.items():
        css = COMMON_CSS + f"""
.account-landing {{ --review-display: '{values['font']}'; --review-hero: {values['size']};
 --review-tablet: {values['tablet']}; --review-mobile: {values['mobile']}; --review-narrow: {values['narrow']};
 --review-section: {values['section']}; --review-weight: {values['weight']}; --review-tracking: {values['tracking']}; }}
"""
        if key in {"a", "b"}:
            css += """
.account-landing .landing-eyebrow { font: 550 18px/1.3 'Review Handjet', monospace; letter-spacing: .6px; font-variation-settings: 'ELSH' 2, 'ELGR' 1; }
@media (max-width:640px) { .account-landing .landing-eyebrow { font-size: 16px; letter-spacing: .4px; } }
"""
        if key == "a":
            css += ".account-landing h1, .account-landing :is(.landing-section-heading h2, .landing-workflow-intro h2, .landing-closing h2) { font-variation-settings: 'ELSH' 2, 'ELGR' 1; }\n"
        if key == "b":
            css += """
.account-landing .landing-copy h1 > span { font-family: 'Review Handjet', monospace; font-size: 1.28em; font-weight: 550; letter-spacing: -.5px; font-variation-settings: 'ELSH' 2, 'ELGR' 1; }
"""
        if key == "c":
            css += ".account-landing :is(.landing-window-bar, .landing-languages) { font-family: 'Review IBM Plex Mono', monospace; font-weight: 500; }\n"
        (EVIDENCE / f"{key}.css").write_text(css, encoding="utf-8")


def configure_preview(application):
    from fastapi.responses import FileResponse, HTMLResponse
    from fastapi.staticfiles import StaticFiles
    application.mount("/__typography_assets", StaticFiles(directory=EVIDENCE / "fonts"), name="local-typography-fonts")

    @application.middleware("http")
    async def preview_only(request, call_next):
        if request.url.hostname not in {"127.0.0.1", "localhost"}:
            return await call_next(request)
        if request.url.path == "/" and request.query_params.get("typography") in VARIANTS:
            key = request.query_params["typography"]
            html = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
            html = html.replace("</head>", f'<style data-local-typography="{key}">\n' + (EVIDENCE / f"{key}.css").read_text(encoding="utf-8") + "\n</style></head>")
            return HTMLResponse(html, headers={"Cache-Control": "no-store"})
        if request.url.path == "/__typography/":
            board = EVIDENCE / "index.html"
            if board.exists():
                return FileResponse(board, headers={"Cache-Control": "no-store"})
            links = "".join(f'<li><a href="/?typography={k}">{k.upper()} — {v["label"]}</a></li>' for k, v in VARIANTS.items())
            return HTMLResponse('<!doctype html><html lang="vi"><meta charset="utf-8"><title>Typography review — local only</title><body style="background:#121212;color:#f2efe6;font:18px/2 system-ui;padding:40px"><h1>Typography review</h1><p>Bản so sánh cục bộ. Landing gốc được giữ nguyên.</p><ul><li><a href="/">Baseline — VT323</a></li>' + links + "</ul></body></html>")
        name = request.url.path.rsplit("/", 1)[-1]
        if request.url.path == f"/__typography/{name}" and name in {p.name for p in EVIDENCE.glob("*.png")}:
            return FileResponse(EVIDENCE / name)
        return await call_next(request)


@contextmanager
def preview_server(port=None):
    import uvicorn
    from scripts.check_retro_landing_ui import temporary_app
    from scripts.check_account_ui import available_port, wait_ready
    with temporary_app(port or available_port()) as (application, origin):
        configure_preview(application)
        server = uvicorn.Server(uvicorn.Config(application, host="127.0.0.1", port=int(origin.rsplit(":", 1)[1]), log_level="error"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            wait_ready(origin)
            yield origin
        finally:
            server.should_exit = True
            thread.join(timeout=20)
            if thread.is_alive():
                raise RuntimeError("Local typography server did not stop")


AUDIT = """() => {
  const root = document.querySelector('#account-landing');
  const w = document.documentElement.clientWidth;
  const overflowing = [...root.querySelectorAll('*')].filter(n => {
    if (!n.getClientRects().length || n.closest('.landing-skip')) return false;
    const r = n.getBoundingClientRect();
    return r.left < -1 || r.right > w + 1;
  }).map(n => n.id || n.className.baseVal || n.className);
  const clipped = [];
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const n = walker.currentNode, p = n.parentElement;
    if (!n.textContent.trim() || !p.getClientRects().length || p.closest('.landing-skip, svg')) continue;
    const range = document.createRange(); range.selectNodeContents(n);
    for (const r of range.getClientRects()) {
      if (r.left < -1 || r.right > w + 1) clipped.push(n.textContent.trim());
    }
  }
  const ids = [...document.querySelectorAll('[id]')].map(n => n.id);
  const h = document.querySelector('#landing-title');
  const hc = getComputedStyle(h);
  return {
    viewport: [innerWidth, innerHeight], scrollWidth: document.documentElement.scrollWidth,
    overflow: overflowing, clippedText: clipped, duplicateIds: ids.filter((v,i) => ids.indexOf(v) !== i),
    headline: {text: h.textContent, font: hc.fontFamily, size: hc.fontSize, lineHeight: hc.lineHeight, height: h.getBoundingClientRect().height},
    featureCardHeights: [...document.querySelectorAll('.landing-feature')].map(n => Math.round(n.getBoundingClientRect().height)),
    functionalType: Object.fromEntries(['.landing-lead','.landing-feature p','.landing-action','.landing-status','.landing-menu-toggle'].map(s=>[s,getComputedStyle(root.querySelector(s)).fontSize])),
    motionTokens: ['--retro-motion-feedback','--retro-motion-hover','--retro-motion-panel','--retro-motion-reveal','--retro-motion-hero'].map(k=>[k,getComputedStyle(root).getPropertyValue(k).trim()]),
    colors: ['--retro-bg','--retro-accent','--retro-cream'].map(k=>[k,getComputedStyle(root).getPropertyValue(k).trim()]),
    artwork: root.querySelector('.landing-art img').getAttribute('src'),
    text: root.innerText.replace(/\\s+/g,' ').trim()
  };
}"""


def platform_fonts(page, selector):
    client = page.context.new_cdp_session(page)
    try:
        client.send("DOM.enable")
        client.send("CSS.enable")
        root = client.send("DOM.getDocument")["root"]["nodeId"]
        node = client.send("DOM.querySelector", {"nodeId": root, "selector": selector})["nodeId"]
        return client.send("CSS.getPlatformFontsForNode", {"nodeId": node})["fonts"]
    finally:
        client.detach()


def uses_only(fonts, *prefixes):
    def normalized(value):
        return "".join(c for c in value.casefold() if c.isalnum())
    expected = tuple(normalized(p) for p in prefixes)
    return bool(fonts) and all(f["isCustomFont"] and normalized(f["postScriptName"]).startswith(expected) for f in fonts)


def write_review_board(port=8877):
    descriptions = {
        "a": "Handjet + Inter. Nét pixel rõ nhất; dáng chữ gọn hơn VT323.",
        "b": "Space Grotesk + Handjet + Inter. Chữ chính hiện đại, pixel ở điểm nhấn.",
        "c": "IBM Plex Mono + Inter. Cảm giác máy tính cổ, chữ đều và dễ phân biệt.",
    }
    cards = []
    for key, values in VARIANTS.items():
        cards.append(f'''<article><h2>{key.upper()} / {values['label']}</h2><p>{descriptions[key]}</p>
<a href="{key}-desktop.png"><img src="{key}-desktop-hero.png" alt="Hero desktop của phương án {key.upper()}"></a>
<nav><a href="{key}-desktop.png">Desktop đầy đủ</a><a href="{key}-mobile.png">Mobile đầy đủ</a><a href="{key}-narrow-mobile.png">320 px</a></nav>
<a class="preview" href="http://127.0.0.1:{port}/?typography={key}">Mở bản tương tác {key.upper()} ↗</a>
<a href="{key}-mobile.png"><img class="mobile" src="{key}-mobile-hero.png" alt="Hero mobile của phương án {key.upper()}"></a></article>''')
    html = '''<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="data:,"><title>NEON ARENA — Typography review</title><style>
*{box-sizing:border-box}body{margin:0;padding:40px;background:#121212;color:#f2efe6;font:15px/1.7 system-ui,sans-serif}header{max-width:1500px;margin:0 auto 30px}h1{font-size:32px;letter-spacing:-1px;margin:0 0 10px}h2{font-size:21px;letter-spacing:-.5px;margin:0}p{color:#b9b8b0;margin:8px 0 20px}a{color:#79e6c6;text-underline-offset:5px}main{max-width:1800px;margin:auto;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:22px}article{min-width:0;border:1px solid #363833;background:#1b1b1b;padding:22px}img{display:block;width:100%;height:auto;border:1px solid #363833}nav{display:flex;flex-wrap:wrap;gap:12px;margin:18px 0}a{min-height:30px}a:focus-visible{outline:2px solid #48d5ae;outline-offset:4px}.preview{display:inline-block;margin-bottom:22px}.mobile{max-width:300px;margin:0 auto}footer{max-width:1500px;margin:32px auto 0;color:#b9b8b0}header a{margin-right:22px}@media(max-width:900px){body{padding:20px}main{grid-template-columns:1fr}article{padding:18px}}@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto}}
</style></head><body><header><h1>NEON ARENA — Typography review</h1><p>Ba bản xem thử. Cùng nội dung, bảng màu, minh họa, cấu trúc và chuyển động. Landing hiện tại vẫn là baseline VT323.</p><a href="baseline-desktop.png">Baseline desktop</a><a href="baseline-mobile.png">Baseline mobile</a></header><main>'''
    html += "".join(cards) + "</main><footer>Ảnh chụp Chrome thực tế · Desktop 1440 px · Mobile 390 px · Chưa áp dụng phương án nào vào sản phẩm.</footer></body></html>"
    (EVIDENCE / "index.html").write_text(html, encoding="utf-8")


def capture():
    from playwright.sync_api import sync_playwright
    from scripts.check_account_ui import PASSWORD
    from scripts.check_retro_landing_ui import ready
    report = {"complete": False, "variants": {}, "errors": [], "assetFailures": [], "apiFailures": [], "sharedContent": True}
    baseline_contract = {}
    with ExitStack() as fixtures, sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        try:
            for key in ["baseline", *VARIANTS]:
                # Each comparison gets fresh data and unchanged production rate
                # limits. A synthetic multi-page audit must not share one IP bucket
                # across all variants and then mistake throttling for a UI defect.
                origin = fixtures.enter_context(preview_server())
                data = {"label": "VT323 baseline" if key == "baseline" else VARIANTS[key]["label"], "viewports": []}
                url = origin if key == "baseline" else origin + f"/?typography={key}"
                for width, height, label in [(1440, 1000, "desktop"), (768, 1024, "tablet"),
                                             (390, 844, "mobile"), (320, 760, "narrow-mobile")]:
                    context = browser.new_context(viewport={"width": width, "height": height})
                    page = context.new_page()
                    page.on("pageerror", lambda error: report["errors"].append(str(error)))
                    page.on("response", lambda response: report["assetFailures"].append({"url":response.url,"status":response.status})
                            if ("/static/" in response.url or "/__typography_assets/" in response.url) and response.status >= 400 else None)
                    page.on("response", lambda response: report["apiFailures"].append({"url":response.url,"status":response.status})
                            if "/api/" in response.url and response.status >= 429 else None)
                    ready(page, url)
                    audit = page.evaluate(AUDIT)
                    assert not audit["overflow"] and not audit["clippedText"] and not audit["duplicateIds"], (key, audit)
                    assert audit["scrollWidth"] <= width, (key, audit)
                    contract = {k: audit[k] for k in ["motionTokens", "colors", "artwork", "text"]}
                    if key == "baseline":
                        baseline_contract[width] = contract
                    else:
                        assert contract == baseline_contract[width], (key, "content/palette/art/motion drift")
                        font = VARIANTS[key]["postscript"]
                        actual = platform_fonts(page, "#landing-title")
                        assert uses_only(actual, *([font, "Handjet"] if key == "b" else [font])), (key, actual)
                        assert any(uses_only([f], font) for f in actual), (key, actual)
                        audit["platformFonts"] = actual
                        if key == "b":
                            actual_accent = platform_fonts(page, "#landing-title > span")
                            assert uses_only(actual_accent, "Handjet"), actual_accent
                            audit["accentFonts"] = actual_accent
                    for section in page.locator("[data-reveal]").all():
                        section.scroll_into_view_if_needed()
                        page.wait_for_timeout(560)
                    page.evaluate("window.scrollTo({top:0,behavior:'instant'})")
                    page.screenshot(path=str(EVIDENCE / f"{key}-{label}.png"), full_page=True)
                    page.locator(".landing-main").screenshot(path=str(EVIDENCE / f"{key}-{label}-hero.png"))
                    data["viewports"].append(audit)
                    if key != "baseline" and width == 390:
                        # Examine all requested Vietnamese words in NFC and NFD
                        # using the actual candidate face, including combining marks.
                        page.evaluate("""({text,font,weight}) => {
                          const n=document.createElement('div'); n.id='review-vietnamese-probe';
                          n.style.cssText=`position:fixed;inset:12px;background:#121212;color:#f2efe6;z-index:100;font: ${weight} 28px/1.8 '${font}';padding:16px;overflow:auto`;
                          n.textContent=text+' '+text.normalize('NFD'); document.body.append(n);
                        }""", {"text": SAMPLE, "font": VARIANTS[key]["font"], "weight": VARIANTS[key]["weight"]})
                        probe = platform_fonts(page, "#review-vietnamese-probe")
                        assert uses_only(probe, VARIANTS[key]["postscript"]), (key, probe)
                        data["vietnameseFonts"] = probe
                        page.locator("#review-vietnamese-probe").screenshot(path=str(EVIDENCE / f"{key}-vietnamese.png"))
                        page.locator("#review-vietnamese-probe").evaluate("n=>n.remove()")
                        page.evaluate("window.scrollTo({top:0,behavior:'instant'})")
                        menu = page.locator("#landing-menu-toggle")
                        menu.focus()
                        page.keyboard.press("Enter")
                        assert menu.get_attribute("aria-expanded") == "true"
                        page.keyboard.press("Tab")
                        assert page.evaluate("document.activeElement.textContent.trim()") == "Khám phá"
                        page.keyboard.press("Escape")
                        assert menu.evaluate("n=>n===document.activeElement")
                        page.click("#landing-register")
                        assert page.locator("#account-register-form").is_visible()
                        username = f"typography_{key}"
                        page.fill('#account-register-form [name="username"]', username)
                        if page.locator("#account-register-name-field").is_visible():
                            page.fill('#account-register-form [name="display_name"]', f"Typography {key.upper()}")
                        if page.locator("#account-register-email-field").is_visible():
                            page.fill('#account-register-form [name="email"]', f"typography.{key}@example.org")
                        page.fill('#account-register-form [name="password"]', PASSWORD)
                        page.fill('#account-register-form [name="confirm_password"]', PASSWORD)
                        page.click('#account-register-form [type="submit"]')
                        page.locator("#account-login-form").wait_for(state="visible")
                        assert page.locator("#account-username").input_value() == username
                        page.fill('#account-login-form [name="password"]', PASSWORD)
                        page.click('#account-login-form [type="submit"]')
                        page.wait_for_function("document.querySelector('#participant-role').textContent === 'PLAYER'")
                        page.wait_for_function("app.initialized && !app.initializing")
                        assert page.locator("#account-landing").is_hidden()
                        assert page.locator("#participant-role").text_content() == "PLAYER"
                        page.reload()
                        page.wait_for_function("document.querySelector('#participant-role').textContent === 'PLAYER'")
                        page.wait_for_function("app.initialized && !app.initializing")
                        assert page.locator("#account-landing").is_hidden()
                        page.click("#user-menu > summary")
                        page.click("#organizer-toggle")
                        page.locator("#account-landing").wait_for(state="visible")
                        page.click("#landing-login")
                        page.fill("#account-username", "qa.admin")
                        page.fill('#account-login-form [name="password"]', PASSWORD)
                        page.click('#account-login-form [type="submit"]')
                        page.wait_for_function("document.querySelector('#participant-role').textContent === 'ADMIN'")
                        page.wait_for_function("app.initialized && !app.initializing")
                        assert page.locator('.nav-item[data-view="upload"]').is_hidden()
                        page.click("#user-menu > summary")
                        page.click("#organizer-toggle")
                        page.locator("#account-landing").wait_for(state="visible")
                        data["authChecks"] = "PASS real registration, Player login/session restore/logout, Admin login/role gate/logout, mobile keyboard menu"
                        page.emulate_media(reduced_motion="reduce")
                        page.reload()
                        page.wait_for_function("!document.querySelector('#landing-login').disabled")
                        assert page.evaluate("document.querySelector('#account-landing').getAnimations({subtree:true}).length") == 0
                        data["reducedMotion"] = "PASS"
                    context.close()
                report["variants"][key] = data
                (EVIDENCE / "browser-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"PASS {key}: four viewport captures and typography checks", flush=True)
            assert not report["errors"] and not report["assetFailures"] and not report["apiFailures"], report
        finally:
            browser.close()
    report["complete"] = True
    (EVIDENCE / "browser-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Review evidence: {EVIDENCE}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-fonts", action="store_true")
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--port", type=int, default=8877)
    args = parser.parse_args()
    if args.prepare_fonts:
        prepare_fonts()
    if args.capture or args.serve:
        if 'font-family: "VT323";' not in (ROOT / "frontend/landing.css").read_text(encoding="utf-8"):
            parser.error("Historical A/B/C comparison targets frontend at 2c2cc75. Use an isolated checkout of that revision to reproduce it; review the adopted typography with scripts/check_retro_landing_ui.py instead.")
        if not (EVIDENCE / "font-coverage.json").exists():
            parser.error("Run --prepare-fonts first")
        write_styles()
    if args.capture:
        capture()
        write_review_board(args.port)
    if args.serve:
        import time
        with preview_server(args.port) as origin:
            print(f"Local comparisons: {origin}/__typography/", flush=True)
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass


if __name__ == "__main__":
    main()
