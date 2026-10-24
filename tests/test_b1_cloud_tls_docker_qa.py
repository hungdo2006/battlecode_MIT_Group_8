"""B1 two-stack HTTPS Docker QA configuration and release-boundary tests."""
import ast
import json

import pytest

from scripts.check_b1_cloud_tls_docker import (
    CADDY, CLOUD_IMAGE, DRIVER, CHECK_HEALTH, HOSTNAME, WORKER_IMAGES,
    env_without_operator_secrets, make_cloud_config, make_worker_override,
    project_names,
)


def test_qa_cloud_never_publishes_ports_or_uses_pc_docker_socket(tmp_path):
    cloud, worker = project_names("abcdef1234")
    assert cloud != worker
    config = make_cloud_config(tmp_path, cloud, cloud + "_transport",
                               "t" * 64, "g" * 64)
    data = json.loads(config.read_text(encoding="utf-8"))
    assert set(data["services"]) == {"arena", "gateway"}
    arena = data["services"]["arena"]
    gateway = data["services"]["gateway"]
    assert arena["environment"]["ARENA_RUNNER"] == "remote_sandbox"
    assert arena["environment"]["ARENA_ACCOUNT_ONLY"] == "1"
    assert arena["environment"]["ARENA_PUBLIC_GATEWAY"] == "1"
    assert arena["environment"]["ARENA_AUTH_ALLOW_HTTP"] == "0"
    assert arena["environment"]["ARENA_ALLOWED_HOSTS"] == HOSTNAME
    assert arena["environment"]["ARENA_AUTH_ORIGINS"] == "https://" + HOSTNAME
    assert "ARENA_RUNNER_TOKEN" not in arena["environment"]
    assert "ports" not in arena and "ports" not in gateway
    assert "transport" not in arena["networks"]
    assert "cloud_private" in gateway["networks"]
    assert gateway["networks"]["transport"]["aliases"] == [HOSTNAME]
    assert data["networks"]["cloud_private"]["internal"] is True
    for service in (arena, gateway):
        assert not any("/var/run/docker.sock" in x for x in service.get("volumes", []))
    assert arena["image"] == CLOUD_IMAGE


def test_qa_agent_uses_ephemeral_issuer_not_insecure_tls(tmp_path):
    transport = "neon-b1-cloud-qa-abcdef1234_transport"
    cert = tmp_path / "test-root.crt"
    config = make_worker_override(tmp_path, transport, cert)
    data = json.loads(config.read_text(encoding="utf-8"))
    agent = data["services"]["agent"]
    assert data["networks"]["transport"]["external"] is True
    assert agent["environment"]["SSL_CERT_FILE"] == "/certs/b1-root.crt"
    assert len(agent["networks"]) == 3
    assert agent["volumes"] == [str(cert) + ":/certs/b1-root.crt:ro"]
    assert not any("docker.sock" in x for x in agent["volumes"])
    assert data["services"]["controller"]["environment"]["SANDBOX_IMAGE"] == WORKER_IMAGES["bot-image"]
    assert "tls internal" in CADDY
    assert "reverse_proxy arena:8000" in CADDY
    assert "X-Arena-Proxy-Secret {$ARENA_PROXY_SECRET}" in CADDY
    assert "CERT_NONE" not in DRIVER
    assert "verify=False" not in DRIVER


def test_qa_embedded_remote_clients_are_valid_python():
    ast.parse(DRIVER)
    ast.parse(CHECK_HEALTH)


def test_qa_https_driver_checks_real_official_match_and_replay():
    for expected in (
        "/api/health", "remote-outbound", "/api/player/bots",
        "/api/admin/team-tournaments", "/api/admin/official-matches/",
        "replay", "tls_verified", "b1_https_e2e",
    ):
        assert expected in DRIVER


def test_qa_scrubs_existing_secrets(monkeypatch):
    monkeypatch.setenv("ARENA_RUNNER_TOKEN", "production-pc-only-secret")
    monkeypatch.setenv("ARENA_PROXY_SECRET", "production-gateway-secret")
    monkeypatch.setenv("ARENA_ADMIN_CODE", "production-admin-code")
    monkeypatch.setenv("SANDBOX_NAMESPACE", "prod-bots")
    env = env_without_operator_secrets()
    assert "ARENA_RUNNER_TOKEN" not in env
    assert "ARENA_PROXY_SECRET" not in env
    assert "ARENA_ADMIN_CODE" not in env
    assert "SANDBOX_NAMESPACE" not in env


@pytest.mark.parametrize("bad", ("", "NOTHEX1234", "bad-name", "../abc", "a" * 12))
def test_qa_rejects_misnamed_projects(bad):
    with pytest.raises(ValueError, match="invalid QA project"):
        project_names(bad)
