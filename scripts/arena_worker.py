"""Stable, cross-platform commands for the existing NEON ARENA Remote Worker.

This compatibility tool deliberately retains the deployed Docker Compose
project and volumes. It never creates a second project or modifies AWS.
"""
import argparse
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "neon-b1-worker"
ENV = ROOT / ".b1-pilot" / "worker.env"
COMPOSE = ROOT / "compose.remote-worker.yaml"
ACTIONS = {
    "start": ("up", "-d", "--build", "--wait"),
    "status": ("ps",),
    "stop-agent": ("stop", "agent"),
    "start-agent": ("start", "agent"),
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=tuple(ACTIONS))
    args = parser.parse_args(argv)
    if not ENV.is_file() or ENV.is_symlink():
        parser.exit(1, "BLOCKED: private Worker config missing; run setup_remote_worker.py first.\n")
    command = ["docker", "compose", "--env-file", str(ENV), "-p", PROJECT,
               "-f", str(COMPOSE), *ACTIONS[args.action]]
    try:
        result = subprocess.run(command, cwd=ROOT, check=False)
    except FileNotFoundError:
        parser.exit(1, "BLOCKED: Docker CLI missing. Install and start Docker first.\n")
    if result.returncode:
        parser.exit(result.returncode, "BLOCKED: Worker command failed; verify Docker and private config.\n")


if __name__ == "__main__":
    main()
