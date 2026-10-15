"""Real Chrome, three cookie jars, real LAN HTTP/WS, no API mocks.

Without --url this owns an isolated test server/data directory and stops it.
With --url use a dedicated QA server with ARENA_ADMIN_CODE; this submits bots.
"""
import argparse
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend.network import lan_addresses


def check(url, code, games=('robot_battle', 'ott_v2'), output_dir=None):
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        contexts = [browser.new_context(viewport={'width': 1440, 'height': 1000}) for _ in range(3)]
        pages = [c.new_page() for c in contexts]
        errors, ws_urls = [], [[], [], []]
        output = Path(output_dir) if output_dir else ROOT / 'docs/screenshots/multiplayer'
        output.mkdir(parents=True, exist_ok=True)
        for index, page in enumerate(pages):
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('websocket', lambda ws, i=index: ws_urls[i].append(ws.url))
            page.goto(url)
            page.wait_for_function('app.participant && app.lobby')
            page.locator('#session-name').fill(['Organizer', 'Hoang', 'Minh'][index])
            page.locator('#session-form button').click()
            page.wait_for_function('name => app.participant.name === name', arg=['Organizer', 'Hoang', 'Minh'][index])
        org, a, b = pages
        org.locator('#organizer-toggle').click()
        org.locator('#organizer-code').fill(code)
        org.locator('#organizer-form [type=submit]').click()
        org.wait_for_function('app.role === "organizer"')
        assert org.locator('.nav-item[data-view=upload]').is_hidden()
        assert org.request.post(url + '/api/samples/python/submit').status == 403
        assert a.request.post(url + '/api/matches', data={'bot_a': 'x', 'bot_b': 'y'}).status == 403
        assert a.request.post(url + '/api/invitations', data={'player_a_id': 'x', 'player_b_id': 'y'}).status == 403
        ids = [page.evaluate('app.participant.id') for page in (a, b)]
        assert len(set(ids)) == 2
        assert len({context.cookies()[0]['value'] for context in contexts}) == 3
        records = []
        baseline_count = len(org.request.get(url + '/api/matches').json())

        def setup(game):
            if org.evaluate('app.competition.competition_locked'):
                org.locator('#competition-close').click()
            org.wait_for_function('app.competition.can_edit')
            org.locator('.nav-item[data-view=rules]').click()
            org.locator('#workspace-game-select').select_option(game)
            org.wait_for_function('game => app.selectedGameId === game && !app.switchingGame', arg=game)
            for page in (a, b):
                page.wait_for_function('game => app.selectedGameId === game', arg=game)
                assert page.locator('#workspace-game-select').is_disabled()
            assert org.locator('#rules-fields [name=max_turns]').is_enabled()
            if game == 'robot_battle':
                org.locator('#rules-fields [name=map_size]').fill('12')
                org.locator('#rules-fields [name=initial_hp]').fill('100')
                org.locator('#rules-fields [name=damage]').fill('20')
            else:
                org.locator('#rules-fields [name=rounds]').fill('2')
            org.locator('#rules-fields [name=max_turns]').fill('100')
            org.locator('#rules-form [type=submit]').click()
            org.wait_for_function('app.rules.max_turns === 100')
            org.locator('#competition-open').click()
            for page in pages:
                page.wait_for_function('app.competition.competition_locked')
            assert org.locator('#rules-fields [name=max_turns]').is_disabled()

        def submit(page, language, game):
            page.locator('.nav-item[data-view=upload]').click()
            source = (ROOT / ('samples/ott_v2/runner.' + language if game == 'ott_v2' and language != 'java'
                              else 'samples/ott_v2/Main.java' if game == 'ott_v2'
                              else 'samples/hunter.' + language if language != 'java' else 'samples/Main.java'))
            page.locator('#upload-form [name=name]').fill('Alpha Bot' if page == a else 'Smart Bot')
            page.locator('#bot-file').set_input_files(str(source))
            with page.expect_response(lambda r: r.url.endswith('/api/bots') and r.request.method == 'POST', timeout=45000) as uploaded:
                page.locator('#upload-form [type=submit]').click()
            bot = uploaded.value.json()
            assert bot['status'] == 'ready', bot.get('logs')
            row = page.locator('.bot-row').filter(has_text=bot['name']).filter(has_text=bot['filename'])
            # A later submission with the same label remains a distinct immutable row.
            row.first.get_by_role('button', name='SET AS ACTIVE BOT', exact=True).click()
            page.wait_for_function('id => app.lobby.me.active_bot_id === id', arg=bot['id'])
            return bot

        for game in games:
            setup(game)
            ba, bb = submit(a, 'cpp', game), submit(b, 'py', game)
            for page in (a, b):
                page.wait_for_function('app.lobby.me.status === "READY"')
            org.locator('.nav-item[data-view=create]').click()
            org.wait_for_function('app.lobby.players.filter(p => p.status === "READY").length === 2')
            form = org.locator('#create-match')
            form.locator('[name=player_a_id]').select_option(ids[0])
            form.locator('[name=player_b_id]').select_option(ids[1])
            form.locator('[type=submit]').click()
            for page in (a, b):
                page.locator('#invitation-dialog').wait_for(state='visible')
                assert 'Hoang' in page.locator('#invitation-fighters').inner_text()
                assert 'Minh' in page.locator('#invitation-fighters').inner_text()
            a.screenshot(path=str(output / f'{game}-invitation.png'), full_page=True)
            org.screenshot(path=str(output / f'{game}-organizer.png'), full_page=True)
            a.locator('#invitation-accept').click()
            a.wait_for_function('app.currentInvitation?.responses[app.participant.id] === "ACCEPTED"')
            assert a.locator('#invitation-accept').is_disabled()
            assert 'WAITING FOR OPPONENT' in a.locator('#invitation-wait').inner_text()
            before = org.request.get(url + '/api/matches').json()
            assert len(before) == baseline_count + len(records)
            b.locator('#invitation-accept').click()
            for page in pages:
                page.wait_for_function('app.match && location.hash === "#home"')
            mid = org.evaluate('app.match.id')
            for page in pages:
                page.wait_for_function('id => app.match?.id === id', arg=mid)
                assert not page.locator('#invitation-dialog').is_visible()
                assert 'Hoang / C++' in page.locator('#fighter-a-name').inner_text()
                assert 'Minh / Python' in page.locator('#fighter-b-name').inner_text()
            a.locator('#play-pause').click()
            paused_cursor = a.evaluate('app.cursor')
            assert a.evaluate('app.paused') and not b.evaluate('app.paused')
            # Reconnect B while the bots continue on the server.
            b.evaluate('app.competitionSocket.close(); app.socket?.close()')
            for page in pages:
                page.wait_for_function('app.match.status === "completed"', timeout=60000)
            replay = org.request.get(url + f'/api/matches/{mid}/replay').json()
            for page in pages:
                page.wait_for_function('n => app.frames.length === n', arg=len(replay['frames']))
                assert page.evaluate('app.frames') == replay['frames']
                assert page.evaluate('app.match.result') == replay['match']['result']
            assert a.evaluate('app.cursor') == paused_cursor
            assert replay['match']['result']['reason'] != 'bot_error'
            assert replay['match']['player_a_name_snapshot'] == 'Hoang'
            assert replay['match']['bot_a_id'] == ba['id'] and replay['match']['bot_b_id'] == bb['id']
            for page in (a, b): page.wait_for_function('app.lobby.me.status === "READY"')
            a.locator('#play-start').click()
            for page in pages:
                page.locator('#play-speed').select_option('4')
                page.locator('#victory-overlay').wait_for(state='visible', timeout=60000)
            b.screenshot(path=str(output / f'{game}-result.png'), full_page=True)
            records.append({'game': game, 'match_id': mid, 'frames': len(replay['frames']), 'result': replay['match']['result']})

        org.locator('#competition-close').click()
        org.wait_for_function('app.competition.can_edit')
        new_game = 'robot_battle' if records[-1]['game'] == 'ott_v2' else 'ott_v2'
        org.locator('#workspace-game-select').select_option(new_game)
        org.wait_for_function('game => app.selectedGameId === game', arg=new_game)
        # Older game replay retains its renderer, snapshots and names.
        for page in pages:
            page.evaluate('id => loadMatch(id)', records[-1]['match_id'])
            page.wait_for_function('game => app.match.game_id === game', arg=records[-1]['game'])
            assert page.evaluate('frameGameId(currentFrame())') == records[-1]['game']
        a.set_viewport_size({'width': 390, 'height': 844})
        a.locator('.nav-item[data-view=create]').click()
        assert a.evaluate('document.documentElement.scrollWidth <= innerWidth')
        a.screenshot(path=str(output / 'mobile-lobby.png'), full_page=True)
        assert not errors, errors
        assert all(any('/ws/matches/' in u for u in urls) for urls in ws_urls)
        print(json.dumps({'url': url, 'sessions': 3, 'matches': records, 'javascript_errors': errors,
                          'permissions': 'OK', 'pause_independent': True, 'mobile_390px': True}, ensure_ascii=False, indent=2))
        browser.close()


