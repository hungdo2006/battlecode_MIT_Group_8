import json
import os

import pytest

from backend.storage import Store


def test_atomic_write_retries_transient_windows_replace_lock(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    path.write_text('{"old":true}', encoding="utf-8")
    real_replace = os.replace
    attempts = 0

    def transient_replace(source, destination):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("simulated transient Windows sharing violation")
        return real_replace(source, destination)

    monkeypatch.setattr(os, "replace", transient_replace)
    Store._write(path, {"new": True})

    assert attempts == 2
    assert json.loads(path.read_text(encoding="utf-8")) == {"new": True}
    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_write_preserves_old_file_and_cleans_temp_on_persistent_error(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    path.write_text('{"old":true}', encoding="utf-8")

    def denied_replace(*_):
        raise PermissionError("persistent destination lock")

    monkeypatch.setattr(os, "replace", denied_replace)
    with pytest.raises(PermissionError):
        Store._write(path, {"new": True})

    assert json.loads(path.read_text(encoding="utf-8")) == {"old": True}
    assert list(tmp_path.glob("*.tmp")) == []
