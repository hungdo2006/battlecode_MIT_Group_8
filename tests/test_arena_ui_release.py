"""Frontend-only release guards use fake Docker metadata; never touch real EC2."""
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import arena_ui_release as release


def image(name, layers, *, cmd=None):
    return {
        "Id": "sha256:" + name * 64,
        "RootFS": {"Layers": layers},
        "Config": {"Env": ["ARENA_TEST=1"], "Cmd": cmd or ["python", "-m", "uvicorn"]},
    }


def test_refuse_non_frontend_images(monkeypatch, tmp_path):
    original = image("a", ["one", "two"])
    not_layered = image("b", ["different", "extra", "more"])
    with pytest.raises(ValueError, match="ONE frontend-only COPY"):
        release.verify_image(original, not_layered)
    changed_runtime = image("b", ["one", "two", "new"], cmd=["sh"])
    with pytest.raises(ValueError, match="runtime config"):
        release.verify_image(original, changed_runtime)


def test_frontend_payload_must_match_checkout(monkeypatch, tmp_path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    for name in release.FILES:
        (frontend / name).parent.mkdir(parents=True, exist_ok=True)
        (frontend / name).write_bytes(name.encode())
    monkeypatch.setattr(release, "ROOT", tmp_path)
    wanted = {name: hashlib.sha256(name.encode()).hexdigest() for name in release.FILES}
    calls = []
    def fake_run(args):
        calls.append(args)
        return json.dumps(wanted)
    monkeypatch.setattr(release.switch, "run", fake_run)
    release.verify_image(image("a", ["base"]), image("b", ["base", "copy"]))
    assert "--network" in calls[0] and "none" in calls[0]
    assert "--read-only" in calls[0]
    monkeypatch.setattr(release.switch, "run", lambda args: json.dumps({"app.js": "wrong"}))
    with pytest.raises(ValueError, match="differs from checked-out"):
        release.verify_image(image("a", ["base"]), image("b", ["base", "copy"]))


def test_image_probe_hashes_nested_landing_assets_without_docker(monkeypatch, tmp_path):
    """Execute the generated image probe against a fixture, including binary fonts."""
    import subprocess
    import sys

    frontend = tmp_path / "frontend"
    for name in release.FILES:
        target = frontend / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"wOF2\x00\xff\r\n" if name.endswith(".woff2") else name.encode())
    monkeypatch.setattr(release, "ROOT", tmp_path)

    def fixture_probe(args):
        program = args[-1].replace("pathlib.Path('/app/frontend')", f"pathlib.Path({str(frontend)!r})")
        return subprocess.check_output([sys.executable, "-c", program], text=True)

    monkeypatch.setattr(release.switch, "run", fixture_probe)
    release.verify_image(image("a", ["base"]), image("b", ["base", "copy"]))


@pytest.mark.parametrize("missing", [
    "landing.css", "art/arena-workstation.svg", "fonts/Handjet.woff2", "fonts/Handjet-OFL.txt",
    "tokens.css", "results.css", "results.html", "renderers.js",
    "fonts/InterVariable.woff2", "fonts/OFL.txt",
])
def test_matching_html_cannot_hide_missing_frontend_asset(monkeypatch, tmp_path, missing):
    frontend = tmp_path / "frontend"
    wanted = {}
    for name in release.FILES:
        target = frontend / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(name.encode())
        wanted[name] = hashlib.sha256(target.read_bytes()).hexdigest()
    monkeypatch.setattr(release, "ROOT", tmp_path)
    del wanted[missing]
    monkeypatch.setattr(release.switch, "run", lambda args: json.dumps(wanted))
    with pytest.raises(ValueError, match="differs from checked-out"):
        release.verify_image(image("a", ["base"]), image("b", ["base", "copy"]))


def test_pins_same_arena_image_for_local_and_remote(monkeypatch):
    old_id = "sha256:" + "a" * 64
    new_id = "sha256:" + "b" * 64
    local = {"services": {"arena": {"image": old_id, "environment": {"ARENA_RUNNER": "local_sandbox"}},
                          "gateway": {"image": "untouched"}, "controller": {"image": "untouched"}}}
    remote = {"services": {"arena": {"image": old_id, "environment": {"ARENA_RUNNER": "remote_sandbox"}},
                           "gateway": {"image": "untouched"}}}
    sample = {"local": local, "remote": remote}
    captured = []
    monkeypatch.setattr(release.switch, "validate_models", lambda a, b: captured.append((a, b)))
    old, updated_local, updated_remote = release.models(
        SimpleNamespace(model=lambda name: deepcopy(sample[name])), new_id)
    assert old == old_id
    assert updated_local["services"]["arena"]["image"] == new_id
    assert updated_remote["services"]["arena"]["image"] == new_id
    assert updated_local["services"]["controller"] == local["services"]["controller"]
    assert sample["local"]["services"]["arena"]["image"] == old_id
    assert captured


def test_atomic_bundle_replacement(tmp_path):
    original = {"local.json": b"old-local", "remote.json": b"old-remote", "plan.json": b"old-plan"}
    for name, data in original.items():
        (tmp_path / name).write_bytes(data)
    updated = {name: b"new-" + content for name, content in original.items()}
    release.install(tmp_path, updated)
    assert all((tmp_path / name).read_bytes() == updated[name] for name in original)
    assert not list(tmp_path.glob(".ui-release-*"))


def test_requires_unique_checkpoint(tmp_path):
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(ValueError, match="already exists"):
        release.checkpoint(SimpleNamespace(), existing, {}, {})
