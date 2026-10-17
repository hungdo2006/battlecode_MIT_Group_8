"""Restore ONLY into NEW neon-arena-restore-* named volumes.

Never starts services, retags images, removes volumes or overwrites originals.
Failed restores leave new volumes for inspection; use a new project name.
"""
import argparse
import json
from pathlib import Path
import re

try:
    from .backup_docker import HELPER, run
    from .volume_snapshot import ROLES, IMAGE_ID, digest_file, read_snapshot
except ImportError:
    from backup_docker import HELPER, run
    from volume_snapshot import ROLES, IMAGE_ID, digest_file, read_snapshot


def verify_bundle(backup):
    backup = Path(backup).resolve()
    record = json.loads(Path(str(backup) + '.receipt.json').read_text(encoding='utf-8'))
    if record.get('format') != 2 or digest_file(backup) != record['snapshot_sha256']:
        raise ValueError('Backup receipt/checksum mismatch')
    with backup.open('rb') as source:
        if read_snapshot(source) != record['manifest']:
            raise ValueError('Backup manifest does not match receipt')
    manifest = record['manifest']
    images = {image['id'] for image in record['images']}
    required = {*manifest['service_images'].values(), manifest['sandbox_image_id'], *manifest['artifact_images']}
    if not required <= images or not all(IMAGE_ID.fullmatch(image) for image in images):
        raise ValueError('Incomplete or invalid pinned image inventory')
    return record


def restore(backup, project, load_images=False, environment=None):
    if not re.fullmatch(r'neon-arena-restore-[a-z0-9][a-z0-9-]{0,40}', project):
        raise ValueError('Use a NEW project named neon-arena-restore-<unique-name>')
    backup = Path(backup).resolve()
    record = verify_bundle(backup)
    volumes = {role: f'{project}_arena_{role}' for role in ROLES}
    existing = set(run(['docker', 'volume', 'ls', '--format', '{{.Name}}'], environment,
                       capture_output=True, text=True).stdout.split())
    if existing.intersection(volumes.values()):
        raise FileExistsError('A destination volume already exists; refusing overwrite')
    if load_images:
        name = record.get('image_archive')
        if not name or name != Path(name).name:
            raise ValueError('No safe image archive recorded')
        image_archive = backup.parent / name
        if digest_file(image_archive) != record['image_archive_sha256']:
            raise ValueError('Image archive checksum mismatch')
        run(['docker', 'image', 'load', '-i', str(image_archive)], environment, capture_output=True)
    expected = {item['id'] for item in record['images']}
    images = json.loads(run(['docker', 'image', 'inspect', *sorted(expected)], environment,
                            capture_output=True, text=True).stdout)
    if {image['Id'] for image in images} != expected:
        raise ValueError('Exact pinned images are not available')
    engine = json.loads(run(['docker', 'info', '--format', '{{json .}}'], environment,
                            capture_output=True, text=True).stdout)
    arch = {'x86_64': 'amd64', 'aarch64': 'arm64'}.get(engine['Architecture'], engine['Architecture'])
    if engine['OSType'] != 'linux' or any(i['Os'] != 'linux' or i['Architecture'] != arch for i in images):
        raise ValueError('Restore requires a compatible Linux Engine/architecture')
    for role, name in volumes.items():
        run(['docker', 'volume', 'create', '--label', 'com.docker.compose.project=' + project,
             '--label', 'com.docker.compose.volume=arena_' + role, name], environment, capture_output=True)
    helper = ['docker', 'run', '--rm', '--pull', 'never', '--log-driver', 'none',
              '-i', '--network', 'none', '--read-only', '--user', '0:0',
              '--cap-drop', 'ALL', '--cap-add', 'CHOWN', '--security-opt', 'no-new-privileges:true',
              '--memory', '256m', '--cpus', '1', '--pids-limit', '16']
    for role, name in volumes.items():
        helper += ['--mount', f'type=volume,src={name},dst=/snapshot/{role},volume-nocopy']
    helper += ['--entrypoint', 'python', record['manifest']['service_images']['arena'],
               '-B', '-c', HELPER.read_text(encoding='utf-8'), 'restore']
    with backup.open('rb') as source:
        run(helper, environment, stdin=source, capture_output=True)
    return volumes


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', required=True)
    parser.add_argument('--project', required=True)
    parser.add_argument('--load-images', action='store_true', help='Import verified image archive into local Engine')
    args = parser.parse_args()
    print(json.dumps(restore(args.backup, args.project, args.load_images), indent=2))
    print('NO application was started. Review image IDs/configuration before running it.')
