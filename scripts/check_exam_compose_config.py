"""Validate isolated exam Compose with synthetic secrets; never starts containers."""
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix="neon-exam-compose-") as folder:
        env = Path(folder) / "exam.env"
        env.write_text("\n".join((
            "ARENA_PUBLIC_DOMAIN=192.168.10.10",
            "ARENA_LAN_BIND_IP=192.168.10.10",
            "ARENA_RUNNER_TOKEN=" + "t" * 64,
            "ARENA_PROXY_SECRET=" + "p" * 64,
            "DOCKER_SOCKET_GID=0",
            "",
        )), encoding="utf-8")
        command = ["docker", "compose", "--env-file", str(env),
                   "-f", str(ROOT / "compose.yaml"), "-f", str(ROOT / "compose.exam.yaml"),
                   "config", "--format", "json"]
        resolved = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=True)
        config = json.loads(resolved.stdout)
        arena = config["services"]["arena"]
        envs = arena["environment"]
        assert envs["ARENA_ACCOUNT_AUTH"] == envs["ARENA_ACCOUNT_ONLY"] == "1"
        assert envs["ARENA_ADMIN_TOTP_REQUIRED"] == "0"
        assert envs["ARENA_PUBLIC_ADMIN_PASSWORD_ONLY"] == "1"
        assert envs["ARENA_SELF_REGISTRATION"] == envs["ARENA_PUBLIC_USERNAME_SIGNUP"] == "1"
        assert envs["ARENA_AUTH_ORIGINS"] == "https://192.168.10.10"
        assert not arena.get("ports")
        assert config["services"]["gateway"]["ports"][0]["host_ip"] == "192.168.10.10"
        assert config["networks"]["ingress_private"]["internal"] is True
        assert config["networks"]["runner_private"]["internal"] is True
        assert not config["services"]["controller"].get("ports")
    print("PASS: Offline LAN account-only password auth and HTTPS Compose configuration")


if __name__ == "__main__":
    main()
