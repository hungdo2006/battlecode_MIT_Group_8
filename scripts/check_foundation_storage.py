"""Real Engine storage checks, called only with disposable DockerCheck projects."""
import asyncio
import json
import secrets
import subprocess

try:
    from .restore_docker import restore
except ImportError:
    from restore_docker import restore


def single_writer(qa):
    probe = """
import asyncio
import backend.main as main
from backend.writer_lock import WriterAlreadyRunning
def forbidden(*args, **kwargs):
    raise AssertionError('Reached Store/runner while another writer is active')
main.Store = main.configured_runner = forbidden
async def check():
    try:
        async with main.app.router.lifespan_context(main.app):
            raise AssertionError('Second backend acquired a live data volume')
    except WriterAlreadyRunning:
        print('BLOCKED_BEFORE_STORE_AND_CONTROLLER')
asyncio.run(check())
"""
    result = qa.compose('run', '--rm', '--no-deps', '-T', '--entrypoint', 'python', 'arena', '-B', '-c', probe)
    assert 'BLOCKED_BEFORE_STORE_AND_CONTROLLER' in result.stdout, result.stdout
    print('PASS shared Docker volume: second backend blocked before Store/Controller', flush=True)


def verify_restored_files(qa, volumes, manifest):
    probe = """
import hashlib,json
from pathlib import Path
records = {}
for role in ('data','uploads','artifacts'):
    root = Path('/snapshot') / role
    for path in sorted(root.rglob('*')):
        if path.is_file() and path.name != '.writer.lock':
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream,'sha256').hexdigest()
            records[role+'/'+path.relative_to(root).as_posix()] = {'size':path.stat().st_size,'sha256':digest}
print(json.dumps(records,sort_keys=True))
"""
    args = ['docker', 'run', '--rm', '--pull', 'never', '--network', 'none', '--read-only',
            '--user', '10001:10001', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true']
    for role, name in volumes.items():
        args += ['--mount', f'type=volume,src={name},dst=/snapshot/{role},readonly']
    args += ['--entrypoint', 'python', manifest['service_images']['arena'], '-B', '-c', probe]
    result = subprocess.run(args, env=qa.env, check=True, capture_output=True, text=True)
    assert json.loads(result.stdout) == manifest['files'], 'Restored byte checksums differ from backup'
    print('PASS restored three volumes: every file hash/size and UID 10001 readability', flush=True)


def restore_and_play(source_qa, archive, bundle, org, a, b, expected, hashes, bots):
    try:
        from .check_docker import DockerCheck, reuse, verify_persistence
    except ImportError:
        from check_docker import DockerCheck, reuse, verify_persistence
    target = DockerCheck()
    target.project = 'neon-arena-restore-qa-' + secrets.token_hex(5)
    target.env['SANDBOX_NAMESPACE'] = target.project + '-test'
    manifest = bundle['manifest']
    target.override.write_text(json.dumps({'services': {
        'arena': {'image': manifest['service_images']['arena']},
        'controller': {'image': manifest['service_images']['controller'],
                       'environment': {'SANDBOX_IMAGE': manifest['sandbox_image_id']}},
        'bot-image': {'image': manifest['sandbox_image_id']}}}), encoding='utf-8')
    old_urls = [player.url for player in (org, a, b)]
    try:
        volumes = restore(archive, target.project, load_images=True, environment=target.env)
        assert not set(volumes.values()).intersection(manifest['volumes'].values())
        verify_restored_files(target, volumes, manifest)
        target.up()
        target.inspect()
        single_writer(target)
        for player in (org, a, b):
            player.url = target.url
        verify_persistence(org, a, b, expected, hashes, target)
        org.request('/api/session/organizer', {'code': target.code})
        mid = asyncio.run(reuse(org, a, b, bots))
        assert a.request('/api/matches/' + mid + '/replay')['frames']
        assert target.uploads() == hashes
        print('PASS pinned-image restore: sessions/bots/rules/history/replays + new sandbox match, 3 WebSockets', flush=True)
        return target.project
    finally:
        for player, url in zip((org, a, b), old_urls):
            player.url = url
        target.cleanup()  # Validates project labels before removing only its volumes.
