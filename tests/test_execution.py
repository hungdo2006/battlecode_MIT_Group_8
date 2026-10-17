import sys
import threading

import pytest

from backend.execution import LegacyRunner, RunnerUnavailable, configured_runner
from sandbox_controller.artifacts import pack, unpack


def test_runner_selection_never_falls_back(monkeypatch):
    monkeypatch.setenv('ARENA_RUNNER', 'sandbox')
    monkeypatch.delenv('ARENA_RUNNER_TOKEN', raising=False)
    with pytest.raises(ValueError, match='TOKEN'):
        configured_runner()
    monkeypatch.setenv('ARENA_RUNNER', 'typo')
    with pytest.raises(ValueError, match='no automatic fallback'):
        configured_runner()


def test_registered_session_can_be_cancelled_before_start(tmp_path):
    runner = LegacyRunner()
    session = runner.session({'command': [sys.executable, '-c', 'raise Exception()'],
                              'folder': str(tmp_path)}, 'job')
    session.close()
    with pytest.raises(RunnerUnavailable, match='cancelled'):
        session.start()
    assert session.process is None


def test_runner_rejects_cross_backend_artifacts():
    with pytest.raises(ValueError, match='another runner'):
        LegacyRunner().compatible({'execution_backend': 'sandbox'})


def test_artifacts_roundtrip_and_reject_paths():
    assert unpack(pack({'bot.py': b'print(1)'}, 'out/'), 'py') == {'bot.py': b'print(1)'}
    for path in ('../out/bot.py', '/out/bot.py', 'out/../bot.py', 'out/sub/bot.py', 'out/bot.py\\evil'):
        with pytest.raises(ValueError):
            unpack(pack({path: b'bad'}), 'py')


def test_artifact_links_are_never_extracted(tmp_path):
    import io
    import tarfile
    for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.DIRTYPE):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w') as archive:
            entry = tarfile.TarInfo('out/bot.py')
            entry.type, entry.linkname = kind, '/etc/passwd'
            archive.addfile(entry)
        with pytest.raises(ValueError):
            unpack(stream.getvalue(), 'py')


@pytest.mark.parametrize('language,name', [('cpp', 'bot'), ('java', 'Main.class')])
def test_artifact_content_type_is_checked(language, name):
    with pytest.raises(ValueError, match='ELF|JVM'):
        unpack(pack({name: b'not a compiled artifact'}, 'out/'), language)


def test_persisted_artifact_integrity_and_toolchain(tmp_path):
    from sandbox_controller.artifacts import ArtifactStore
    store = ArtifactStore(tmp_path)
    metadata = store.save('submission', 'py', {'bot.py': b'pass'}, 'image-original')
    assert store.load('submission', metadata['artifact_digest'], 'image-original') == ('py', {'bot.py': b'pass'})
    with pytest.raises(ValueError, match='mismatch'):
        store.load('submission', metadata['artifact_digest'], 'different-image')
    (tmp_path / 'submission.tar').write_bytes(b'tampered')
    with pytest.raises(ValueError, match='mismatch'):
        store.load('submission', metadata['artifact_digest'], 'image-original')
