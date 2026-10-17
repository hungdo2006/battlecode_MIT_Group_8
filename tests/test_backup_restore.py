import io
import json
from pathlib import Path
from types import SimpleNamespace
import tarfile

import pytest
from fastapi.testclient import TestClient

from backend.main import create_app
from backend.writer_lock import WriterLock
from sandbox_controller.artifacts import ArtifactStore
from scripts import backup_docker as backup_cli, restore_docker as restore_cli
from scripts.volume_snapshot import ROLES, digest_file, read_snapshot, write_snapshot

BOT_IMAGE = 'sha256:' + 'a' * 64
OLD_IMAGE = 'sha256:' + 'b' * 64
APP_IMAGE = 'sha256:' + 'c' * 64
CONTROLLER_IMAGE = 'sha256:' + 'd' * 64


@pytest.fixture
def source(tmp_path):
    roots = {role: tmp_path / 'original' / role for role in ROLES}
    for root in roots.values():
        root.mkdir(parents=True)
    # Build valid application metadata only inside this disposable directory.
    with TestClient(create_app(tmp_path / 'original')) as client:
        for mid in ('old', 'new'):
            client.app.state.store.save_match({'id': mid, 'game_id': 'robot_battle', 'status': 'completed',
                                               'turn': 1, 'rules_snapshot': {'max_turns': 1},
                                               'result': {'winner': None, 'reason': 'draw'}})
    (roots['data'] / 'replays' / 'old.json').write_text('{"frames":[{"turn":0}]}')
    (roots['data'] / 'replays' / 'new.jsonl').write_bytes(b'{"turn":0}\n{"turn":1}\n')
    for name in ('sessions', 'players', 'invitations'):
        (roots['data'] / (name + '.json')).write_text('{}')
    for name in ('bot.py', 'hunter.cpp', 'Main.java'):
        (roots['uploads'] / name).write_bytes(b'original source\x00\xff\n')
    ArtifactStore(roots['artifacts']).save('artifact', 'py', {'bot.py': b'print(1)'}, OLD_IMAGE)
    return roots


def file_bytes(roots):
    return {role + '/' + p.relative_to(root).as_posix(): p.read_bytes()
            for role, root in roots.items() for p in root.rglob('*')
            if p.is_file() and p.name != '.writer.lock'}


class FakeDocker:
    """CLI integration double: actual archive IO, no Engine or production paths."""
    def __init__(self, source, tmp_path):
        self.source, self.root = source, tmp_path / 'restored'
        self.running, self.extra_writer = set(), False
        self.calls, self.destinations = [], {}
        self.records = {
            'arena-id': {'Image': APP_IMAGE, 'State': {'Running': False}, 'Config': {'Env': ['SECRET=never-export-me']},
                         'Mounts': [{'Type': 'volume', 'Destination': '/app/' + r, 'Name': 'original_' + r, 'RW': True}
                                    for r in ('data', 'uploads')]},
            'controller-id': {'Image': CONTROLLER_IMAGE, 'State': {'Running': False},
                              'Config': {'Env': ['SANDBOX_IMAGE=neon-arena-bot:4.0', 'TOKEN=never-export-me']},
                              'Mounts': [{'Type': 'volume', 'Destination': '/artifacts', 'Name': 'original_artifacts', 'RW': True}]}}

    def __call__(self, args, environment=None, **kwargs):
        self.calls.append(args)
        def result(value):
            return SimpleNamespace(stdout=value if isinstance(value, str) else json.dumps(value))
        if args[1] == 'compose':
            return result(args[-1] + '-id')
        if args[1] == 'inspect':
            return result([self.records[key] for key in args[2:]])
        if args[1] == 'ps':
            if self.extra_writer:
                raise RuntimeError('A running container still has writable access')
            return result('')
        if args[1:3] == ['image', 'inspect']:
            return result([{'Id': BOT_IMAGE if image == 'neon-arena-bot:4.0' else image,
                            'RepoDigests': [], 'Os': 'linux', 'Architecture': 'amd64',
                            'Config': {'Env': ['SECRET=never-export-me']}} for image in args[3:]])
        if args[1:3] == ['image', 'save']:
            kwargs['stdout'].write(b'binary image bundle\x00\xff')
            return result('')
        if args[1:3] == ['image', 'load']:
            return result('')
        if args[1] == 'info':
            return result({'OSType': 'linux', 'Architecture': 'x86_64'})
        if args[1:3] == ['volume', 'ls']:
            return result('\n'.join(self.destinations.values()))
        if args[1:3] == ['volume', 'create']:
            name = args[-1]
            role = name.rsplit('_', 1)[1]
            self.destinations[role] = name
            (self.root / role).mkdir(parents=True)
            return result(name)
        if args[1] == 'run':
            assert '--network' in args and 'none' in args and '--read-only' in args
            mounts = [args[i+1] for i, value in enumerate(args) if value == '--mount']
            assert all('docker.sock' not in mount and 'dst=/snapshot/' in mount for mount in mounts)
            if args[-1] == 'restore':
                assert '--cap-add' in args and 'CHOWN' in args
                read_snapshot(kwargs['stdin'], {r: self.root / r for r in ROLES})
            else:
                with WriterLock(self.source['data']):
                    write_snapshot(self.source, kwargs['stdout'], json.loads(args[-1]))
            return result('')
        raise AssertionError(args)


