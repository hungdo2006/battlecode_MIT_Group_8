"""Checks for user-friendly setup helpers. No Docker or credentials needed."""
import pytest

from scripts.setup_exam_lan import lan_ip, prepare, setting
from scripts.setup_remote_worker import server_url, machine_key, compose_values


def test_exam_setup_uses_ip_and_preserves_existing_proxy_secret():
    source = ("ARENA_PUBLIC_DOMAIN=\nARENA_LAN_BIND_IP=\n"
              "ARENA_PROXY_SECRET=" + "x" * 64 + "\n")
    updated = prepare(source, "192.168.4.22")
    assert setting(updated, "ARENA_PUBLIC_DOMAIN") == "192.168.4.22"
    assert setting(updated, "ARENA_LAN_BIND_IP") == "192.168.4.22"
    assert setting(updated, "ARENA_PROXY_SECRET") == "x" * 64
    assert prepare(updated, "192.168.4.22") == updated
    assert len(setting(updated, "ARENA_OFFLINE_RESULTS_KEY")) >= 32


@pytest.mark.parametrize("ip", ["127.0.0.1", "8.8.8.8", "::1", "0.0.0.0", "x"])
def test_exam_setup_rejects_unusable_lan_ip(ip):
    with pytest.raises(ValueError):
        lan_ip(ip)


def test_exam_setup_refuses_repointing_existing_host():
    with pytest.raises(ValueError, match="Existing .env"):
        prepare("ARENA_PUBLIC_DOMAIN=192.168.1.3\n", "192.168.1.4")


def test_exam_setup_generates_proxy_secret_and_leaves_site_keys_unset():
    updated = prepare("ARENA_RUNNER_TOKEN=" + "t" * 64 + "\n", "10.10.5.6")
    assert len(setting(updated, "ARENA_PROXY_SECRET")) >= 48
    assert setting(updated, "ARENA_RUNNER_TOKEN") == "t" * 64
    assert len(setting(updated, "ARENA_OFFLINE_RESULTS_KEY")) >= 32
    assert setting(updated, "ARENA_OFFLINE_SITE_ID").startswith("exam-")


def test_worker_config_preserves_shared_key_and_separates_local_token():
    cloud_key, local_key = "a" * 64, "b" * 64
    config = compose_values("https://traitimcodon.duckdns.org", cloud_key, local_key, 999)
    assert "ARENA_REMOTE_RUNNER_KEY=" + cloud_key in config
    assert "ARENA_RUNNER_TOKEN=" + local_key in config
    assert "DOCKER_SOCKET_GID=999" in config
    assert "ARENA_REMOTE_SERVER_URL=https://traitimcodon.duckdns.org" in config


@pytest.mark.parametrize("url", ["http://example.com", "https://example.com/path", "https://example.com:8443"])
def test_worker_rejects_non_https_origin(url):
    with pytest.raises(ValueError):
        server_url(url)


def test_worker_rejects_weak_or_unsafe_shared_key():
    for key in ("short", "x" * 32 + " $"):
        with pytest.raises(ValueError):
            machine_key(key)
