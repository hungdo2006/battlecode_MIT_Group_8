"""Create a private remote worker config without echoing credentials."""
import argparse
import getpass
import os
from pathlib import Path
import re
import secrets
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SERVER = "https://traitimcodon.duckdns.org"


def server_url(value):
    url = urlsplit(value.strip())
    if (url.scheme != "https" or not url.hostname or url.username or url.password
            or url.path or url.query or url.fragment or url.port not in (None, 443)):
        raise ValueError("Use an HTTPS server origin only (e.g. https://example.com)")
    return value.strip().rstrip("/")


def machine_key(value):
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,}", value):
        raise ValueError("The EC2 machine key must be 32+ URL-safe characters; do not invent a new value")
    return value


def compose_values(server, shared_key, controller_key, gid, namespace="neon-school-worker"):
    server, shared_key = server_url(server), machine_key(shared_key)
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,}", controller_key):
        raise ValueError("Controller token must have 32+ URL-safe characters")
    if not str(gid).isdigit():
        raise ValueError("Invalid Docker socket GID")
    if not re.fullmatch(r"[a-z0-9_-]{3,64}", namespace):
        raise ValueError("Invalid sandbox namespace")
    return "\n".join((
        "ARENA_REMOTE_SERVER_URL=" + server,
        "ARENA_REMOTE_RUNNER_KEY=" + shared_key,
        "ARENA_RUNNER_TOKEN=" + controller_key,
        "SANDBOX_NAMESPACE=" + namespace,
        "DOCKER_SOCKET_GID=" + str(gid),
        "",
    ))


def main(argv=None):
    parser = argparse.ArgumentParser(description="First-time Remote Worker setup (no AWS modifications)")
    parser.add_argument("--server", default=DEFAULT_SERVER, help="HTTPS origin of the existing AWS website")
    args = parser.parse_args(argv)
    try:
        server_url(args.server)
        if not sys.stdin.isatty():
            raise ValueError("Interactive terminal required to enter the machine key privately")
        target = ROOT / ".b1-pilot" / "worker.env"
        if target.exists() or target.is_symlink():
            raise ValueError("worker.env already exists; refusing to overwrite an existing Worker identity")
        secret = getpass.getpass("Enter the EXISTING AWS remote machine key (input hidden): ")
        gid = (os.stat("/var/run/docker.sock").st_gid
               if os.name != "nt" and Path("/var/run/docker.sock").exists() else 0)
        config = compose_values(args.server, secret, secrets.token_urlsafe(48), gid)
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8", newline="\n") as stream:
            if os.name != "nt":
                os.chmod(target, 0o600)
            stream.write(config)
    except (ValueError, OSError, EOFError, KeyboardInterrupt) as exc:
        parser.exit(1, f"Worker setup refused: {exc}\n")
    print("Private worker.env created. Start Docker and run the Remote Worker Compose command.")
    print("Do not start another agent with the same AWS machine key.")


if __name__ == "__main__":
    main()
