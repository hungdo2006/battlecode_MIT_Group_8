"""Populated, disposable Retro Pixel UI review. Never uses live data or AWS.

python scripts/review_workspace_redesign.py --serve --port 8880
python scripts/review_workspace_redesign.py --capture

Creates real local accounts/Teams, trusted sample bots, tournaments, Seasons,
practice/official matches and saved replays. Layout fixtures have larger request
budgets; the separate account browser suite tests unchanged default budgets.
"""
import argparse
import base64
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EVIDENCE = ROOT / ".qa-evidence/application-redesign"

import httpx
import uvicorn
from backend.auth_limits import RateLimits
from scripts.check_account_ui import PASSWORD, available_port, wait_ready
from scripts.check_retro_landing_ui import temporary_app


def request(client, method, path, payload=None):
    response = client.request(method, path, json=payload)
    if response.status_code >= 400:
        raise RuntimeError(f"Local fixture {method} {path}: HTTP {response.status_code}: {response.json().get('detail', '')}")
    return response.json()


@contextmanager
def account_client(origin, username, role):
    with httpx.Client(base_url=origin, headers={"Origin":origin}, trust_env=False, timeout=60) as client:
        request(client, "POST", "/api/account/auth/login", {"username":username,"password":PASSWORD})
        csrf = request(client, "GET", f"/api/{role}/auth/csrf")
        client.headers["X-CSRF-Token"] = csrf["csrf_token"]
        yield client


def populate(origin, *, sandbox=False):
    teams = []
    for username, slug, name in [("qa.player","tu-duy","Đội Tư Duy"),
                                  ("qa.opponent","nuoc-di","Đội Nước Đi"),
                                  ("qa.gamma","khoi-dong","Đội Khởi Động")]:
        with account_client(origin, username, "player") as client:
            team = request(client,"POST","/api/player/teams",{"slug":slug,"display_name":name})["team"]
            teams.append(team["id"])
            request(client,"POST",f"/api/player/teams/{team['id']}/activate",{})
            source = ROOT / "samples/hunter.py"
            bot = request(client,"POST","/api/player/bots",{"name":"Chiến thuật Python · "+name,
                "filename":source.name,"game_id":"robot_battle","source_base64":base64.b64encode(source.read_bytes()).decode()})["bot"]
            assert bot["status"] == "ready", bot["status"]
            request(client,"PUT","/api/player/active-bot",{"game_id":"robot_battle","bot_id":bot["id"]})
            if username == "qa.player":
                request(client,"POST",f"/api/player/teams/{team['id']}/invitations",{"username":"qa.member"})
    with account_client(origin,"qa.admin","admin") as admin:
        tournament = request(admin,"POST","/api/admin/team-tournaments",{"name":"Giải chiến thuật mùa thu",
            "game_id":"robot_battle","team_ids":teams,"format":"round_robin"})["tournament"]
        request(admin,"POST",f"/api/admin/team-tournaments/{tournament['id']}/start",{})
        request(admin,"POST","/api/admin/team-tournaments",{"name":"Cúp lập trình đội tuyển",
            "game_id":"robot_battle","team_ids":teams[:2],"format":"single_elimination"})
        now=int(time.time())
        season=request(admin,"POST","/api/admin/seasons",{"name":"Đợt đăng ký tháng 10","game_id":"robot_battle",
            "registration_opens_at":now-60,"registration_closes_at":now+86400,
            "starts_at":now+86460,"ends_at":now+172800,"max_teams":16})["season"]
        future=request(admin,"POST","/api/admin/official-matches",{"team_a_id":teams[0],"team_b_id":teams[1],
            "game_id":"robot_battle","bot_lock_at":now+3600,"scheduled_at":now+7200})["request"]
    with account_client(origin,"qa.player","player") as player:
        request(player,"POST",f"/api/player/seasons/{season['id']}/register",{})
        if not sandbox:
            return {"practice_id":None,"future_official_id":future["id"],"season_id":season["id"],
                    "tournament_id":tournament["id"],"teams":teams,"replay_frames":0,"runner":"native; async unavailable"}
        practice=request(player,"POST","/api/player/scrimmages",{"game_id":"robot_battle","opponent_team_id":teams[1]})["request"]
        deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            detail=request(player,"GET",f"/api/player/scrimmages/{practice['id']}")["request"]
            if detail["status"] in ("COMPLETED","INTERRUPTED","CANCELLED","FAILED"):
                break
            time.sleep(.3)
        assert detail["status"]=="COMPLETED", detail
        replay=request(player,"GET",f"/api/player/scrimmages/{practice['id']}/replay")
        assert replay["frames"], "Sandbox sample match must have real frames"
    return {"practice_id":practice["id"],"future_official_id":future["id"],"season_id":season["id"],
            "tournament_id":tournament["id"],"teams":teams,"replay_frames":len(replay["frames"])}


