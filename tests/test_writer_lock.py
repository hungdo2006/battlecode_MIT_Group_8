import os
from pathlib import Path
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

import backend.main as main
from backend.writer_lock import WriterAlreadyRunning, WriterLock

ROOT = Path(__file__).resolve().parents[1]


def child(code, path):
    return subprocess.run([sys.executable, "-c", code, str(path)], cwd=ROOT,
                          env={**os.environ, "ARENA_RUNNER": "legacy"},
                          capture_output=True, text=True, timeout=15)


def test_second_process_cannot_initialize_store_or_claim_controller(tmp_path):
    # These sentinels must not be modified by Store's startup recovery.
    data = tmp_path / "data"
    data.mkdir()
    (data / "matches.json").write_text('{"sentinel":"do not parse or replace"}')
    (data / "replay.jsonl").write_bytes(b'old replay\n')
    code = """
import sys
from pathlib import Path
from fastapi.testclient import TestClient
import backend.main as main
from backend.writer_lock import WriterAlreadyRunning
def forbidden(*args, **kwargs):
    raise AssertionError('Store/runner reached before writer lock')
main.Store = main.configured_runner = forbidden
try:
    with TestClient(main.create_app(Path(sys.argv[1]))):
        raise AssertionError('second backend started')
except WriterAlreadyRunning:
    print('blocked before Store and runner')
"""
    before = {p.name: p.read_bytes() for p in data.iterdir()}
    with WriterLock(data):
        result = child(code, tmp_path)
        assert result.returncode == 0, result.stderr
        assert 'blocked before Store and runner' in result.stdout
        assert all((data / name).read_bytes() == content for name, content in before.items())


def test_release_crash_and_permanent_file(tmp_path):
    code = """
import os,sys
from pathlib import Path
from backend.writer_lock import WriterLock
lock = WriterLock(Path(sys.argv[1]))
lock.__enter__()
os._exit(0)
"""
    assert child(code, tmp_path).returncode == 0
    with WriterLock(tmp_path):
        with pytest.raises(WriterAlreadyRunning):
            with WriterLock(tmp_path):
                pass
    assert (tmp_path / '.writer.lock').exists()
    with WriterLock(tmp_path):
        pass


def test_lock_released_after_failed_runner_startup(tmp_path, monkeypatch):
    class Runner:
        stopped = False
        def startup(self):
            raise RuntimeError('startup failed')
        def shutdown(self):
            self.stopped = True
    runner = Runner()
    monkeypatch.setattr(main, 'configured_runner', lambda *args: runner)
    with pytest.raises(RuntimeError, match='startup failed'):
        with TestClient(main.create_app(tmp_path)):
            pass
    assert runner.stopped
    with WriterLock(tmp_path / 'data'):
        pass


def test_same_data_volume_different_base_alias_and_normal_shutdown(tmp_path):
    with TestClient(main.create_app(tmp_path)) as first:
        assert first.get('/api/health').status_code == 200
        with pytest.raises(WriterAlreadyRunning):
            with TestClient(main.create_app(tmp_path / 'data' / '..')):
                pass
    with TestClient(main.create_app(tmp_path)) as restarted:
        assert restarted.get('/api/health').status_code == 200
