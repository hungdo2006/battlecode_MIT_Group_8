"""Cold three-volume backup: stop arena AND controller, never deletes volumes.

Creates OUTPUT, OUTPUT.images.tar and OUTPUT.receipt.json with checksums.
No credentials/Config.Env are included. Protect backups as sensitive data.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

try:
    from .volume_snapshot import ROLES, IMAGE_ID, digest_file, read_snapshot
except ImportError:
    from volume_snapshot import ROLES, IMAGE_ID, digest_file, read_snapshot

ROOT = Path(__file__).resolve().parent.parent
HELPER = Path(__file__).with_name('volume_snapshot.py')
DESTINATIONS = {'/app/data': 'data', '/app/uploads': 'uploads', '/artifacts': 'artifacts'}


def run(args, environment=None, **kwargs):
    return subprocess.run(args, cwd=ROOT, env=environment, check=True, **kwargs)


def inspect_images(ids, environment):
    records = json.loads(run(['docker', 'image', 'inspect', *sorted(ids)], environment,
                             capture_output=True, text=True).stdout)
    # Never serialize full inspect records: Config.Env may contain credentials.
    return [{'id': r['Id'], 'repo_digests': r.get('RepoDigests') or [],
             'os': r['Os'], 'architecture': r['Architecture']} for r in records]


def assert_no_writers(volumes, environment):
    for volume in volumes.values():
        ids = run(['docker', 'ps', '-aq', '--filter', 'volume=' + volume], environment,
                  capture_output=True, text=True).stdout.split()
        if not ids:
            continue
        for record in json.loads(run(['docker', 'inspect', *ids], environment,
                                     capture_output=True, text=True).stdout):
            state = record['State']
            if (state.get('Running') or state.get('Paused') or state.get('Restarting')) and any(
                    m.get('Name') == volume and m.get('RW') for m in record['Mounts']):
                raise RuntimeError('A running container still has writable access to a backup volume')


def backup(output, project=None, environment=None, save_images=True):
    command = ['docker', 'compose', '-f', str(ROOT / 'compose.yaml')]
    if project:
        command += ['-p', project]
    volumes, image_ids, service_images = {}, set(), {}
    sandbox_ref = None
    for service in ('arena', 'controller'):
        ids = run(command + ['ps', '-a', '-q', service], environment,
                  capture_output=True, text=True).stdout.split()
        if len(ids) != 1:
            raise RuntimeError('Exactly one stopped arena and controller are required; do not down before backup')
        record = json.loads(run(['docker', 'inspect', ids[0]], environment,
                                capture_output=True, text=True).stdout)[0]
        if record['State'].get('Running') or record['State'].get('Restarting') or record['State'].get('Paused'):
            raise RuntimeError('Stop BOTH arena and controller before backup')
        service_images[service] = record['Image']
        image_ids.add(record['Image'])
        for mount in record['Mounts']:
            role = DESTINATIONS.get(mount['Destination'])
            if role:
                if mount['Type'] != 'volume' or role in volumes:
                    raise RuntimeError('Backup requires exactly three named volumes')
                volumes[role] = mount['Name']
        if service == 'controller':
            sandbox_ref = next((v.split('=', 1)[1] for v in record['Config'].get('Env', [])
                                if v.startswith('SANDBOX_IMAGE=')), None)
    if set(volumes) != set(ROLES) or not sandbox_ref:
        raise RuntimeError('Missing source, replay or artifact volume / sandbox image configuration')
    bot = json.loads(run(['docker', 'image', 'inspect', sandbox_ref], environment,
                         capture_output=True, text=True).stdout)[0]['Id']
    image_ids.add(bot)
    assert_no_writers(volumes, environment)
    output = Path(output).resolve()
    image_archive, receipt = Path(str(output) + '.images.tar'), Path(str(output) + '.receipt.json')
    if any(path.exists() for path in (output, image_archive, receipt)):
        raise FileExistsError('Backup destination already exists; choose a new name')
    output.parent.mkdir(parents=True, exist_ok=True)
    metadata = {'created_at': datetime.now(timezone.utc).isoformat(), 'volumes': volumes,
                'service_images': service_images, 'sandbox_image_ref': sandbox_ref, 'sandbox_image_id': bot}
    helper = ['docker', 'run', '--rm', '--pull', 'never', '--log-driver', 'none',
              '--network', 'none', '--read-only', '--user', '10001:10001',
              '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
              '--memory', '256m', '--cpus', '1', '--pids-limit', '16']
    for role in ROLES:
        helper += ['--mount', f'type=volume,src={volumes[role]},dst=/snapshot/{role}'
                   + ('' if role == 'data' else ',readonly')]
    helper += ['--entrypoint', 'python', service_images['arena'], '-B', '-c',
               HELPER.read_text(encoding='utf-8'), json.dumps(metadata)]
    with output.open('xb') as archive:
        run(helper, environment, stdout=archive)
        archive.flush()
        os.fsync(archive.fileno())
    # A failed backup has NO receipt. Do not treat partial files as a valid bundle.
    assert_no_writers(volumes, environment)
    with output.open('rb') as archive:
        manifest = read_snapshot(archive)
    image_ids.update(manifest['artifact_images'])
    if not all(IMAGE_ID.fullmatch(image) for image in image_ids):
        raise ValueError('Invalid pinned image ID')
    images = inspect_images(image_ids, environment)  # Fail if an old artifact image is missing.
    image_digest = None
    if save_images:
        with image_archive.open('xb') as target:
            run(['docker', 'image', 'save', *sorted(image_ids)], environment, stdout=target)
            target.flush()
            os.fsync(target.fileno())
        image_digest = digest_file(image_archive)
    record = {'format': 2, 'snapshot_sha256': digest_file(output), 'images': images,
              'image_archive_sha256': image_digest, 'image_archive': image_archive.name if save_images else None,
              'manifest': manifest}
    with receipt.open('x', encoding='utf-8') as target:
        json.dump(record, target, ensure_ascii=False, indent=2)
        target.flush()
        os.fsync(target.fileno())
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, help='New .tar.gz archive path')
    parser.add_argument('--project', help='Compose project override, if used')
    parser.add_argument('--metadata-only', action='store_true', help='Do not export images; requires exact images elsewhere')
    args = parser.parse_args()
    result = backup(args.output, args.project, save_images=not args.metadata_only)
    print(f'Verified backup: {result}; receipt: {result}.receipt.json')