@contextmanager
def populated_server(port=None):
    with temporary_app(port or available_port(),limits=RateLimits(request_source=10000,session_token=5000)) as (application,origin):
        # Only this helper's disposable runtime is seeded, never workspace data.
        server=uvicorn.Server(uvicorn.Config(application,host="127.0.0.1",port=int(origin.rsplit(':',1)[1]),log_level="error",timeout_graceful_shutdown=2))
        thread=threading.Thread(target=server.run,daemon=True)
        thread.start()
        try:
            wait_ready(origin)
            runtime=application.state.account_http
            def seed_running(auth,db):
                principal=auth.login("qa.admin",PASSWORD,audience="ADMIN",source_key="review-seed").principal
                for username,name in [("qa.opponent","Minh Anh"),("qa.gamma","Tuấn Minh"),("qa.member","Linh Nguyễn"),("qa.new","Người chơi mới")]:
                    grant=auth.issue_invitation(principal,username,name=name)
                    auth.activate(grant.token,PASSWORD)
            import asyncio
            # Runtime.run owns the actual writer/transaction protocol.
            asyncio.run(runtime.run(seed_running))
            fixture=populate(origin)
            yield origin,fixture
        finally:
            server.should_exit=True
            thread.join(timeout=20)
            if thread.is_alive(): raise RuntimeError("Disposable workspace review did not stop")


@contextmanager
def docker_server(port):
    from scripts.check_docker import DockerCheck
    qa=DockerCheck()
    qa.env.update(ARENA_PORT=str(port),ARENA_ACCOUNT_AUTH="1",ARENA_ACCOUNT_ONLY="1",
        ARENA_AUTH_ALLOW_HTTP="1",ARENA_SELF_REGISTRATION="1",ARENA_PUBLIC_USERNAME_SIGNUP="0",
        ARENA_EMAIL_VERIFICATION="0",ARENA_ADMIN_TOTP_REQUIRED="0",ARENA_ALLOWED_HOSTS="127.0.0.1",
        QA_PASSWORD=PASSWORD)
    origin=f"http://127.0.0.1:{port}"
    qa.env["ARENA_AUTH_ORIGINS"]=origin
    qa.images={"arena":"neon-retro-workspace-qa-arena:local","controller":"neon-retro-workspace-qa-controller:local",
               "bot-image":"neon-arena-qa-bot-image:local"}
    override={"services":{
        "arena":{"image":qa.images["arena"],"volumes":[{"type":"bind","source":str(ROOT/"frontend"),"target":"/app/frontend","read_only":True}]},
        "controller":{"image":qa.images["controller"],"environment":{"SANDBOX_IMAGE":qa.images["bot-image"]}},
        "bot-image":{"image":qa.images["bot-image"]}}}
    qa.override.write_text(json.dumps(override),encoding="utf-8")
    seed_code='''import os
from pathlib import Path
from backend.admin_cli import bootstrap_admin
from backend.account_database import AccountDatabase
from backend.auth_service import AuthService
from backend.auth_limits import AuthRateLimiter
from backend.writer_lock import WriterLock
data=Path('/app/data'); password=os.environ['QA_PASSWORD']
bootstrap_admin(data,'qa.admin',password,'QA Admin')
with WriterLock(data) as writer, AccountDatabase(data).writer_connection(writer) as connection:
    auth=AuthService(connection,writer,login_limiter=AuthRateLimiter())
    admin=auth.login('qa.admin',password,audience='ADMIN',source_key='ui-seed').principal
    for username,name in [('qa.player','Captain Tu Duy'),('qa.opponent','Minh Anh'),('qa.gamma','Tuan Minh'),('qa.member','Linh Nguyen'),('qa.new','New Player')]:
        grant=auth.issue_invitation(admin,username,name=name); auth.activate(grant.token,password)
'''
    try:
        qa.compose("build","arena","controller",capture=False)
        qa.compose("run","--rm","--no-deps","-e","QA_PASSWORD","--entrypoint","python","arena","-c",seed_code)
        qa.up()
        wait_ready(origin)
        fixture=populate(origin,sandbox=True)
        fixture["project"]=qa.project
        fixture["runner"]="sandbox"
        yield origin,fixture
    finally:
        qa.cleanup()


