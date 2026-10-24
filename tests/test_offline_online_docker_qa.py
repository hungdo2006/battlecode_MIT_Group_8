"""No-Docker safety checks for the two-stack Phase A acceptance runner."""
import json

import pytest

from scripts.check_offline_online_docker import QAStack, qa_environment, qa_project


def test_two_compose_projects_and_all_ports_are_private(tmp_path):
    secret = "test-only-signing-key-" + "x" * 48
    source = QAStack("off", "0123456789", secret, tmp_path)
    target = QAStack("on", "0123456789", secret, tmp_path)
    assert source.project != target.project
    assert source.url.startswith("http://127.0.0.1:")
    assert target.url.startswith("http://127.0.0.1:")
    assert source.env["ARENA_AUTH_ORIGINS"] == source.url
    assert target.env["ARENA_AUTH_ORIGINS"] == target.url
    assert source.env["ARENA_RUNNER_TOKEN"] != target.env["ARENA_RUNNER_TOKEN"]
    assert source.env["ARENA_OFFLINE_RESULTS_KEY"] == target.env["ARENA_OFFLINE_RESULTS_KEY"]
    assert source.env["ARENA_OFFLINE_SITE_ID"] and not target.env["ARENA_OFFLINE_SITE_ID"]
    assert source.env["SANDBOX_NAMESPACE"] != target.env["SANDBOX_NAMESPACE"]
    for stack in (source, target):
        assert stack.env["ARENA_BIND_IP"] == "127.0.0.1"
        assert stack.env["ARENA_ACCOUNT_ONLY"] == "1"
        assert stack.env["ARENA_AUTH_ALLOW_HTTP"] == "1"
        assert stack.env["ARENA_PUBLIC_GATEWAY"] == "0"
        assert stack.env["ARENA_ADMIN_TOTP_REQUIRED"] == "0"
        config = json.loads(stack.override.read_text())
        assert set(config["services"]) == {"arena", "controller", "bot-image"}
        assert config["services"]["arena"]["image"] == "neon-arena-qa-arena:local"
        assert (config["services"]["controller"]["environment"]["SANDBOX_IMAGE"]
                == config["services"]["bot-image"]["image"])


@pytest.mark.parametrize("role,nonce", [
    ("production", "0123456789"), ("off", "bad-word"),
    ("on", ""), ("off", "x" * 11),
])
def test_qa_project_rejects_unknown_identifiers(role, nonce):
    with pytest.raises(ValueError):
        qa_project(role, nonce)


def test_qa_environment_cannot_be_pointed_to_production():
    with pytest.raises(ValueError):
        qa_environment("off", 8000, "neon-arena", "x" * 48)
    with pytest.raises(ValueError):
        qa_environment("on", 0, "neon-phase-a-on-0123456789", "x" * 48)
    with pytest.raises(ValueError):
        qa_environment("on", 45678, "neon-phase-a-on-0123456789", "too-short")


def test_qa_never_inherits_operator_arena_secrets(monkeypatch):
    monkeypatch.setenv("ARENA_SMTP_PASSWORD", "real-host-smtp-secret-never-propagate")
    monkeypatch.setenv("ARENA_PROXY_SECRET", "real-host-gateway-secret-never-propagate")
    monkeypatch.setenv("ARENA_ADMIN_CODE", "real-host-admin-code-never-propagate")
    env = qa_environment("off", 45000, "neon-phase-a-off-0123456789", "x" * 48)
    assert "ARENA_SMTP_PASSWORD" not in env
    assert "ARENA_PROXY_SECRET" not in env
    assert env["ARENA_ADMIN_CODE"] == ""
