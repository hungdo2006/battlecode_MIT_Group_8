"""Binary-safe backup of both Compose volumes on Windows and Linux.

Stop arena first for a consistent snapshot. This never deletes volumes or
overwrites an existing archive, and does not put .env into the backup.
"""
import argparse
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent.parent


def backup(output, project=None, environment=None):
    command = ["docker", "compose", "-f", str(ROOT / "compose.yaml")]
    if project:
        command += ["-p", project]
    running = subprocess.run(command + ["ps", "--status", "running", "-q", "arena"],
                             cwd=ROOT, env=environment, check=True, capture_output=True)
    if running.stdout.strip():
        raise RuntimeError("Stop arena first: docker compose stop arena (include -p if used).")
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    # stdout is a binary file, not PowerShell's text redirection pipeline.
    with output.open("xb") as archive:
        subprocess.run(command + ["run", "--rm", "--no-deps", "-T", "--entrypoint", "tar",
                                  "arena", "-czf", "-", "-C", "/app", "data", "uploads"],
                       cwd=ROOT, env=environment, stdout=archive, check=True)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="New .tar.gz archive path")
    parser.add_argument("--project", help="Compose project override, if you used -p")
    args = parser.parse_args()
    path = backup(args.output, args.project)
    print(f"Backup: {path} ({path.stat().st_size} bytes)")
