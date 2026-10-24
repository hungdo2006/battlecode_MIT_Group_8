"""Unit safety checks for disposable PC worker Docker QA (no Docker required)."""
import ast
import json

import pytest

from scripts.check_remote_worker_docker import (
    EXERCISE_AGENT, QA_IMAGES, WorkerQA, isolated_env, qa_project,
)


def test_pc_worker_qa_is_random_and_not_production(tmp_path):
    smoke = WorkerQA(tmp_path, "abcdef1234")
    assert smoke.project == "neon-b1-worker-qa-abcdef1234"
    assert smoke.env["SANDBOX_NAMESPACE"].startswith(smoke.project)
    assert smoke.env["ARENA_REMOTE_SERVER_URL"] == "https://qa-disconnected.invalid"
    assert smoke.env["ARENA_RUNNER_TOKEN"] != smoke.env["ARENA_REMOTE_RUNNER_KEY"]
    assert len(smoke.env["ARENA_RUNNER_TOKEN"]) >= 32
    assert smoke.command[smoke.command.index("-p") + 1] == smoke.project
    override = json.loads((tmp_path / "worker-smoke.json").read_text(encoding="utf-8"))
    assert set(override["services"]) == {"bot-image", "controller", "agent"}
    assert override["services"]["controller"]["environment"]["SANDBOX_IMAGE"] == QA_IMAGES["bot-image"]
    assert override["services"]["controller"]["environment"]["SANDBOX_NAMESPACE"] == smoke.env["SANDBOX_NAMESPACE"]
    assert all("qa-" in image for image in QA_IMAGES.values())


@pytest.mark.parametrize("nonce", ["", "too-long-name", "outside", "ABCDEFGHIJ", "../etc/passwd"])
def test_worker_qa_rejects_uncontrolled_project_names(nonce):
    with pytest.raises(ValueError, match="QA identifier"):
        qa_project(nonce)


def test_worker_qa_does_not_inherit_existing_cloud_or_docker_secrets(monkeypatch):
    monkeypatch.setenv("ARENA_REMOTE_RUNNER_KEY", "production-cloud-secret-never-propagate")
    monkeypatch.setenv("ARENA_RUNNER_TOKEN", "production-controller-secret-never-propagate")
    monkeypatch.setenv("ARENA_SMTP_PASSWORD", "production-smtp-secret-never-propagate")
    monkeypatch.setenv("SANDBOX_NAMESPACE", "active-prod-bots")
    env = isolated_env("neon-b1-worker-qa-abcdef1234")
    assert env["ARENA_REMOTE_RUNNER_KEY"] != "production-cloud-secret-never-propagate"
    assert env["ARENA_RUNNER_TOKEN"] != "production-controller-secret-never-propagate"
    assert "ARENA_SMTP_PASSWORD" not in env
    assert env["SANDBOX_NAMESPACE"] == "neon-b1-worker-qa-abcdef1234-bots"


def test_agent_rpc_smoke_code_has_real_compile_and_runtime_path():
    parsed = ast.parse(EXERCISE_AGENT)
    assert parsed.body
    for expected in ("/health", "/owner", "/compile/", "/runtime/",
                     "/request", "/close/", "/release"):
        assert expected in EXERCISE_AGENT
    assert "real_docker_runtime" in EXERCISE_AGENT
