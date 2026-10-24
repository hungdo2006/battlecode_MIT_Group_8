"""Read-only B1.4 Compose CI check; synthetic secrets, no Engine and no AWS."""
import json
import os
from pathlib import Path
import secrets
import subprocess

from scripts.b1_ec2_pilot import DOMAIN, PILOT_PROJECT, PILOT_VOLUMES, PILOT_SERVICES, ports


def main():
    root = Path(__file__).resolve().parents[1]
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("ARENA_", "SANDBOX_", "COMPOSE_"))}
    env.update(ARENA_PUBLIC_DOMAIN=DOMAIN, ARENA_REMOTE_RUNNER_KEY=secrets.token_hex(32),
               ARENA_PROXY_SECRET=secrets.token_hex(48))
    command = ["docker", "compose", "--env-file", str(root / ".env.example"),
               "-f", str(root / "compose.ec2-pilot.yaml"), "-p", PILOT_PROJECT,
               "config", "--format", "json"]
    result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("Pilot Compose resolution failed; raw output suppressed")
    conf = json.loads(result.stdout)
    assert conf["name"] == PILOT_PROJECT
    assert set(conf["services"]) == PILOT_SERVICES
    assert {v["name"] for v in conf["volumes"].values()} == PILOT_VOLUMES
    assert ports(conf["services"]["gateway"]) == {
        (80, 80, "tcp"), (443, 443, "tcp"), (443, 443, "udp")}
    arena = conf["services"]["arena"]
    assert arena["environment"]["ARENA_RUNNER"] == "remote_sandbox"
    assert arena["environment"]["ARENA_ADMIN_TOTP_REQUIRED"] == "1"
    assert arena["environment"]["ARENA_PUBLIC_ADMIN_PASSWORD_ONLY"] == "0"
    assert arena["environment"]["ARENA_AUTH_ORIGINS"] == "https://" + DOMAIN
    assert not arena.get("ports") and not arena.get("depends_on")
    assert all("docker.sock" not in str(s.get("volumes", [])) for s in conf["services"].values())
    assert "ARENA_RUNNER_TOKEN" not in arena["environment"]
    assert "ARENA_CONTROLLER_URL" not in arena["environment"]
    assert conf["networks"]["ingress_private"]["internal"] is True
    print("PASS B1.4 isolated fresh-data Cloud Compose; no containers started")


if __name__ == "__main__":
    main()