def capture(origin=None):
    """Measure real rendered pages. Optional existing sandbox gets replay QA only."""
    from playwright.sync_api import expect, sync_playwright

    def review(url, fixture, *, replay_only=False):
        errors, measurements = [], []

        def measure(page, role, view, *, document=False):
            for width in (320,360,390,768,1024,1440):
                page.set_viewport_size({"width":width,"height":1000 if width>=768 else 844})
                page.wait_for_timeout(80)
                result = page.evaluate("""documentPage => ({
                    overflow:document.documentElement.scrollWidth>innerWidth,
                    heading:getComputedStyle(document.querySelector(documentPage ? 'h1' : '.view.active h1')).fontFamily,
                    duplicateIds:document.querySelectorAll('[id]').length-new Set([...document.querySelectorAll('[id]')].map(n=>n.id)).size
                })""", document)
                assert not result["overflow"], (role,view,width,"page overflow")
                assert not result["duplicateIds"], (role,view,"duplicate IDs")
                assert "Handjet" in result["heading"], (role,view,"display font")
                if not document:
                    expect(page.locator("#competition-status")).to_be_hidden()
                if role == "admin" and view == "administration":
                    region = page.locator(".data-table-wrap")
                    hint = page.locator("#admin-accounts-scroll-hint")
                    overflow = region.evaluate("node => node.scrollWidth > node.clientWidth + 1")
                    if overflow:
                        expect(hint).to_be_visible()
                        expect(region).to_have_attribute("aria-describedby","admin-accounts-scroll-hint")
                        region.focus()
                        region.press("ArrowRight")
                        page.wait_for_function("document.querySelector('.data-table-wrap').scrollLeft > 0")
                        # Preserve all five columns and reach the real actions.
                        assert region.locator("th").count() == 5
                        action = region.get_by_role("button",name="Khôi phục mật khẩu").first
                        action.focus()
                        expect(action).to_be_focused()
                        assert region.evaluate("node => node.scrollLeft > 0")
                        region.evaluate("node => { node.scrollLeft = 0; }")
                    else:
                        expect(hint).to_be_hidden()
                        assert region.get_attribute("aria-describedby") is None
                if view == "replay":
                    for side in ("a","b"):
                        identity = page.locator(f".fighter-{side}")
                        expect(identity.locator("small")).to_have_text("PLAYER "+side.upper())
                        expect(page.locator(f"#fighter-{side}-name")).not_to_be_empty()
                        expect(page.locator(f"#fighter-{side}-bot")).to_contain_text("Python ·")
                        expect(page.locator(f"#hp-{side}-text")).to_contain_text("HP")
                        assert identity.evaluate("node => [...node.querySelectorAll('strong,.fighter-bot,.hp-text')].every(text => text.scrollWidth <= text.clientWidth + 1)")
                    if width <= 600:
                        a = page.locator(".fighter-a").bounding_box()
                        b = page.locator(".fighter-b").bounding_box()
                        assert b["y"] >= a["y"]+a["height"], (width,"stacked competitors")
                measurements.append({"role":role,"view":view,"width":width,**result})
                if width in (390,1440):
                    page.evaluate("window.scrollTo({top:0,behavior:'instant'})")
                    page.screenshot(path=str(EVIDENCE/f"{role}-{view}-{width}.png"),full_page=True,animations="disabled")

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            try:
                roles = [("player", "qa.player")] if replay_only else [
                    ("player", "qa.player"), ("admin", "qa.admin"),
                    ("new-player", "qa.new"), ("invited-member", "qa.member")]
                for role, username in roles:
                    context = browser.new_context(viewport={"width":1440,"height":1000}, locale="vi-VN")
                    page = context.new_page()
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(url)
                    page.click("#landing-login")
                    page.fill("#account-username", username)
                    page.fill("#account-login-form [name=password]", PASSWORD)
                    page.click("#account-login-form [type=submit]")
                    page.wait_for_function("app.initialized && !app.initializing")
                    page.evaluate("document.fonts.ready")
                    if replay_only:
                        # Use the actual history button to preserve the supported routing contract.
                        page.evaluate("location.hash = 'scrimmage'")
                        expect(page.locator("#view-scrimmage")).to_be_visible()
                        page.locator(f"#scrimmage-list [data-focus-key='{fixture['practice_id']}-watch']").click()
                        expect(page.locator("#view-replay")).to_be_visible()
                        expect(page.locator("#timeline")).to_be_enabled()
                        page.wait_for_function("app.frames.length > 1")
                        page.click("#play-reset")
                        page.wait_for_function("app.paused && app.cursor === 0")
                        page.locator("#timeline").focus()
                        page.keyboard.press("ArrowRight")
                        page.wait_for_function("app.paused && app.cursor === 1")
                        page.select_option("#play-speed","2")
                        page.wait_for_function("app.speed === 2")
                        page.click("#play-start")
                        page.wait_for_function("!app.paused && app.cursor > 1")
                        page.click("#play-pause")
                        page.wait_for_function("app.paused")
                        with page.expect_download() as downloaded:
                            page.click("#download-replay")
                        replay = json.loads(Path(downloaded.value.path()).read_text(encoding="utf-8"))
                        assert len(replay["frames"]) == fixture["replay_frames"]
                        page.click("#play-reset")
                        views = ["replay"]
                    elif role in ("new-player", "invited-member"):
                        views = ["home", "upload", "profile"]
                    else:
                        views = ["home", "upload", "tournaments", "seasons", "official", "scrimmage", "standings", "watch", "profile"]
                        if role == "admin": views = [v for v in views if v != "upload"] + ["administration", "system"]
                    for view in views:
                        if view != "replay":
                            page.evaluate("view => { location.hash = view; }", view)
                            expect(page.locator(f"#view-{view}")).to_be_visible()
                        measure(page,role,view)
                        if view == "tournaments":
                            page.locator(".team-tournament-details > summary").first.click()
                            if role == "admin": page.locator("#team-tournament-admin-panel > summary").click()
                            measure(page,role,"tournaments-expanded")
                        if role == "admin" and view in ("seasons","official","system"):
                            selector = {"seasons":"#season-admin-panel", "official":"#official-admin-panel", "system":".system-advanced"}[view]
                            page.locator(selector+" > summary").click()
                            measure(page,role,view+"-expanded")
                        if role == "admin" and view == "administration":
                            for pane in ("teams","bots"):
                                page.click("#admin-tab-"+pane)
                                expect(page.locator("#admin-pane-"+pane)).to_be_visible()
                                measure(page,role,"administration-"+pane)
                    # Navigation is exercised through the real mobile drawer.
                    page.set_viewport_size({"width":390,"height":844})
                    page.click("#nav-toggle")
                    page.locator('.sidebar [data-view="home"]').click()
                    expect(page.locator("#view-home")).to_be_visible()
                    page.emulate_media(reduced_motion="reduce")
                    assert page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
                    assert page.locator("#view-home").evaluate("node => getComputedStyle(node).animationName === 'none'")
                    if role == "player" and not replay_only:
                        # Real network loss; the received state must stay readable.
                        context.set_offline(True)
                        expect(page.locator("#network-notice")).to_be_visible(timeout=20000)
                        expect(page.locator("#view-home h1")).to_be_visible()
                        page.screenshot(path=str(EVIDENCE/"player-offline-390.png"),full_page=True,animations="disabled")
                        context.set_offline(False)
                        expect(page.locator("#network-notice")).to_be_hidden(timeout=20000)
                    # Revoke this disposable session and wake socket watchers.
                    page.evaluate("async () => { await accountLogout(); }")
                    expect(page.locator("#account-landing")).to_be_visible()
                    if replay_only:
                        expect(page.locator("#fighter-a-bot")).to_be_empty()
                        expect(page.locator("#fighter-b-bot")).to_be_empty()
                    context.close()
                if not replay_only:
                    with browser.new_context(locale="vi-VN") as context:
                        page = context.new_page()
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        missing = []
                        page.on("response", lambda response: missing.append(response.url) if response.status == 404 else None)
                        for name,path in (("protocol","/static/protocol.html"),("lan","/lan"),("results","/results")):
                            response = page.goto(url+path)
                            assert response.status == 200, (path,response.status)
                            page.evaluate("document.fonts.ready")
                            measure(page,"public",name,document=True)
                        assert not missing, missing
                assert not errors, errors
            finally:
                browser.close()
        report = {"measurements":measurements,"page_errors":errors,"runner":fixture.get("runner"),"replay_frames":fixture.get("replay_frames",0)}
        suffix = "replay" if replay_only else "layout"
        (EVIDENCE/f"{suffix}-report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        print(f"PASS {suffix}: {len(measurements)} role/view/viewport checks",flush=True)

    if origin:
        from urllib.parse import urlparse
        parsed = urlparse(origin)
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1":
            raise ValueError("Review only accepts a disposable 127.0.0.1 HTTP server")
        fixture = json.loads((EVIDENCE/"fixture-summary.json").read_text(encoding="utf-8"))
        review(origin,fixture,replay_only=True)
    else:
        with populated_server() as (url,fixture):
            review(url,fixture)


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve",action="store_true")
    parser.add_argument("--capture",action="store_true")
    parser.add_argument("--port",type=int,default=8880)
    parser.add_argument("--docker",action="store_true",help="Use isolated real Docker Sandbox, never operational volumes")
    parser.add_argument("--url",help="Capture saved replay from an already running disposable localhost sandbox")
    args=parser.parse_args()
    EVIDENCE.mkdir(parents=True,exist_ok=True)
    if args.serve:
        factory=docker_server if args.docker else populated_server
        with factory(args.port) as (origin,fixture):
            (EVIDENCE/"fixture-summary.json").write_text(json.dumps(fixture,indent=2),encoding="utf-8")
            print(f"READY disposable populated review: {origin}",flush=True)
            stop=EVIDENCE/"stop-review"
            if stop.exists():stop.unlink()
            try:
                while not stop.exists(): time.sleep(1)
            except KeyboardInterrupt: pass
    elif args.capture:
        capture(args.url)
