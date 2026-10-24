"""Maintenance safety boundaries; no network or Docker daemon required."""
import asyncio
from copy import deepcopy
from contextlib import nullcontext
import json
import ssl
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.artifact_compat import artifact_current
from backend.execution import RunnerUnavailable, configured_runner
from backend.main import create_app
from backend.runner_control import RunnerControl, validate_status
from sandbox_controller.artifacts import ArtifactStore
from scripts import runner_switch as switch, runner_site_backup as backup


def model():
    return {"name": "neon-arena", "services": {
        "arena": {"image": "sha256:" + "a" * 64, "environment": {
            "ARENA_RUNNER": "sandbox", "ARENA_CONTROLLER_URL": "http://controller:9000",
            "ARENA_RUNNER_TOKEN": "pc-only-controller-token-" * 2,
            "ARENA_ADMIN_TOTP_REQUIRED": "0", "ARENA_PUBLIC_ADMIN_PASSWORD_ONLY": "1",
            "ARENA_SELF_REGISTRATION": "1", "ARENA_AUTH_ORIGINS": "https://arena.example.test",
            "SMTP_PASSWORD": "literal-$FOO-${BAR}-$$-do-not-expand"},
            "depends_on": {"controller": {"condition": "service_healthy"}},
            "networks": {"ingress_private": None, "runner_private": None},
            "volumes": [{"type": "volume", "source": "arena_" + role, "target": "/app/" + role}
                        for role in ("data", "uploads")]},
        "controller": {"image": "sha256:" + "b" * 64, "environment": {
            "ARENA_RUNNER_TOKEN": "pc-only-controller-token-" * 2},
            "volumes": [{"type": "volume", "source": "arena_artifacts", "target": "/artifacts"}]},
        "bot-image": {"image": "sha256:" + "c" * 64},
        "gateway": {"image": "sha256:" + "d" * 64,
            "ports": [{"target": 443, "published": "443", "protocol": "tcp"}],
            "volumes": [{"type": "volume", "source": "caddy_" + role, "target": "/" + role}
                        for role in ("data", "config")]}},
        "networks": {"ingress_private": {"internal": True}, "runner_private": {"internal": True}},
        "volumes": {name: {"name": "neon-arena_" + name} for name in
                    ("arena_data", "arena_uploads", "arena_artifacts", "caddy_data", "caddy_config")}}


def test_full_remote_model_preserves_private_override_settings_and_resources():
    local = model()
    before = deepcopy(local)
    remote = switch.remote_model(local, "separate-machine-key-" * 3)
    assert local == before
    assert set(remote["services"]) == {"arena", "gateway"}
    env = remote["services"]["arena"]["environment"]
    assert env["ARENA_ADMIN_TOTP_REQUIRED"] == "0"
    assert env["ARENA_PUBLIC_ADMIN_PASSWORD_ONLY"] == "1"
    assert env["ARENA_SELF_REGISTRATION"] == "1"
    assert env["SMTP_PASSWORD"] == before["services"]["arena"]["environment"]["SMTP_PASSWORD"]
    assert "ARENA_RUNNER_TOKEN" not in env and "ARENA_CONTROLLER_URL" not in env
    assert switch.volume_map(remote).items() <= switch.volume_map(local).items()


@pytest.mark.parametrize("change", ["volume", "image", "password-only", "caddy", "socket", "dependency"])
def test_remote_model_rejects_resource_or_security_drift(change):
    local = model()
    remote = switch.remote_model(local, "k" * 64)
    arena = remote["services"]["arena"]
    if change == "volume": remote["volumes"]["arena_data"]["name"] = "empty-new-volume"
    if change == "image": arena["image"] = "sha256:" + "f" * 64
    if change == "password-only": arena["environment"]["ARENA_PUBLIC_ADMIN_PASSWORD_ONLY"] = "0"
    if change == "caddy": remote["services"]["gateway"]["ports"] = []
    if change == "socket": arena["volumes"].append({"type": "bind", "source": "/var/run/docker.sock", "target": "/sock"})
    if change == "dependency": arena["depends_on"] = {"controller": {}}
    with pytest.raises(ValueError): switch.validate_models(local, remote)


@pytest.mark.parametrize("key", ["short", "pc-only-controller-token-" * 2])
def test_distinct_machine_key_required(key):
    with pytest.raises(ValueError): switch.remote_model(model(), key)


def test_literal_compose_serialization_keeps_dollar_secrets_private(tmp_path):
    path = tmp_path / "private.json"
    switch.private_json(path, model(), compose=True)
    env = json.loads(path.read_text())["services"]["arena"]["environment"]
    assert env["SMTP_PASSWORD"] == "literal-$$FOO-$${BAR}-$$$$-do-not-expand"
    with pytest.raises(FileExistsError): switch.private_json(path, {})


def state(**values):
    return {"protocol": 1, "time": 100, "admission_closed": True, "mode": "local_sandbox",
            "active_matches": 0, "operations": 0, "uploading": False, "cleanup_pending": 0,
            "ready": True, **values}


