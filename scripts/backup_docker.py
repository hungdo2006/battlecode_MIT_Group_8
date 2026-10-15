"""Binary-safe backup of application volumes and sandbox artifacts.

Stop arena first for a consistent snapshot. This never deletes volumes or
overwrites an existing archive, and does not put .env into the backup.
"""
import argparse
import json
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
    # Discover actual named volumes; do not assume a Compose project prefix.
    mounts = {}
    for service in ('arena', 'controller'):
        result = subprocess.run(command + ['ps', '-a', '-q', service], cwd=ROOT, env=environment,
                                capture_output=True, text=True)
        if result.returncode or not result.stdout.strip():
            continue
        record = json.loads(subprocess.run(['docker', 'inspect', result.stdout.strip()],
            env=environment, check=True, capture_output=True, text=True).stdout)[0]
        for mount in record['Mounts']:
            if mount['Type'] == 'volume' and mount['Destination'] in ('/app/data', '/app/uploads', '/artifacts'):
                destination = '/app/artifacts' if mount['Destination'] == '/artifacts' else mount['Destination']
                mounts[destination] = mount['Name']
    if not {'/app/data', '/app/uploads'} <= mounts.keys():
        raise RuntimeError('Application volumes not found. Stop containers, but do not down before backup.')
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    # stdout is a binary file, not PowerShell's text redirection pipeline.
    with output.open("xb") as archive:
        helper = ['docker', 'run', '--rm', '--network', 'none', '--read-only', '--cap-drop', 'ALL',
                  '--security-opt', 'no-new-privileges:true', '--memory', '128m', '--pids-limit', '16']
        for destination, name in sorted(mounts.items()):
            helper += ['--mount', f'type=volume,src={name},dst={destination},readonly']
        helper += ['--entrypoint', 'tar', 'neon-arena:4.0', '-czf', '-', '-C', '/app']
        helper += [Path(p).name for p in sorted(mounts)]
        subprocess.run(helper, cwd=ROOT, env=environment, stdout=archive, check=True)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="New .tar.gz archive path")
    parser.add_argument("--project", help="Compose project override, if you used -p")
    args = parser.parse_args()
    path = backup(args.output, args.project)
    print(f"Backup: {path} ({path.stat().st_size} bytes)")
