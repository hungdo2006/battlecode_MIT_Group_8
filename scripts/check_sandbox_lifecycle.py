"""Real cancellation/restart/outage checks using disposable Compose resources."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.error import HTTPError
from urllib.request import Request
from uuid import uuid4

from check_docker import DockerCheck
from check_lan import Player, invited_match, presence


def lease_policy(qa, active_backend):
    """Probe private HTTP endpoints in the QA controller, never print tokens."""
    script = """
import base64,json,os,secrets
from urllib.error import HTTPError
from urllib.request import Request,urlopen
token=os.environ['ARENA_RUNNER_TOKEN']
def rpc(path,body=None,expected=200):
    request=Request('http://127.0.0.1:9000'+path,
                    data=json.dumps(body).encode() if body is not None else None,
                    headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    try:
        with urlopen(request,timeout=15) as response:
            assert expected==200
            return json.load(response)
    except HTTPError as exc:
        assert exc.code==expected,(path,exc.code,expected)
epoch=rpc('/health')['epoch']
owner=secrets.token_hex(16)
"""
    if active_backend:
        script += """
rpc('/owner',{'owner':owner,'epoch':epoch},409)
rpc('/heartbeat',{'owner':owner,'lease':secrets.token_hex(16)},409)
print('PASS real Controller: live owner cannot be replaced by foreign claim/heartbeat')
"""
    else:
        script += """
lease=rpc('/owner',{'owner':owner,'epoch':epoch})['lease']
assert rpc('/owner',{'owner':owner,'epoch':epoch})['lease']==lease
old={'owner':owner,'lease':lease}
rpc('/release',old)
newowner=secrets.token_hex(16)
newlease=rpc('/owner',{'owner':newowner,'epoch':epoch})['lease']
rpc('/owner',{'owner':owner,'epoch':epoch},409)
rpc('/heartbeat',old,409)
rpc('/close/stale-never-start',old,409)
rpc('/compile/stale-never-compile',{**old,'language':'py','source':base64.b64encode(b'pass').decode()},409)
rpc('/release',old,409)
rpc('/release',{'owner':newowner,'lease':newlease})
print('PASS real Controller: duplicate claim idempotent; released/stale owner fenced on all operations')
"""
    result = qa.compose('exec', '-T', 'controller', 'python', '-B', '-c', script)
    print(result.stdout.strip(), flush=True)


def upload_wait(player):
    boundary = 'arena-' + uuid4().hex
    source = b"import sys,json\nfor line in sys.stdin: print(json.dumps({'type':'wait'}),flush=True)\n"
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="game_id"\r\n\r\nrobot_battle\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="bot.py"\r\n\r\n').encode()
    body += source + f'\r\n--{boundary}--\r\n'.encode()
    request = Request(player.url + '/api/bots', data=body,
                      headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
    with player.opener.open(request, timeout=45) as response:
        bot = json.load(response)
    assert bot['status'] == 'ready', bot
    return bot


def job_ids(qa):
    result = subprocess.run(['docker', 'ps', '-aq', '--filter',
        'label=io.neonarena.sandbox=' + qa.env['SANDBOX_NAMESPACE']],
        env=qa.env, check=True, capture_output=True, text=True)
    return result.stdout.split()


async def until(check, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if await asyncio.to_thread(check):
            return
        await asyncio.sleep(.1)
    raise AssertionError('Condition did not become true before timeout')


async def lifecycle(qa, org, a, b, bots):
    async with presence(org), presence(a), presence(b):
        for operation in ('cancel', 'controller_outage', 'controller_restart', 'backend_restart'):
            match = await invited_match(org, a, b, bots)
            mid = match['id']
            await until(lambda: len(job_ids(qa)) == 2)
            await until(lambda: a.request('/api/matches/' + mid)['turn'] >= 1)
            if operation == 'cancel':
                result = await asyncio.to_thread(org.request, '/api/matches/' + mid + '/cancel', {})
                assert result['result']['reason'] == 'organizer_cancelled'
            elif operation == 'controller_outage':
                await asyncio.to_thread(qa.compose, 'stop', 'controller')
                await until(lambda: a.request('/api/matches/' + mid)['status'] == 'interrupted')
                result = await asyncio.to_thread(a.request, '/api/matches/' + mid)
                assert result['result'] == {'winner': None, 'reason': 'runner_unavailable', 'faults': {}}
                try:
                    await asyncio.to_thread(a.request, '/api/games/robot_battle/samples/python/submit', {})
                    raise AssertionError('Sandbox unavailable but upload executed')
                except HTTPError as exc:
                    assert exc.code == 503
                await asyncio.to_thread(qa.compose, 'start', 'controller')
                await asyncio.to_thread(qa.ready)
            else:
                service = 'controller' if operation == 'controller_restart' else 'arena'
                # Abrupt exit skips normal shutdown: verify orphan sweep/lease ownership.
                await asyncio.to_thread(qa.compose, 'kill', '-s', 'SIGKILL', service)
                if service == 'arena':
                    # Keep it down: lease expiry must reclaim jobs without a new
                    # backend startup doing the cleanup for it.
                    await until(lambda: not job_ids(qa), seconds=30)
                    print('PASS backend lease expiry while backend remains down', flush=True)
                await asyncio.to_thread(qa.compose, 'up', '-d', '--no-build', '--wait')
                await asyncio.to_thread(qa.ready)
                for player in (org, a, b):
                    player.url = qa.url
                await until(lambda: a.request('/api/matches/' + mid)['status'] == 'interrupted')
                result = await asyncio.to_thread(a.request, '/api/matches/' + mid)
                assert result['result']['winner'] is None
                # WebSockets close on backend restart; caller reconnects for next operation.
            await until(lambda: not job_ids(qa))
            replay = await asyncio.to_thread(a.request, '/api/matches/' + mid + '/replay')
            assert replay['frames'] and replay['match']['status'] == 'interrupted'
            print('PASS', operation, 'no unfair winner, replay retained, no orphan containers', flush=True)
            if operation == 'backend_restart':
                return


def main():
    qa = DockerCheck()
    before = os.environ.get('ARENA_ADMIN_CODE')
    os.environ['ARENA_ADMIN_CODE'] = qa.code
    try:
        qa.up()
        lease_policy(qa, active_backend=True)
        org, a, b = (Player(qa.url) for _ in range(3))
        org.prepare_competition('robot_battle', {'max_turns': 1000})
        bots = [upload_wait(p) for p in (a, b)]
        asyncio.run(lifecycle(qa, org, a, b, bots))
        qa.compose('stop', 'arena')
        lease_policy(qa, active_backend=False)
        probe = Path(__file__).with_name('probe_sandbox.py').read_text(encoding='utf-8')
        result = qa.compose('exec', '-T', '-e', 'SANDBOX_TEST_ACK=1', 'controller',
                            'python', '-B', '-c', probe, 'languages')
        print(result.stdout.strip(), flush=True)
    finally:
        if before is None:
            os.environ.pop('ARENA_ADMIN_CODE', None)
        else:
            os.environ['ARENA_ADMIN_CODE'] = before
        qa.cleanup()


if __name__ == '__main__':
    main()
