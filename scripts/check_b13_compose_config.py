"""Read-only Compose acceptance using synthetic private settings, no Engine IO.

Checks the actual repository file order and exact neon-arena resource names.
Never starts a container, reads the operator .env or mounts an existing volume.
"""
import json
import os
from pathlib import Path
import secrets
import subprocess

try:
    from . import runner_switch as switch
except ImportError:
    import runner_switch as switch


def main():
    root = Path(__file__).resolve().parents[1]
    folder = root / ".runner-switch" / ("qa-compose-config-" + secrets.token_hex(5))
    folder.mkdir(parents=True, mode=0o700)
    env = {key: value for key, value in os.environ.items() if not key.startswith("ARENA_")}
    env.update(ARENA_RUNNER_TOKEN=secrets.token_hex(32), ARENA_PUBLIC_DOMAIN="qa-public.example.test",
               ARENA_PROXY_SECRET=secrets.token_hex(32), ARENA_ADMIN_TOTP_REQUIRED="0",
               ARENA_PUBLIC_ADMIN_PASSWORD_ONLY="1", ARENA_SELF_REGISTRATION="1",
               ARENA_PUBLIC_USERNAME_SIGNUP="1")
    override = folder / "compose.override.json"
    switch.private_json(override, {"services": {"arena": {"environment": {
        "ARENA_SMTP_PASSWORD": "qa-literal-$FOO-${BAR}-$$"}}}}, compose=True)
    command = ["docker", "compose", "--env-file", str(root / ".env.example"), "-p", "neon-arena"]
    for path in (root / "compose.yaml", override, root / "compose.public.yaml"):
        command += ["-f", str(path)]
    def resolve(command):
        result = subprocess.run(command + ["config", "--format", "json"], env=env,
                                capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError("QA Compose config failed; raw output suppressed")
        return switch.literal(json.loads(result.stdout), decode=True)
    local = resolve(command)
    remote = switch.remote_model(local, secrets.token_hex(32))
    switch.private_json(folder / "remote.json", remote, compose=True)
    (folder / "empty.env").touch(mode=0o600)
    assert resolve(switch.compose_command(folder / "remote.json", "neon-arena")) == remote
    assert switch.volume_map(local) == {
        "arena:/app/data": "neon-arena_arena_data", "arena:/app/uploads": "neon-arena_arena_uploads",
        "controller:/artifacts": "neon-arena_arena_artifacts", "gateway:/data": "neon-arena_caddy_data",
        "gateway:/config": "neon-arena_caddy_config"}
    current = remote["services"]["arena"]["environment"]
    assert current["ARENA_ADMIN_TOTP_REQUIRED"] == "0" and current["ARENA_PUBLIC_ADMIN_PASSWORD_ONLY"] == "1"
    assert current["ARENA_SELF_REGISTRATION"] == "1" and current["ARENA_PUBLIC_USERNAME_SIGNUP"] == "1"
    assert current["ARENA_SMTP_PASSWORD"] == "qa-literal-$FOO-${BAR}-$$"
    assert not remote["services"]["arena"].get("ports")
    assert remote["services"]["gateway"]["ports"] == local["services"]["gateway"]["ports"]
    assert "ARENA_RUNNER_TOKEN" not in current and "ARENA_CONTROLLER_URL" not in current
    print("PASS actual base + synthetic private override + public order; same project/volumes/auth/Caddy, remote-only services and literal dollar round trip; zero containers started")


if __name__ == "__main__":
    main()