def test_three_volume_bundle_restore_images_and_legacy_replays(source, tmp_path, monkeypatch):
    fake = FakeDocker(source, tmp_path)
    monkeypatch.setattr(backup_cli, 'run', fake)
    monkeypatch.setattr(restore_cli, 'run', fake)
    before = file_bytes(source)
    output = backup_cli.backup(tmp_path / 'backup.tar.gz', project='local-copy')
    receipt = restore_cli.verify_bundle(output)
    assert receipt['manifest']['artifact_images'] == [OLD_IMAGE]
    assert {i['id'] for i in receipt['images']} == {BOT_IMAGE, OLD_IMAGE, APP_IMAGE, CONTROLLER_IMAGE}
    assert 'never-export-me' not in Path(str(output) + '.receipt.json').read_text()
    restore_cli.restore(output, 'neon-arena-restore-unit', load_images=True)
    restored = {r: fake.root / r for r in ROLES}
    assert file_bytes(restored) == before == file_bytes(source)
    assert not (restored['data'] / '.writer.lock').exists()
    # Both replay formats remain readable after a normal backend restart.
    with TestClient(create_app(fake.root)) as client:
        assert client.get('/api/games').status_code == 200
        assert client.app.state.store.data == restored['data']
        assert client.get('/api/matches/old/replay').json()['frames'] == [{'turn': 0}]
        assert client.get('/api/matches/new/replay').json()['frames'] == [{'turn': 0}, {'turn': 1}]
    assert (restored['data'] / 'replays' / 'new.jsonl').read_bytes() == before['data/replays/new.jsonl']
    with pytest.raises(FileExistsError):
        restore_cli.restore(output, 'neon-arena-restore-unit')


@pytest.mark.parametrize('service', ['arena', 'controller'])
def test_backup_refuses_either_running_service(source, tmp_path, monkeypatch, service):
    fake = FakeDocker(source, tmp_path)
    fake.records[service + '-id']['State']['Running'] = True
    monkeypatch.setattr(backup_cli, 'run', fake)
    with pytest.raises(RuntimeError, match='BOTH'):
        backup_cli.backup(tmp_path / 'no.tar.gz')
    assert not (tmp_path / 'no.tar.gz').exists()


def test_backup_never_overwrites_and_restore_checks_before_docker(source, tmp_path, monkeypatch):
    fake = FakeDocker(source, tmp_path)
    monkeypatch.setattr(backup_cli, 'run', fake)
    monkeypatch.setattr(restore_cli, 'run', fake)
    output = backup_cli.backup(tmp_path / 'once.tar.gz')
    previous = output.read_bytes()
    with pytest.raises(FileExistsError):
        backup_cli.backup(output)
    assert output.read_bytes() == previous
    output.write_bytes(previous[:-1] + b'x')
    fake.calls.clear()
    with pytest.raises(ValueError, match='checksum'):
        restore_cli.restore(output, 'neon-arena-restore-corrupt')
    assert not fake.calls


@pytest.mark.parametrize('path,kind', [('../outside', tarfile.REGTYPE), ('uploads/C:/escape', tarfile.REGTYPE),
                                      ('uploads/link', tarfile.SYMTYPE), ('data/link', tarfile.LNKTYPE),
                                      ('data/device', tarfile.CHRTYPE)])
def test_restore_rejects_traversal_links_and_devices(tmp_path, path, kind):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w:gz') as archive:
        entry = tarfile.TarInfo(path)
        entry.type, entry.linkname = kind, '/outside'
        archive.addfile(entry)
    stream.seek(0)
    with pytest.raises(ValueError, match='Unsafe'):
        read_snapshot(stream)


def test_local_restore_checksum_mismatch_and_nonempty_destination(source, tmp_path):
    stream = io.BytesIO()
    write_snapshot(source, stream, {})
    roots = {r: tmp_path / 'nonempty' / r for r in ROLES}
    for root in roots.values():
        root.mkdir(parents=True)
    sentinel = roots['data'] / 'keep'
    sentinel.write_bytes(b'do not overwrite')
    stream.seek(0)
    with pytest.raises(ValueError, match='empty'):
        read_snapshot(stream, roots)
    assert sentinel.read_bytes() == b'do not overwrite'


def test_restore_rejects_production_project_before_any_docker(monkeypatch):
    monkeypatch.setattr(restore_cli, 'run', lambda *a, **k: pytest.fail('Docker must not be called'))
    with pytest.raises(ValueError, match='NEW project'):
        restore_cli.restore('does-not-exist', 'neon-arena')
