import json

import pytest

from scripts.check_docker import DockerCheck


def test_local_qa_ignores_inherited_all_interfaces_and_uses_separate_images(monkeypatch):
    monkeypatch.setenv('ARENA_BIND_IP', '0.0.0.0')
    qa = DockerCheck()
    try:
        assert qa.host == qa.env['ARENA_BIND_IP'] == '127.0.0.1'
        assert qa.env['ARENA_PORT'] == '0'
        config = json.loads(qa.override.read_text())['services']
        assert config['arena']['image'].startswith('neon-arena-qa-')
        assert config['controller']['environment']['SANDBOX_IMAGE'] == config['bot-image']['image']
    finally:
        qa.config_dir.cleanup()


def test_lan_qa_requires_explicit_interface():
    qa = DockerCheck('192.168.2.20')
    try:
        assert qa.env['ARENA_BIND_IP'] == qa.host == '192.168.2.20'
    finally:
        qa.config_dir.cleanup()
    for invalid in ('0.0.0.0', '8.8.8.8', '224.0.0.1', '::1', 'localhost'):
        with pytest.raises(ValueError):
            DockerCheck(invalid)


def test_docker_homepage_assertion_matches_current_shipped_landing():
    from pathlib import Path
    from scripts.check_docker import verify_homepage

    page = (Path(__file__).resolve().parents[1] / "frontend" / "index.html").read_text(encoding="utf-8")
    verify_homepage(page)

    with pytest.raises(AssertionError, match="login action"):
        verify_homepage(page.replace('id="landing-login"', 'id="deleted-login"'))
