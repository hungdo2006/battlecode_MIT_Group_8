"""B1.4 pilot non-destructive boundaries. No Docker Engine or EC2 required."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import b1_ec2_pilot as pilot


def models():
    orig = {"name": pilot.OLD_PROJECT,
        "services": {
            "arena": {"environment": {"ARENA_RUNNER": "sandbox"}, "ports": []},
            "controller": {}, "bot-image": {},
            "gateway": {"ports": [
                {"target": a, "published": str(a), "protocol": protocol}
                for a, protocol in ((80, "tcp"), (443, "tcp"), (443, "udp"))]},
        },
        "volumes": {str(i): {"name": name} for i, name in enumerate(sorted(pilot.OLD_VOLUMES))}}
    cloud = {"name": pilot.PILOT_PROJECT,
        "services": {"arena": {
            "environment": {"ARENA_RUNNER": "remote_sandbox", "ARENA_ACCOUNT_AUTH": "1",
                "ARENA_ACCOUNT_ONLY": "1", "ARENA_PUBLIC_GATEWAY": "1",
                "ARENA_ADMIN_TOTP_REQUIRED": "0", "ARENA_AUTH_ALLOW_HTTP": "0",
                "ARENA_PUBLIC_ADMIN_PASSWORD_ONLY": "1",
                "ARENA_ALLOWED_HOSTS": pilot.DOMAIN,
                "ARENA_AUTH_ORIGINS": "https://" + pilot.DOMAIN,
                "ARENA_REMOTE_RUNNER_KEY": "r" * 64,
                "ARENA_PROXY_SECRET": "p" * 64,
            }, "volumes": [{"type": "volume", "source": "a", "target": "/app/data"}]},
            "gateway": {"environment": {"ARENA_PUBLIC_DOMAIN": pilot.DOMAIN},
                "ports": orig["services"]["gateway"]["ports"],
                "volumes": [{"type": "bind", "target": "/etc/caddy/Caddyfile",
                             "read_only": True, "source": "/repo/deploy/Caddyfile"}]}},
        "volumes": {"a": {"name": pilot.PILOT_PROJECT + "_pilot_data"},
                    "b": {"name": pilot.PILOT_PROJECT + "_pilot_uploads"},
                    "c": {"name": pilot.PILOT_PROJECT + "_pilot_caddy_data"},
                    "d": {"name": pilot.PILOT_PROJECT + "_pilot_caddy_config"}},
        "networks": {"ingress_private": {"internal": True}}}
    return orig, cloud


def test_correct_isolated_roles_are_accepted():
    pilot.validate_models(*models())


@pytest.mark.parametrize("change", [
    lambda old, cloud: cloud["volumes"]["a"].update(name="neon-arena_arena_data"),
    lambda old, cloud: cloud["services"]["arena"]["environment"].update(ARENA_RUNNER="sandbox"),
    lambda old, cloud: cloud["services"]["arena"]["environment"].update(ARENA_RUNNER_TOKEN="secret"),
    lambda old, cloud: cloud["services"]["arena"]["environment"].update(ARENA_ADMIN_TOTP_REQUIRED="1"),
    lambda old, cloud: cloud["services"]["arena"]["environment"].update(ARENA_PUBLIC_ADMIN_PASSWORD_ONLY="0"),
    lambda old, cloud: cloud["services"]["arena"]["environment"].update(ARENA_ALLOWED_HOSTS="prod.example.org"),
    lambda old, cloud: cloud["services"]["arena"]["environment"].update(ARENA_REMOTE_RUNNER_KEY="short"),
    lambda old, cloud: cloud["services"]["arena"].update(ports=[{"published": "8000", "target": 8000}]),
    lambda old, cloud: cloud["services"]["arena"].update(depends_on={"controller": {}}),
    lambda old, cloud: cloud["services"]["gateway"]["ports"].append({"target": 9000, "published": "9000"}),
    lambda old, cloud: cloud["services"]["gateway"]["volumes"].append({
        "type": "bind", "target": "/var/run/docker.sock", "source": "/var/run/docker.sock"}),
    lambda old, cloud: cloud["networks"]["ingress_private"].update(internal=False),
    lambda old, cloud: cloud["services"].update(controller={}),
])
def test_insecure_or_nonisolated_cloud_is_blocked(change):
    old, cloud = models()
    change(old, cloud)
    with pytest.raises(pilot.Blocked):
        pilot.validate_models(old, cloud)


def test_original_compose_files_are_explicit_and_ordered(tmp_path):
    old, cloud = pilot.commands(tmp_path / "pilot", tmp_path / "old", tmp_path / "pilot/.b1-pilot/cloud.env")
    assert old[-6:] == [
        "-f", str(tmp_path / "old/compose.yaml"),
        "-f", str(tmp_path / "old/compose.override.yaml"),
        "-f", str(tmp_path / "old/compose.public.yaml")]
    assert cloud[cloud.index("-p") + 1] == pilot.PILOT_PROJECT
    assert cloud[-1].endswith("compose.ec2-pilot.yaml")


def test_cutover_refuses_without_operator_acknowledgement(monkeypatch):
    monkeypatch.setattr(pilot, "context", lambda _: pytest.fail("no inspection before approval"))
    with pytest.raises(pilot.Blocked, match="DOWNTIME"):
        pilot.switch_to_pilot(SimpleNamespace(confirm_downtime=False))


def test_cutover_refuses_missing_prepare_or_wrong_live_port_owner(tmp_path, monkeypatch):
    folder = tmp_path / ".b1-pilot"
    folder.mkdir()
    monkeypatch.setattr(pilot, "context", lambda _: (tmp_path, tmp_path / "old", ["old"], ["pilot"]))
    monkeypatch.setattr(pilot, "docker", lambda *a, **kw: pytest.fail("no services may change"))
    with pytest.raises(pilot.Blocked, match="PREPARE"):
        pilot.switch_to_pilot(SimpleNamespace(confirm_downtime=True))
    (folder / "prepared").write_text("yes")
    monkeypatch.setattr(pilot, "is_running", lambda command, role, root: command == ["old"])
    monkeypatch.setattr(pilot, "current_containers", lambda root: {"unrelated"})
    with pytest.raises(pilot.Blocked, match="GATEWAY"):
        pilot.switch_to_pilot(SimpleNamespace(confirm_downtime=True))


def test_cutover_and_failure_rollback_touch_only_allowlisted_services(tmp_path, monkeypatch):
    folder = tmp_path / ".b1-pilot"
    folder.mkdir()
    (folder / "prepared").write_text("yes")
    monkeypatch.setattr(pilot, "context", lambda _: (tmp_path, tmp_path / "old", ["old"], ["pilot"]))
    monkeypatch.setattr(pilot, "is_running", lambda command, role, root: command == ["old"])
    monkeypatch.setattr(pilot, "current_containers", lambda root: {pilot.OLD_PROJECT})
    calls = []
    def docker(command, root, interactive):
        calls.append(command)
        if command[:3] == ["pilot", "up", "-d"]:
            raise pilot.Blocked("test start failure")
        assert not any(a in ("down", "rm", "prune", "-v") for a in command)
        return ""
    monkeypatch.setattr(pilot, "docker", docker)
    with pytest.raises(pilot.Blocked, match="ORIGINAL_RESTARTED"):
        pilot.switch_to_pilot(SimpleNamespace(confirm_downtime=True))
    assert calls == [
        ["old", "stop", "gateway", "arena", "controller"],
        ["pilot", "up", "-d", "--no-build"],
        ["pilot", "stop", "gateway", "arena"],
        ["old", "up", "-d", "--no-build", "--wait"],
    ]


def test_rollback_requires_confirmation_and_never_removes_volumes(tmp_path, monkeypatch):
    with pytest.raises(pilot.Blocked, match="EXPLICIT_ROLLBACK"):
        pilot.rollback(SimpleNamespace(confirm_rollback=False))
    monkeypatch.setattr(pilot, "context", lambda _: (tmp_path, tmp_path / "old", ["old"], ["pilot"]))
    monkeypatch.setattr(pilot, "is_running", lambda command, role, root: command == ["pilot"])
    actions = []
    monkeypatch.setattr(pilot, "docker", lambda command, root, interactive: actions.append(command))
    pilot.rollback(SimpleNamespace(confirm_rollback=True))
    assert actions == [["pilot", "stop", "gateway", "arena"], ["old", "up", "-d", "--no-build", "--wait"]]
