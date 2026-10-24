"""Complete cold site backup + non-destructive restore drill for B1.3.

No stopping/restarting/deleting services or volumes. Operator must drain and
stop arena/controller/gateway first. Backup contains secrets: protect its ACL.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess

try:
    from . import backup_docker, restore_docker
    from .runner_switch import Site, private_json, run, sha
    from .volume_snapshot import read_snapshot
except ImportError:
    import backup_docker, restore_docker
    from runner_switch import Site, private_json, run, sha
    from volume_snapshot import read_snapshot

ROLES = ("caddy_data", "caddy_config")
HELPER = Path(__file__).with_name("volume_snapshot.py").read_text(encoding="utf-8").split("if __name__ == '__main__':", 1)[0]


def plan_digest(plan):
    return hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def gateway_helper(volumes, image, restore=False):
    command = ["docker", "run", "--rm", "--pull", "never", "--log-driver", "none", "-i",
               "--network", "none", "--read-only", "--user", "0:0", "--cap-drop", "ALL",
               "--security-opt", "no-new-privileges:true", "--memory", "256m", "--pids-limit", "16"]
    for role, name in volumes.items():
        command += ["--mount", f"type=volume,src={name},dst=/snapshot/{role},volume-nocopy"
                    + ("" if restore else ",readonly")]
    suffix = "\nroles=('caddy_data','caddy_config')\nroots={r:Path('/snapshot')/r for r in roles}\n"
    suffix += ("read_snapshot(sys.stdin.buffer, roots, roles=roles)" if restore else
               "write_snapshot(roots, sys.stdout.buffer, {}, roles=roles)")
    return command + ["--entrypoint", "python", image, "-B", "-c", HELPER + suffix]


def binary_run(command, path, restore=False):
    with Path(path).open("rb" if restore else "xb") as target:
        kwargs = {"stdin": target, "stdout": subprocess.DEVNULL} if restore else {"stdout": target}
        result = subprocess.run(command, stderr=subprocess.PIPE, **kwargs)
        if result.returncode:
            raise RuntimeError("Backup/restore helper failed; no complete receipt issued")
        if not restore:
            target.flush()
            os.fsync(target.fileno())


def backup(site, directory):
    site.verify()
    backup_docker.assert_no_writers(site.plan["volumes"], None)
    local = site.model("local")
    # Current containers must use exactly the pinned images being backed up.
    for service in ("arena", "controller", "gateway"):
        ids = site.compose("local", "ps", "-a", "-q", service).split()
        if len(ids) != 1:
            raise ValueError("Missing original service for complete backup")
        record = json.loads(run(["docker", "inspect", ids[0]]))[0]
        if record["Image"] != local["services"][service]["image"]:
            raise ValueError("Running image differs from backup plan")
    directory = Path(directory).resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    backup_docker.backup(directory / "state.tar.gz", compose_command=site.command("local"))
    caddy_volumes = {"caddy_data": site.plan["volumes"]["gateway:/data"],
                     "caddy_config": site.plan["volumes"]["gateway:/config"]}
    binary_run(gateway_helper(caddy_volumes, local["services"]["arena"]["image"]), directory / "gateway.tar.gz")
    with (directory / "gateway.tar.gz").open("rb") as source:
        read_snapshot(source, roles=ROLES)
    binary_run(["docker", "image", "save", local["services"]["gateway"]["image"]], directory / "gateway.images.tar")
    protected = directory / "private"
    protected.mkdir(mode=0o700)
    private_files = {}
    # Includes exact input Compose/env/key/Caddyfile and generated full models.
    paths = [*site.plan["sources"], *map(str, site.directory.iterdir())]
    for index, value in enumerate(paths):
        path = Path(value)
        if not path.is_file() or path.is_symlink():
            raise ValueError("Only regular private configuration files may be backed up")
        target = protected / (str(index) + ".private")
        shutil.copyfile(path, target)
        os.chmod(target, 0o600)
        private_files[str(path)] = {"file": target.relative_to(directory).as_posix(), "sha256": sha(target)}
    backup_docker.assert_no_writers(site.plan["volumes"], None)
    receipt = {"format": 1, "plan_sha256": plan_digest(site.plan),
               "volumes": site.plan["volumes"], "private": private_files,
               "gateway_image": local["services"]["gateway"]["image"],
               "checksums": {name: sha(directory / name) for name in
                   ("state.tar.gz", "state.tar.gz.images.tar", "state.tar.gz.receipt.json",
                    "gateway.tar.gz", "gateway.images.tar")}}
    private_json(directory / "complete.json", receipt)
    return receipt


def verify_complete(directory, plan, *, require_drill=True):
    directory = Path(directory).resolve()
    receipt = json.loads((directory / "complete.json").read_text(encoding="utf-8"))
    if (receipt.get("format") != 1 or receipt["volumes"] != plan["volumes"]
            or receipt["plan_sha256"] != plan_digest(plan)):
        raise ValueError("Complete backup does not match this site plan")
    expected = {"state.tar.gz", "state.tar.gz.images.tar", "state.tar.gz.receipt.json",
                "gateway.tar.gz", "gateway.images.tar"}
    if set(receipt["checksums"]) != expected:
        raise ValueError("Incomplete backup inventory")
    for name, digest in receipt["checksums"].items():
        if sha(directory / name) != digest:
            raise ValueError("Backup checksum mismatch")
    for path, digest in plan["sources"].items():
        if receipt["private"][path]["sha256"] != digest:
            raise ValueError("Original private configuration backup mismatch")
    for entry in receipt["private"].values():
        relative = Path(entry["file"])
        if relative.is_absolute() or ".." in relative.parts or sha(directory / relative) != entry["sha256"]:
            raise ValueError("Private configuration backup mismatch")
    state = restore_docker.verify_bundle(directory / "state.tar.gz")
    if state.get("image_archive_sha256") != sha(directory / "state.tar.gz.images.tar"):
        raise ValueError("Missing exact referenced image archive")
    source_volumes = state["manifest"]["volumes"]
    if source_volumes != {"data": plan["volumes"]["arena:/app/data"],
                          "uploads": plan["volumes"]["arena:/app/uploads"],
                          "artifacts": plan["volumes"]["controller:/artifacts"]}:
        raise ValueError("Backup state volume identities mismatch")
    with (directory / "gateway.tar.gz").open("rb") as source:
        read_snapshot(source, roles=ROLES)
    if require_drill:
        drill = json.loads((directory / "drill.json").read_text(encoding="utf-8"))
        if (drill.get("complete_sha256") != sha(directory / "complete.json")
                or drill.get("sqlite_integrity") != "ok" or drill.get("schema") != 20
                or drill.get("verified") != ["data", "uploads", "artifacts", "caddy_data", "caddy_config", "private"]
                or len(drill.get("restored_volumes", {})) != 5
                or set(drill["restored_volumes"].values()) & set(plan["volumes"].values())):
            raise ValueError("A verified restore drill on new volumes is required")
    return receipt


def drill(site, directory):
    directory = Path(directory).resolve()
    verify_complete(directory, site.plan, require_drill=False)
    project = "neon-arena-restore-b13-" + secrets.token_hex(5)
    restored = restore_docker.restore(directory / "state.tar.gz", project)
    caddy = {role: project + "_" + role for role in ROLES}
    for name in caddy.values():
        existing = run(["docker", "volume", "ls", "--format", "{{.Name}}"] ).split()
        if name in existing:
            raise FileExistsError("Restore destination exists")
        run(["docker", "volume", "create", "--label", "com.docker.compose.project=" + project, name])
    image = site.model("local")["services"]["arena"]["image"]
    # Probe the restored database without starting Arena or claiming leases.
    # Pinned B1.3 images use schema 20; do not silently accept a later migration.
    probe = ("import sqlite3; c=sqlite3.connect('file:/restored/arena.sqlite3?mode=ro',uri=True); "
             "assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'; "
             "assert not c.execute('PRAGMA foreign_key_check').fetchall(); "
             "assert c.execute('PRAGMA user_version').fetchone()[0]==20")
    run(["docker", "run", "--rm", "--pull", "never", "--log-driver", "none", "--network", "none",
         "--read-only", "--user", "10001:10001", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
         "--mount", f"type=volume,src={restored['data']},dst=/restored,readonly",
         "--entrypoint", "python", image, "-c", probe])
    binary_run(gateway_helper(caddy, image, restore=True), directory / "gateway.tar.gz", restore=True)
    # Re-snapshot restored Caddy volumes and compare every file's bytes.
    binary_run(gateway_helper(caddy, image), directory / "drill-gateway.tar.gz")
    with (directory / "gateway.tar.gz").open("rb") as source, (directory / "drill-gateway.tar.gz").open("rb") as target:
        if read_snapshot(source, roles=ROLES)["files"] != read_snapshot(target, roles=ROLES)["files"]:
            raise ValueError("Restored Caddy data differs")
    record = {"complete_sha256": sha(directory / "complete.json"),
              "sqlite_integrity": "ok", "schema": 20,
              "verified": ["data", "uploads", "artifacts", "caddy_data", "caddy_config", "private"],
              "restored_volumes": {**restored, **caddy}}
    private_json(directory / "drill.json", record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("backup", "drill", "verify"))
    parser.add_argument("--directory", required=True, help="Private switch bundle")
    parser.add_argument("--backup-directory", required=True, help="New protected backup directory")
    args = parser.parse_args()
    try:
        site = Site(args.directory)
        with site.exclusive():
            if args.action == "backup":
                backup(site, args.backup_directory)
            elif args.action == "drill":
                drill(site, args.backup_directory)
            else:
                verify_complete(args.backup_directory, site.plan)
        print("PASS: " + args.action + "; protect all files and retain restore volumes for review")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        parser.exit(1, "BLOCKED: complete cold backup/restore verification failed; no cutover authorized.\n")


if __name__ == "__main__":
    main()
