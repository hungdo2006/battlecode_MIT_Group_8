"""Phase 3 browser QA against a disposable real Docker sandbox stack.

No mocked API payloads or invented game states. One upload is deliberately delayed
in transport to verify busy state across polling; its real server response is used.
"""
import argparse
import json
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from check_docker import DockerCheck
from check_multiplayer_ui import check as multiplayer_check

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / 'docs/screenshots/liquid-light'
WAIT = b"import sys,json\nfor line in sys.stdin: print(json.dumps({'type':'wait'}),flush=True)\n"


def no_overflow(page):
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), page.url


def save(page, filename):
    page.evaluate('window.scrollTo({top:0,behavior:"instant"})')
    page.locator('#toast').evaluate("node => node.classList.add('hidden')")
    page.screenshot(path=str(OUTPUT / filename), full_page=True, animations='disabled')


def initialize(page, url, name):
    page.goto(url)
    page.wait_for_function('app.initialized && app.lobby')
    page.locator('#session-name').fill(name)
    page.locator('#session-form button').click()
    page.wait_for_function('name => app.participant.name === name', arg=name)


def organize(page, code):
    page.locator('#organizer-toggle').click()
    page.locator('#organizer-code').fill(code)
    page.locator('#organizer-form [type=submit]').click()
    page.wait_for_function('app.role === "organizer"')


def confirm(page, accept=True):
    page.locator('#confirm-dialog').wait_for(state='visible')
    page.locator('#confirm-accept' if accept else '#confirm-cancel').click()
    page.locator('#confirm-dialog').wait_for(state='hidden')


def select_game(page, game):
    page.locator('.nav-item[data-view=rules]').click()
    page.locator('#workspace-game-select').select_option(game)
    page.wait_for_function('game => app.selectedGameId === game && !app.switchingGame', arg=game)


def set_rules(page, **rules):
    for key, value in rules.items():
        page.locator(f'#rules-fields [name={key}]').fill(str(value))
    assert page.locator('#competition-open').is_disabled(), 'Unsaved rules must be explicit'
    page.locator('#rules-form [type=submit]').click()
    page.wait_for_function('!app.rulesBusy && !app.rulesDirty')


