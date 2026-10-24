"""Extended B1 QA safety checks; no Docker Engine or browser is started."""
import ast
import json
from types import SimpleNamespace

import pytest

from scripts import check_b1_real_world_qa as qa


@pytest.mark.parametrize("endpoint", ["tcp://localhost:2375", "ssh://staging", "https://docker.example"])
def test_remote_docker_endpoint_is_rejected_before_engine_access(monkeypatch, endpoint):
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    calls = []

    def docker(*args):
        calls.append(args)
        if args == ("context", "show"):
            return "qa-context\n"
        if args == ("context", "inspect", "qa-context"):
            return json.dumps([{"Endpoints": {"docker": {"Host": endpoint}}}])
        pytest.fail("Remote Docker Engine must not be contacted")

    monkeypatch.setattr(qa, "docker", docker)
    with pytest.raises(RuntimeError, match="non-local Docker Engine"):
        qa.require_local_engine()
    assert len(calls) == 2


@pytest.mark.parametrize("endpoint", ["npipe:////./pipe/dockerDesktopLinuxEngine", "unix:///var/run/docker.sock"])
def test_local_linux_docker_engine_is_accepted(monkeypatch, endpoint):
    monkeypatch.delenv("DOCKER_HOST", raising=False)

    def docker(*args):
        if args == ("context", "show"):
            return "qa-context\n"
        if args[0] == "context":
            return json.dumps([{"Endpoints": {"docker": {"Host": endpoint}}}])
        return json.dumps({"Os": "linux"})

    monkeypatch.setattr(qa, "docker", docker)
    assert qa.require_local_engine() == "qa-context"


def test_docker_host_override_cannot_select_a_remote_engine(monkeypatch):
    monkeypatch.setenv("DOCKER_HOST", "tcp://remote.invalid:2375")
    monkeypatch.setattr(qa, "docker", lambda *args: "qa-context" if args == ("context", "show")
                        else json.dumps([{"Endpoints": {"docker": {"Host": "unix:///var/run/docker.sock"}}}]))
    with pytest.raises(RuntimeError, match="non-local Docker Engine"):
        qa.require_local_engine()


@pytest.mark.parametrize("failure", ["cleanup_error", "remaining_volume", "browser_failure"])
def test_failed_cleanup_or_browser_never_returns_success_even_after_ui_return(tmp_path, monkeypatch, failure):
    cleaned, calls = [], []

    def clean(project):
        cleaned.append(project)
        if failure == "cleanup_error" and project.endswith("worker"):
            raise RuntimeError("simulated cleanup failure")

    stacks = [SimpleNamespace(project="neon-b1-qa-worker", clean=lambda: clean("neon-b1-qa-worker")),
              SimpleNamespace(project="neon-b1-qa-cloud", clean=lambda: clean("neon-b1-qa-cloud"))]

    def docker(*args):
        calls.append(args)
        assert args[-2] == "--filter" and args[-1].startswith("label=com.docker.compose.project=neon-b1-qa-")
        return "remaining-qa-volume\n" if failure == "remaining_volume" and args[:2] == ("volume", "ls") else ""

    monkeypatch.setattr(qa, "docker", docker)
    report = {"cases": {"browser_ui": {"status": "FAIL" if failure == "browser_failure" else "PASS"}}}

    def early_ui_return():
        try:
            return
        finally:
            qa.finalize_report(tmp_path, report, stacks)

    with pytest.raises(SystemExit) as error:
        early_ui_return()
    assert error.value.code == 1
    assert cleaned == [s.project for s in stacks]
    assert calls
    assert json.loads((tmp_path / "extended-results.json").read_text())["status"] == "FAIL"


def test_clean_qa_reports_success(tmp_path, monkeypatch):
    monkeypatch.setattr(qa, "docker", lambda *args: "")
    stack = SimpleNamespace(project="neon-b1-cloud-qa-abcdef1234", clean=lambda: None)
    report = {"cases": {"browser_ui": {"status": "PASS"}}}
    qa.finalize_report(tmp_path, report, [stack])
    assert report["status"] == "PASS"
    assert report["cleanup"][stack.project] == "PASS"


def test_container_failures_do_not_disclose_arbitrary_output():
    worker = SimpleNamespace(compose=lambda *args, **kwargs: SimpleNamespace(
        returncode=1, stdout="private stdout sentinel", stderr="private stderr sentinel"))
    with pytest.raises(RuntimeError, match="client failed: setup") as error:
        qa.client(worker, "setup", "runtime-only-password")
    assert "sentinel" not in str(error.value)
    assert "password" not in str(error.value)


def test_embedded_acceptance_driver_parses():
    ast.parse(qa.CLIENT)