@pytest.mark.parametrize("values", [{"active_matches": 1}, {"operations": 1}, {"uploading": True},
    {"cleanup_pending": 1}, {"admission_closed": False}, {"time": 80}, {"protocol": 0}])
def test_switch_refuses_busy_unknown_or_stale_writer(values):
    with pytest.raises(RuntimeError): validate_status(state(**values), drained=True, now=100)


def test_missing_remote_worker_or_wrong_transport_refuses_resume():
    for values in ({"ready": False}, {"mode": "remote_sandbox", "transport": "local"}):
        with pytest.raises(RuntimeError): validate_status(state(**values), ready=True, now=100)


def test_drain_survives_restart_blocks_new_work_and_observes_inflight_operation(tmp_path):
    control = RunnerControl(tmp_path, "sandbox")
    manager = SimpleNamespace(live={}, runner=SimpleNamespace(pending_closes={}))
    with control.operation():
        nonce = control.request(True)
        assert control.publish(manager, False, {"ready": True})["operations"] == 1
        assert control.status()["request_id"] == nonce
        with pytest.raises(RunnerUnavailable): control.require_open()
    restarted = RunnerControl(tmp_path, "remote_sandbox")
    assert restarted.closed and restarted.boot_id != control.boot_id
    control.publish(manager, False, {"ready": True})
    validate_status(control.status(), drained=True)
    assert "drain" in (control.directory / "audit.jsonl").read_text()
    (control.directory / "intent.json").write_text("corrupt")
    assert restarted.closed


