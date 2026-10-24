"""No-Docker smoke for the real B1.4 pilot and B1.5 local Compose models.

Only resolves configs using synthetic secrets. Does not create volumes,
start containers, reach AWS or interact with the live website.
"""
import json
from pathlib import Path
import subprocess
import tempfile

from scripts.b15_pilot_runner import matching_remote, project_identity
from scripts.runner_switch import remote_model, volume_map, literal

ROOT = Path(__file__).resolve().parents[1]


def resolve(name, env):
    command = ["docker", "compose", "--env-file", str(env), "-p", "neon-b1-ec2-pilot",
               "-f", str(ROOT / name), "config", "--format", "json"]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=True)
    return literal(json.loads(result.stdout), decode=True)


def main():
    with tempfile.TemporaryDirectory(prefix="neon-b15-config-") as folder:
        cloud_env = Path(folder) / "cloud.env"
        local_env = Path(folder) / "local.env"
        cloud_env.write_text(
            "ARENA_PUBLIC_DOMAIN=traitimcodon.duckdns.org\n"
            + "ARENA_REMOTE_RUNNER_KEY=" + "r" * 64 + "\n"
            + "ARENA_PROXY_SECRET=" + "p" * 64 + "\n", encoding="utf-8")
        local_env.write_text(cloud_env.read_text(encoding="utf-8")
                             + "ARENA_RUNNER_TOKEN=" + "t" * 64 + "\n", encoding="utf-8")
        cloud = resolve("compose.ec2-pilot.yaml", cloud_env)
        local = resolve("compose.ec2-pilot.local.yaml", local_env)
        project_identity(cloud)
        remote = remote_model(local, "r" * 64)
        matching_remote(cloud, remote)
        identities = volume_map(local)
        assert identities["arena:/app/data"] == identities["gateway:/data"].replace(
            "pilot_caddy_data", "pilot_data")
        assert identities["arena:/app/uploads"] == "neon-b1-ec2-pilot_pilot_uploads"
        assert identities["controller:/artifacts"] == "neon-b1-ec2-pilot_local_artifacts"
        assert not local["services"]["arena"].get("ports")
        assert not remote["services"]["arena"].get("depends_on")
        assert not any("docker.sock" in str(m) for name in ("arena", "gateway")
                       for m in remote["services"][name].get("volumes", []))
        assert "ARENA_RUNNER_TOKEN" not in remote["services"]["arena"]["environment"]
        assert set(remote["services"]) == {"arena", "gateway"}
        assert set(local["services"]) == {"arena", "controller", "bot-image", "gateway"}
    print("PASS: B1.5 local/remote models preserve the same B1.4 HTTPS and data volumes")


if __name__ == "__main__":
    main()
