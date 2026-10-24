"""B1.5 production-pilot identity and non-destructive operator gates."""
from copy import deepcopy
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import b15_pilot_runner as b15


def cloud():
    return {
        "name": b15.PROJECT,
        "volumes": {name: {"name": b15.PROJECT + "_" + name}
                    for name in ("pilot_data", "pilot_uploads",
                                 "pilot_caddy_data", "pilot_caddy_config")},
        "networks": {"default": {}, "ingress_private": {"internal": True}},
        "services": {
            "arena": {
                "image": "neon-b1-ec2-pilot-arena:1.0",
                "environment": {"ARENA_RUNNER": "remote_sandbox",
                                "ARENA_REMOTE_RUNNER_KEY": "k" * 64,
                                "ARENA_ACCOUNT_ONLY": "1",
                                "ARENA_PUBLIC_ADMIN_PASSWORD_ONLY": "1"},
                "volumes": [{"type": "volume", "source": "pilot_data", "target": "/app/data"},
                            {"type": "volume", "source": "pilot_uploads", "target": "/app/uploads"}],
            },
            "gateway": {"ports": [{"target": 443, "published": "443"}]},
        },
    }


def test_pilot_identity_is_strict():
    original = cloud()
    b15.project_identity(original)
    for name in ("pilot_data", "pilot_uploads", "pilot_caddy_data"):
        altered = deepcopy(original)
        altered["volumes"][name]["name"] = "neon-arena_" + name
        with pytest.raises(ValueError, match="volume"):
            b15.project_identity(altered)
    altered = deepcopy(original)
    altered["services"]["arena"]["environment"]["ARENA_RUNNER"] = "sandbox"
    with pytest.raises(ValueError, match="remote"):
        b15.project_identity(altered)


@pytest.mark.parametrize("field", ["volumes", "networks", "environment", "ports", "services"])
def test_pilot_remote_model_change_is_refused(field):
    original, generated = cloud(), cloud()
    if field == "volumes":
        generated["volumes"]["pilot_data"]["name"] = "different_data"
    elif field == "networks":
        generated["networks"]["ingress_private"]["internal"] = False
    elif field == "environment":
        generated["services"]["arena"]["environment"]["ARENA_ACCOUNT_ONLY"] = "0"
    elif field == "ports":
        generated["services"]["gateway"]["ports"].append({"target": 9000})
    else:
        generated["services"]["controller"] = {}
    with pytest.raises(ValueError):
        b15.matching_remote(original, generated)


def test_pinning_image_only_does_not_count_as_data_drift():
    expected = cloud()
    generated = cloud()
    generated["services"]["arena"]["image"] = "sha256:" + "e" * 64
    generated["services"]["arena"]["pull_policy"] = "never"
    generated["services"]["arena"]["build"] = {"context": "."}
    b15.matching_remote(expected, generated)


def test_private_file_never_overwrites(tmp_path):
    path = tmp_path / "secret.env"
    b15.safe_private(path, "ARENA_RUNNER_TOKEN=not-real\n")
    with pytest.raises(FileExistsError):
        b15.safe_private(path, "overwrite!")
    assert path.read_text() == "ARENA_RUNNER_TOKEN=not-real\n"


def test_backup_does_not_stop_site_when_drain_fails(monkeypatch, tmp_path):
    calls = []
    class Fake:
        plan = {}
        def exclusive(self): return nullcontext()
        def verify(self): calls.append("verify")
        def control(self, mode, action):
            calls.append(action)
            if action == "drain":
                raise RuntimeError("busy")
            return {"mode": "remote_sandbox"}
        def compose(self, *args):
            calls.append(("compose", *args))
    with pytest.raises(RuntimeError, match="busy"):
        b15.snapshot(Fake(), tmp_path / "unique")
    assert calls == ["verify", "status", "drain"]


def test_backup_returns_to_same_mode_after_failure(monkeypatch, tmp_path):
    calls = []
    class Fake:
        plan = {}
        def exclusive(self): return nullcontext()
        def verify(self): calls.append("verify")
        def control(self, mode, action):
            calls.append((mode, action))
            return {"mode": "remote_sandbox"}
        def compose(self, mode, *args): calls.append((mode, *args))
        def wait_ready(self, mode, timeout): calls.append(("ready", mode))
    def failed_backup(*args): raise RuntimeError("backup failed")
    monkeypatch.setattr(b15.site_backup, "backup", failed_backup)
    with pytest.raises(RuntimeError, match="backup failed"):
        b15.snapshot(Fake(), tmp_path / "new")
    assert ("remote", "stop", "--timeout", "30", "arena") in calls
    assert ("remote", "up", "-d", "--no-deps", "--no-build", "gateway") in calls
    assert ("remote", "up", "-d", "--no-deps", "--no-build", "arena") in calls
    assert ("remote", "resume") in calls


def test_cloud_image_or_database_not_modified_during_invalid_preflight(monkeypatch, tmp_path):
    touched = []
    monkeypatch.setattr(b15.switch, "local_engine", lambda: None)
    monkeypatch.setattr(b15, "CLOUD_ENV", tmp_path / "missing")
    monkeypatch.setattr(b15.switch, "run", lambda *args: touched.append(args))
    with pytest.raises(ValueError, match="cloud.env"):
        b15.prepare(tmp_path / "private")
    assert touched == [] and not (tmp_path / "private").exists()