def extra_checks(url, code):
    checks = []
    def passed(name):
        checks.append(name)
        print('PASS', name, flush=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='chrome', headless=True)
        contexts = [browser.new_context(viewport={'width':1440, 'height':1000}, accept_downloads=True) for _ in range(3)]
        org, a, b = [context.new_page() for context in contexts]
        errors = []
        for page in (org, a, b):
            page.on('pageerror', lambda error: errors.append(str(error)))
        for page, name in ((org, 'Organizer'), (a, 'Nova'), (b, 'Orbit')):
            initialize(page, url, name)
        assert a.request.get(url + '/api/health').json()['runner']['mode'] == 'sandbox'
        save(a, 'overview.png')
        contrast = a.evaluate("""() => {
          const luminance = color => {const c=color.match(/[\\d.]+/g).slice(0,3).map(Number).map(n=>n/255).map(n=>n<=.04045?n/12.92:((n+.055)/1.055)**2.4);return .2126*c[0]+.7152*c[1]+.0722*c[2];};
          const ratio = (a,b) => (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
          const button=getComputedStyle(document.querySelector('#view-home .button.primary'));
          const body=getComputedStyle(document.body);
          return {primary:ratio(luminance(button.color),luminance(button.backgroundColor)),body:ratio(luminance(body.color),luminance(body.backgroundColor))};
        }""")
        assert contrast['primary'] >= 4.5 and contrast['body'] >= 7, contrast
        passed('computed primary/button and body contrast')

        # Keyboard access, password clearing and focus return on the real dialog.
        a.locator('#organizer-toggle').focus()
        a.keyboard.press('Enter')
        a.locator('#organizer-code').fill('not-a-real-credential')
        a.keyboard.press('Escape')
        a.wait_for_function('!document.querySelector("#organizer-dialog").open && document.querySelector("#organizer-code").value === ""')
        assert a.locator('#organizer-code').input_value() == ''
        assert a.locator('#organizer-toggle').evaluate('node => node === document.activeElement')
        outline = a.locator('#organizer-toggle').evaluate('node => getComputedStyle(node).outlineStyle')
        assert outline != 'none'
        passed('keyboard focus, dialog Escape and password clearing')

        organize(org, code)
        if org.evaluate('app.competition.competition_locked'):
            org.locator('#competition-close').click(); confirm(org)
        org.wait_for_function('app.competition.can_edit')
        select_game(org, 'robot_battle')
        assert org.locator('#rules-fields [name=initial_hp]').is_visible()
        save(org, 'organizer-robot-rules.png')
        select_game(org, 'ott_v2')
        assert org.locator('#rules-fields [name=rounds]').is_visible()
        assert org.locator('#rules-fields [name=initial_hp]').count() == 0
        save(org, 'organizer-ott-rules.png')
        select_game(org, 'robot_battle')
        set_rules(org, max_turns=1000)
        org.locator('#competition-open').click()
        org.wait_for_function('app.competition.phase === "open"')
        assert org.locator('#rules-fields [name=max_turns]').is_disabled()
        org.locator('#competition-close').click(); confirm(org, False)
        assert org.evaluate('app.competition.phase') == 'open'
        org.locator('#competition-close').click(); confirm(org)
        org.wait_for_function('app.competition.phase === "setup"')
        passed('dynamic rules, unsaved changes, Game Lock and close confirmation')

        # Default-reset confirmation may be cancelled without changing the server.
        org.locator('#default-rules').click(); confirm(org, False)
        assert org.evaluate('app.rules.max_turns') == 1000
        passed('reset confirmation cancellation preserves real rules')

        a.locator('.nav-item[data-view=upload]').click()
        assert a.locator('#upload-game').is_disabled()
        form = a.locator('#upload-form')
        form.locator('[name=name]').fill('Invalid source')
        a.locator('#bot-file').set_input_files({'name':'invalid.txt','mimeType':'text/plain','buffer':b'hello'})
        form.locator('[type=submit]').click()
        assert a.locator('#upload-feedback').evaluate('node => node.classList.contains("error")')
        a.locator('#bot-file').set_input_files({'name':'broken.py','mimeType':'text/plain','buffer':b'def broken(:\n'})
        with a.expect_response(lambda r: r.url.endswith('/api/bots') and r.request.method == 'POST', timeout=45000) as response:
            form.locator('[type=submit]').click()
        assert response.value.json()['status'] == 'error'
        a.locator('#compiler-log').wait_for(state='visible')
        assert 'SyntaxError' in a.locator('#compiler-log').inner_text()
        save(a, 'compile-error.png')
        passed('invalid file validation and genuine sandbox compiler diagnostics')

        # Drop a real File, then delay transport rather than fabricating compilation.
        transfer = a.evaluate_handle("""source => { const d = new DataTransfer(); d.items.add(new File([source], 'atlas.py', {type:'text/plain'})); return d; }""", WAIT.decode())
        a.locator('#drop-zone').dispatch_event('drop', {'dataTransfer':transfer})
        assert a.locator('#file-label').inner_text() == 'atlas.py'
        assert 'Python' in a.locator('#file-language').inner_text()
        form.locator('[name=name]').fill('Atlas')
        requests = []
        def delay_upload(route):
            if route.request.method == 'POST':
                requests.append(route.request.url)
                time.sleep(3)
            route.continue_()
        a.route('**/api/bots', delay_upload)
        with a.expect_response(lambda r: r.url.endswith('/api/bots') and r.request.method == 'POST', timeout=45000) as response:
            a.evaluate("""() => { const form=document.querySelector('#upload-form'); form.requestSubmit(); setTimeout(() => {window.busySurvivedPolling=document.querySelector('#upload-form [type=submit]').disabled; form.requestSubmit();},2300); }""")
        bot_a = response.value.json()
        assert bot_a['status'] == 'ready', bot_a
        a.wait_for_function('!app.uploading')
        a.unroute('**/api/bots', delay_upload)
        assert len(requests) == 1 and a.evaluate('window.busySurvivedPolling')
        a.locator(f'.bot-row[data-bot-id="{bot_a["id"]}"] [data-action=set-active]').click()
        a.wait_for_function('id => app.lobby.me.active_bot_id === id', arg=bot_a['id'])
        save(a, 'submission.png')
        passed('drag-and-drop, real compile and no duplicate submit across polling')

        error_details = a.locator('.bot-row').filter(has_text='broken.py').locator('details')
        error_details.locator('summary').click()
        a.wait_for_timeout(2300)
        assert error_details.evaluate('node => node.open'), 'Polling collapsed diagnostics'
        passed('compiler diagnostics remain expanded during polling')

        response = b.request.post(url + '/api/bots', multipart={'game_id':'robot_battle', 'name':'Orbit Bot', 'file':{'name':'orbit.py','mimeType':'text/plain','buffer':WAIT}})
        assert response.status == 201
        bot_b = response.json(); assert bot_b['status'] == 'ready'
        assert b.request.put(url + '/api/players/active-bot', data={'bot_id':bot_b['id']}).status == 200
        org.locator('#competition-open').click()
        org.wait_for_function('app.competition.phase === "open"')
        org.locator('.nav-item[data-view=create]').click()
        ids = [page.evaluate('app.participant.id') for page in (a,b)]
        def invite():
            org.wait_for_function('ids => ids.every(id => app.lobby.players.some(p => p.player_id === id && p.status === "READY"))', arg=ids)
            org.locator('#create-match [name=player_a_id]').select_option(ids[0])
            org.locator('#create-match [name=player_b_id]').select_option(ids[1])
            org.locator('#create-match [type=submit]').click()
            for page in (a,b): page.locator('#invitation-dialog').wait_for(state='visible')
        invite()
        b.locator('#invitation-decline').click()
        for page in (a,b): page.locator('#invitation-dialog').wait_for(state='hidden')
        org.wait_for_function('app.lobby.invitations.some(i => i.status === "DECLINED")')
        passed('real invitation Decline synchronizes across clients')
        invite()
        for page in (a,b): page.locator('#invitation-accept').click()
        org.wait_for_function('["running", "queued"].includes(app.match?.status) && app.frames.length > 1')
        org.locator('#competition-close').click(); confirm(org)
        org.wait_for_function('app.competition.phase === "draining"')
        assert 'DRAINING' in org.locator('#competition-status').inner_text()
        assert org.locator('#workspace-game-select').is_disabled()
        save(org, 'competition-draining.png')
        mid = org.evaluate('app.match.id')
        assert org.request.post(url + f'/api/matches/{mid}/cancel').status == 200
        org.wait_for_function('app.competition.phase === "setup"')
        passed('real running match, DRAINING and configuration remains read-only')

        matches = a.request.get(url + '/api/matches').json()
        for game in ('robot_battle','ott_v2'):
            match = next(m for m in matches if m['game_id'] == game and m['status'] == 'completed')
            a.evaluate('id => loadMatch(id)', match['id'])
            a.locator('#play-pause').click()
            a.locator('#timeline').evaluate("node => { node.value=Math.floor(Number(node.max)/2);node.dispatchEvent(new Event('input',{bubbles:true})); }")
            assert a.evaluate('app.paused && app.cursor > 0')
            assert a.evaluate('frameGameId(currentFrame())') == game
            a.locator('#play-speed').select_option('2')
            assert a.evaluate('app.speed') == 2
            a.wait_for_timeout(80)
            pixel = a.locator('#arena').evaluate('node => [...node.getContext("2d").getImageData(2,2,1,1).data]')
            assert all(channel > 200 for channel in pixel[:3]), pixel
            save(a, f'arena-{game}.png')
            with a.expect_download() as download:
                a.locator('#download-replay').click()
            saved = json.loads(Path(download.value.path()).read_text())
            assert saved['match']['id'] == match['id'] and saved['frames']
            a.locator('#play-reset').click()
            assert a.evaluate('app.cursor === 0 && app.paused')
        passed('both light Canvas renderers, seek/reset/speed and genuine replay download')

        before = a.evaluate('app.frames.length')
        contexts[1].set_offline(True)
        a.evaluate('app.competitionSocket.close(); app.socket?.close()')
        a.locator('#network-notice').wait_for(state='visible')
        assert a.evaluate('app.frames.length') == before
        contexts[1].set_offline(False)
        a.wait_for_function('app.lobbyOnline && app.serverOnline')
        passed('offline/reconnect feedback preserves replay frames')

        a.emulate_media(reduced_motion='reduce')
        a.wait_for_function('reducedMotion === true')
        assert a.locator('.view.active').evaluate('node => getComputedStyle(node).animationName') == 'none'
        a.emulate_media(reduced_motion='no-preference')
        passed('prefers-reduced-motion in CSS and Canvas')

        # Actual layouts at common laptop/tablet/phone widths, every route.
        for width,height in ((1920,1080),(1440,1000),(1366,768),(1024,768),(768,1024),(390,844),(320,740)):
            a.set_viewport_size({'width':width,'height':height})
            for view in ('home','upload','create','watch','rules'):
                a.locator(f'.nav-item[data-view={view}]').click()
                no_overflow(a)
            if width == 390: save(a, 'mobile-rules.png')
        a.set_viewport_size({'width':1440,'height':1000})
        a.locator('.nav-item[data-view=watch]').click(); save(a, 'history.png')
        a.goto(url + '/lan'); no_overflow(a)
        a.goto(url + '/static/protocol.html'); no_overflow(a)
        passed('35 responsive route checks and matching LAN/protocol pages')
        assert not errors, errors
        browser.close()
    return {'checks':checks,'javascript_errors':errors,'screenshots':str(OUTPUT)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-build', action='store_true', help='Use images already built from current source')
    args = parser.parse_args()
    qa = DockerCheck()
    print('Liquid Light QA project:', qa.project, flush=True)
    try:
        if not args.no_build: qa.compose('build', capture=False)
        qa.up(); qa.inspect()
        multiplayer_check(qa.url, qa.code, output_dir=OUTPUT)
        result = extra_checks(qa.url, qa.code)
        print(json.dumps(result, ensure_ascii=True, indent=2))
    finally:
        qa.cleanup()
        print('Dedicated QA resources removed; application data untouched.', flush=True)


if __name__ == '__main__':
    main()
