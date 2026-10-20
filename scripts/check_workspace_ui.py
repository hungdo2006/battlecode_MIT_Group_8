"""Populated desktop/mobile QA using check_battlecode_platform.py --serve's fixture.

Reads disposable credentials locally; report and screenshots never include them.
"""
import argparse
import json
import time
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SIZES = ((1440, 960), (1366, 768), (768, 1024), (390, 844), (360, 800))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, default=ROOT / 'design-research/battlecode26-engine/browser-session.json')
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text(encoding='utf-8'))
    origin = fixture['origin']
    assert urlsplit(origin).hostname == '127.0.0.1', 'Use only the isolated local QA deployment'
    output = ROOT / 'design-research/battlecode26-engine/workspace-ui'
    output.mkdir(parents=True, exist_ok=True)
    errors, checks, rate_limits = [], [], []

    def layout(page, label):
        state = page.evaluate("""() => ({width:innerWidth, scroll:document.documentElement.scrollWidth,
            duplicateIds:[...document.querySelectorAll('[id]')].map(n=>n.id).filter((id,i,ids)=>ids.indexOf(id)!==i),
            inputs:[...document.querySelectorAll('input:not([type=checkbox]):not([type=range]):not([type=file]),select')]
              .filter(n=>n.getClientRects().length).map(n=>parseFloat(getComputedStyle(n).fontSize))})""")
        assert state['scroll'] <= state['width'], (label, state)
        assert not state['duplicateIds'], (label, state)
        if state['width'] < 768:
            assert all(size >= 16 for size in state['inputs']), (label, state)
        checks.append({'view': label, 'width': state['width'], 'overflow': False})

    def navigate(page, view):
        if page.viewport_size['width'] < 1024:
            page.locator('#nav-toggle').click()
        page.locator(f'.nav-item[data-view={view}]').click()
        page.locator('#view-' + view).wait_for(state='visible')
        assert not page.locator('.shell').evaluate('n=>n.inert')

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel='chrome', headless=True)
        for role, username in (('player', 'qa.alpha'), ('admin', 'qa.admin')):
            context = browser.new_context(viewport={'width':1440, 'height':960})
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('response', lambda response: rate_limits.append(response.url) if response.status == 429 else None)
            page.goto(origin)
            page.wait_for_function("!document.querySelector('#landing-login').disabled")
            if role == 'player':
                for width, height in SIZES:
                    page.set_viewport_size({'width':width, 'height':height})
                    page.evaluate('document.fonts.ready')
                    layout(page, 'landing')
                page.emulate_media(reduced_motion='reduce')
                assert page.locator('#account-landing h1').evaluate("n=>getComputedStyle(n).animationName") == 'none'
                page.emulate_media(reduced_motion='no-preference')
            page.set_viewport_size({'width':1440, 'height':960})
            page.locator('#landing-login').click()
            page.locator('#account-username').fill(username)
            page.locator('#account-login-form [name=password]').fill(fixture['password'])
            page.locator('#account-login-form [type=submit]').click()
            page.wait_for_function('app.initialized && !app.initializing')
            page.wait_for_function('app.scrimmages.length >= 3 && app.teamTournaments.length > 0')
            views = ['home','standings','tournaments','official','scrimmage','watch','seasons','profile','rules']
            views.insert(1, 'upload')
            if role == 'admin':
                views.remove('upload')
                views += ['administration', 'system']
            for view in views:
                page.set_viewport_size({'width':1440, 'height':960})
                navigate(page, view)
                if view == 'standings':
                    page.wait_for_function("document.querySelector('#standings-body').textContent.includes('QA Round Robin')")
                    assert 'qa.beta' in page.locator('#standings-body').inner_text()
                for width, height in SIZES:
                    page.set_viewport_size({'width':width, 'height':height})
                    # Let real responses settle before measuring populated rows.
                    page.wait_for_timeout(150)
                    layout(page, role + '-' + view)
                    if width in (1440,390) and view in ('upload','seasons','scrimmage','administration','system','official','tournaments'):
                        page.screenshot(path=str(output/f'{role}-{view}-{width}.png'), full_page=True, animations='disabled')
            navigate(page, 'profile')
            page.locator('#profile-display-name').fill('QA Profile ' + role)
            page.locator('#profile-form [type=submit]').click()
            page.wait_for_function("document.querySelector('#profile-feedback').textContent.includes('Đã')")
            if role == 'player':
                for kind, request_id in (('scrimmage',fixture['request_id']),('official',fixture['official_id'])):
                    page.goto(origin + '/?' + kind + '=' + request_id + '#home')
                    try:
                        page.wait_for_function("app.initialized && app.match?.game_id === 'battlecode26' && app.frames.length >= 4")
                    except Exception:
                        print('Replay review state:', kind, page.evaluate("({initialized:app.initialized,frames:app.frames.length,game:app.match?.game_id,pollPaused:Date.now()<app.pollPauseUntil})"), 'rate limits:', rate_limits)
                        raise
                    if page.locator('#victory-overlay').is_visible():
                        page.locator('#dismiss-victory').click()
                    for width,height in ((1440,960),(390,844),(360,800)):
                        page.set_viewport_size({'width':width,'height':height})
                        layout(page, kind + '-replay')
                    with page.expect_download() as download:
                        page.locator('#download-replay').click()
                    saved = output / (kind + '-replay.json')
                    download.value.save_as(str(saved))
                    assert json.loads(saved.read_text(encoding='utf-8'))['frames']
                    assert kind + '=' + request_id in page.url
            else:
                page.set_viewport_size({'width':1440,'height':960})
                navigate(page,'administration')
                page.locator('#admin-account-query').fill('qa.outsider')
                page.locator('#admin-account-search [type=submit]').click()
                page.wait_for_function("document.querySelectorAll('#admin-accounts-body tr').length === 1 && document.querySelector('#admin-accounts-body').textContent.includes('qa.outsider')")
                assert 'ADMIN' not in page.locator('#admin-accounts-body').inner_text()
                navigate(page,'system')
                page.wait_for_function("document.querySelector('#system-status').textContent.includes('sandbox')")
            context.close()
        browser.close()
    assert not errors, errors
    assert not rate_limits, rate_limits
    report = {'status':'PASS','layout_checks':len(checks),'checks':checks,'javascript_errors':errors,
              'rate_limits':rate_limits,'profile_forms':True,'scoped_replay_downloads':True,'admin_search':True}
    (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('PASS populated UI:', len(checks), 'layout checks; profiles, scoped replay downloads, Admin search; no JS errors or rate limits')


if __name__ == '__main__':
    main()
