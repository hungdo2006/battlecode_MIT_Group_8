"""Six real cross-language matches over LAN HTTP/WS on isolated QA data."""
import argparse
import asyncio
import json
import os
import secrets
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import uvicorn
from backend.main import create_app
from backend.network import lan_addresses
from check_lan import check
from demo_match import demo


def main(args):
    previous = os.environ.get('ARENA_ADMIN_CODE')
    os.environ['ARENA_ADMIN_CODE'] = secrets.token_urlsafe(24)
    try:
        with tempfile.TemporaryDirectory(prefix='neon-v3-network-') as base:
            app = create_app(Path(base), tick_seconds=0.03)
            server = uvicorn.Server(uvicorn.Config(app, host='0.0.0.0', port=0, log_level='error'))
            thread = threading.Thread(target=server.run, daemon=True)
            thread.start()
            try:
                deadline = time.monotonic() + 15
                while not server.started:
                    if time.monotonic() > deadline or not thread.is_alive(): raise RuntimeError('QA server not ready')
                    time.sleep(0.05)
                port = server.servers[0].sockets[0].getsockname()[1]
                addresses = lan_addresses()
                host = args.lan_ip or (addresses[0] if addresses else '127.0.0.1')
                url = f'http://{host}:{port}'
                for game in ('robot_battle', 'ott_v2'):
                    for a, b in (('python', 'cpp'), ('cpp', 'java'), ('python', 'java')):
                        asyncio.run(demo(SimpleNamespace(url=url, game=game, a=a, b=b,
                                                        open_competition=True, max_turns=100,
                                                        rounds=2 if game == 'ott_v2' else None)))
                asyncio.run(check(SimpleNamespace(url=url, game='ott_v2', language_b='java',
                                                 max_turns=100, open_competition=True)))
                records = app.state.manager.get_matches()
                assert len(records) == 7 and all(m['status'] == 'completed' for m in records)
                assert all(m['result']['reason'] != 'bot_error' for m in records)
                print(json.dumps({'url': url, 'matches': [{'id': m['id'], 'game': m['game_id'],
                    'languages': [m['bot_a_language'], m['bot_b_language']], 'result': m['result']} for m in records]}, indent=2))
            finally:
                server.should_exit = True
                thread.join(timeout=15)
                assert not thread.is_alive(), 'Owned QA server did not stop'
    finally:
        if previous is None: os.environ.pop('ARENA_ADMIN_CODE', None)
        else: os.environ['ARENA_ADMIN_CODE'] = previous


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lan-ip')
    main(parser.parse_args())