def main(args):
    if args.url:
        check(args.url.rstrip('/'), os.environ['ARENA_ADMIN_CODE'])
        return
    with tempfile.TemporaryDirectory(prefix='neon-v3-ui-') as base:
        code = secrets.token_urlsafe(24)
        env = {**os.environ, 'ARENA_ADMIN_CODE': code, 'PYTHONIOENCODING': 'utf-8'}
        addresses = lan_addresses()
        address = args.lan_ip or (addresses[0] if addresses else "127.0.0.1")
        url = f'http://{address}:{args.port}'
        command = [sys.executable, '-c', 'import sys; from pathlib import Path; import uvicorn; from backend.main import create_app; uvicorn.run(create_app(Path(sys.argv[1]),tick_seconds=0.12),host="0.0.0.0",port=int(sys.argv[2]),log_level="warning")', base, str(args.port)]
        proc = subprocess.Popen(command, cwd=ROOT, env=env, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            for _ in range(100):
                try:
                    with urlopen(url + '/api/health', timeout=1): break
                except OSError:
                    if proc.poll() is not None: raise RuntimeError('QA server exited')
                    time.sleep(0.1)
            else: raise RuntimeError('QA server not reachable')
            check(url, code)
        finally:
            proc.terminate(); proc.wait(timeout=15)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url')
    parser.add_argument('--port', type=int, default=8015)
    parser.add_argument('--lan-ip', help='Wi-Fi IPv4 from ipconfig for isolated QA server')
    main(parser.parse_args())