def test_drained_http_upload_and_match_manager_do_not_create_work(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        control = client.app.state.runner_control
        control.request(True)
        with pytest.raises(RunnerUnavailable):
            client.portal.call(client.app.state.manager.start, SimpleNamespace())
        # Session is a player in this legacy QA fixture.
        client.get("/api/session")
        response = client.post("/api/bots", files={"file": ("x.py", b"print('x')")},
                               data={"game_id": "robot_battle"})
        assert response.status_code == 503
        assert not client.app.state.manager.live


def test_store_identity_prevents_false_compatibility_on_another_pc(tmp_path):
    cloud, pc = ArtifactStore(tmp_path / "cloud"), ArtifactStore(tmp_path / "pc")
    image = "sha256:" + "e" * 64
    bot = {"status": "ready", "game_id": "robot_battle", **cloud.save("job", "py", {"bot.py": b"print(1)"}, image)}
    before = deepcopy(bot)
    store = SimpleNamespace(sandbox_image_for_game=lambda game: image,
                            sandbox_artifact_store=lambda: pc.identity)
    assert not artifact_current(store, bot)
    store.sandbox_artifact_store = lambda: cloud.identity
    assert artifact_current(store, bot)
    assert ArtifactStore(tmp_path / "cloud").identity == cloud.identity
    del bot["artifact_store_id"]
    assert not artifact_current(store, bot)
    assert before["status"] == bot["status"] == "ready"


class FakeSite:
    def __init__(self, *, busy=False, fail=False, rollback_fail=False):
        self.plan = {}
        self.calls = []
        self.busy, self.fail, self.rollback_fail = busy, fail, rollback_fail
    def verify(self): self.calls.append(("verify",))
    def exclusive(self): return nullcontext()
    def control(self, mode, action):
        self.calls.append(("control", mode, action))
        if action == "drain" and self.busy: raise RuntimeError("busy")
        return {"mode": "local_sandbox"}
    def model(self, mode): return switch.remote_model(model(), "r" * 64)
    def audit(self, event, **details): self.calls.append(("audit", event))
    def compose(self, mode, *args): self.calls.append(("compose", mode, *args))
    def wait_ready(self, mode, timeout):
        self.calls.append(("ready", mode))
        if (mode == "remote" and self.fail) or (mode == "local" and self.rollback_fail):
            raise RuntimeError("missing worker")


def test_transition_busy_or_invalid_tls_never_stops_services(monkeypatch):
    monkeypatch.setattr(backup, "verify_complete", lambda *a: None)
    busy = FakeSite(busy=True)
    with pytest.raises(RuntimeError): switch.transition(busy, "remote", backup_directory="unused", tls_check=lambda u: None)
    assert not any(c[0] == "compose" for c in busy.calls)
    bad_tls = FakeSite()
    def reject(url): raise ssl.SSLCertVerificationError("bad cert")
    with pytest.raises(ssl.SSLCertVerificationError):
        switch.transition(bad_tls, "remote", backup_directory="unused", tls_check=reject)
    assert not any(c[0] in ("compose", "audit") for c in bad_tls.calls)


def test_failed_target_rolls_back_before_admitting_any_target_jobs(monkeypatch):
    monkeypatch.setattr(backup, "verify_complete", lambda *a: None)
    site = FakeSite(fail=True)
    with pytest.raises(RuntimeError, match="original mode restored"):
        switch.transition(site, "remote", backup_directory="unused", tls_check=lambda u: None)
    assert ("control", "remote", "resume") not in site.calls
    assert ("control", "local", "resume") in site.calls
    assert site.calls[-1] == ("audit", "rollback_complete")


def test_failed_rollback_leaves_admission_closed(monkeypatch):
    monkeypatch.setattr(backup, "verify_complete", lambda *a: None)
    site = FakeSite(fail=True, rollback_fail=True)
    with pytest.raises(RuntimeError, match="admission remains closed"):
        switch.transition(site, "remote", backup_directory="unused", tls_check=lambda u: None)
    assert not any(c[:1] == ("control",) and c[-1] == "resume" for c in site.calls)


@pytest.mark.parametrize("failure", ["resume_reply_lost", "audit_after_resume"])
def test_resume_or_commit_acknowledgement_loss_never_rolls_back_admitted_jobs(monkeypatch, failure):
    monkeypatch.setattr(backup, "verify_complete", lambda *a: None)
    class Site(FakeSite):
        def control(self, mode, action):
            result = super().control(mode, action)
            if failure == "resume_reply_lost" and mode == "remote" and action == "resume":
                raise RuntimeError("response lost after application resumed")
            return result
        def audit(self, event, **details):
            super().audit(event, **details)
            if failure == "audit_after_resume" and event == "committed":
                raise OSError("disk full after resume")
    site = Site()
    with pytest.raises(RuntimeError, match="no automatic rollback after resume"):
        switch.transition(site, "remote", backup_directory="unused", tls_check=lambda u: None)
    assert ("control", "remote", "resume") in site.calls
    assert ("control", "local", "resume") not in site.calls
    assert not any(c == ("audit", "target_failed") for c in site.calls)


def test_incomplete_backup_blocks_before_drain(monkeypatch):
    def reject(*args): raise ValueError("missing referenced image")
    monkeypatch.setattr(backup, "verify_complete", reject)
    site = FakeSite()
    with pytest.raises(ValueError): switch.transition(site, "remote", backup_directory="unused", tls_check=lambda u: None)
    assert site.calls == [("verify",)]


@pytest.mark.parametrize("origin", ["http://arena.test", "https://user:secret@arena.test", "https://arena.test/path"])
def test_public_tls_cannot_use_plaintext_credentials_or_redirect_paths(origin):
    with pytest.raises(ValueError): switch.public_tls(origin)


def test_public_tls_uses_system_trust_and_hostname_validation(monkeypatch):
    class Connection:
        def __init__(self, host, port, timeout, context):
            assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
        def request(self, method, path): assert (method, path) == ("GET", "/api/health")
        def getresponse(self): return SimpleNamespace(status=200, read=lambda n: b'{"runner":{"ready":true}}')
        def close(self): pass
    monkeypatch.setattr(switch.http.client, "HTTPSConnection", Connection)
    switch.public_tls("https://arena.test")


def test_plan_digest_is_independent_of_windows_newlines():
    plan = {"format": 1, "path": "windows-path", "volumes": {"a": "b"}}
    lf = json.dumps(plan, indent=2)
    assert backup.plan_digest(json.loads(lf)) == backup.plan_digest(json.loads(lf.replace("\n", "\r\n")))


def test_two_bundles_for_same_site_cannot_switch_concurrently(tmp_path):
    from backend.writer_lock import WriterAlreadyRunning
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "plan.json").write_text(json.dumps({"project": "unit-exclusive-test", "engine": "qa"}))
    a, b = switch.Site(tmp_path / "a"), switch.Site(tmp_path / "b")
    with a.exclusive():
        with pytest.raises(WriterAlreadyRunning):
            with b.exclusive(): pass


def test_local_sandbox_alias_keeps_the_existing_sandbox_runtime(monkeypatch):
    from backend.sandbox_client import SandboxRunner
    monkeypatch.setenv("ARENA_RUNNER", "local_sandbox")
    monkeypatch.setenv("ARENA_RUNNER_TOKEN", "unit-local-controller-token-" * 2)
    runner = configured_runner()
    assert isinstance(runner, SandboxRunner) and runner.mode == "sandbox"


def test_docker_failures_cannot_echo_expanded_secrets(monkeypatch):
    monkeypatch.setattr(switch.subprocess, "run", lambda *a, **kw:
        SimpleNamespace(returncode=1, stdout="secret-model", stderr="secret-password"))
    with pytest.raises(RuntimeError) as error:
        switch.run(["docker", "compose", "config"])
    assert "secret-model" not in str(error.value) and "secret-password" not in str(error.value)


def test_startup_cannot_reuse_previous_process_ready_status(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    site = object.__new__(switch.Site)
    site.compose = lambda *args: "qa-container"
    started = 100
    monkeypatch.setattr(switch, "run", lambda args: json.dumps([{"State": {
        "StartedAt": datetime.fromtimestamp(started, timezone.utc).isoformat()}}]))
    acknowledgements = iter([state(time=99), state(time=101)])
    site.control = lambda *args: next(acknowledgements)
    monkeypatch.setattr(switch.time, "sleep", lambda seconds: None)
    assert site.wait_ready("local")["time"] == 101
