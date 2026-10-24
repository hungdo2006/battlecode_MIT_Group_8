"""B1.5: attach a reversible local sandbox to the *existing* B1.4 EC2 pilot.

Never start the local Compose model directly. All modes use the original pilot
project, data, upload and Caddy volumes. No AWS/SSH, prune, volume deletion or
database migration is performed. Private output stays outside Git.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import sys

from scripts import runner_switch as switch
from scripts import runner_site_backup as site_backup

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "neon-b1-ec2-pilot"
CLOUD_FILE = ROOT / "compose.ec2-pilot.yaml"
LOCAL_FILE = ROOT / "compose.ec2-pilot.local.yaml"
CLOUD_ENV = ROOT / ".b1-pilot" / "cloud.env"
DEFAULT_PRIVATE = ROOT / ".runner-switch" / "b15-pilot"
IGNORED = {"image", "build", "pull_policy"}


def command(compose, env):
    return ["docker", "compose", "--env-file", str(env), "-p", PROJECT,
            "-f", str(compose)]


def safe_private(path, data):
    path = Path(path)
    with path.open("x", encoding="utf-8") as stream:
        os.chmod(path, 0o600)
        stream.write(data)


def project_identity(cloud):
    if cloud.get("name") != PROJECT or set(cloud["services"]) != {"arena", "gateway"}:
        raise ValueError("Not the original B1.4 cloud-only project")
    expected = {f"{PROJECT}_{name}" for name in
                ("pilot_data", "pilot_uploads", "pilot_caddy_data", "pilot_caddy_config")}
    if {v["name"] for v in cloud["volumes"].values()} != expected:
        raise ValueError("Pilot persistent volume identity changed")
    arena = cloud["services"]["arena"]
    if arena["environment"].get("ARENA_RUNNER") != "remote_sandbox":
        raise ValueError("Pilot cloud must start in remote mode")
    if arena.get("depends_on") or arena.get("ports"):
        raise ValueError("Unexpected controller dependency/public Arena port")


def matching_remote(actual, generated):
    """Compare *complete* live Compose meaning, excluding only image pin/build."""
    if actual.get("name") != generated.get("name"):
        raise ValueError("Pilot project changed")
    for kind in ("volumes", "networks"):
        if actual.get(kind) != generated.get(kind):
            raise ValueError(f"Pilot {kind} changed")
    if set(actual["services"]) != set(generated["services"]):
        raise ValueError("Services differ from currently deployed cloud pilot")
    for name in actual["services"]:
        left = {k: v for k, v in actual["services"][name].items() if k not in IGNORED}
        right = {k: v for k, v in generated["services"][name].items() if k not in IGNORED}
        if left != right:
            raise ValueError(f"Existing pilot {name} has configuration drift")


def existing_pilot(env):
    cloud = switch.resolve(command(CLOUD_FILE, env))
    project_identity(cloud)
    ids = switch.run(command(CLOUD_FILE, env) + ["ps", "-q", "arena"]).split()
    if len(ids) != 1:
        raise ValueError("Exactly one running B1.4 pilot Arena is required")
    record = json.loads(switch.run(["docker", "inspect", ids[0]]))[0]
    if record["State"]["Running"] is not True:
        raise ValueError("Pilot Arena must be running")
    if record["Config"].get("Labels", {}).get("com.docker.compose.project") != PROJECT:
        raise ValueError("Arena belongs to another Compose project")
    if record["Image"] != json.loads(switch.run([
            "docker", "image", "inspect", cloud["services"]["arena"]["image"]]))[0]["Id"]:
        raise ValueError("Pilot image tag changed since deployment")
    mounts = {v["Destination"]: v.get("Name") for v in record["Mounts"]}
    for destination, suffix in (("/app/data", "pilot_data"), ("/app/uploads", "pilot_uploads")):
        if mounts.get(destination) != f"{PROJECT}_{suffix}":
            raise ValueError("Running pilot uses unexpected data volume")
    from backend.runner_control import validate_status
    live = json.loads(switch.run(command(CLOUD_FILE, env) + [
        "exec", "-T", "arena", "python", "-m", "backend.runner_control", "status"]))
    validate_status(live, mode="remote_sandbox")
    return cloud


def prepare(private):
    switch.local_engine()
    if CLOUD_ENV.is_symlink() or not CLOUD_ENV.is_file():
        raise ValueError("Missing private B1.4 cloud.env")
    if private.exists():
        raise ValueError("B1.5 bundle already exists; never overwrite keys or pinned models")
    cloud = existing_pilot(CLOUD_ENV)
    key = cloud["services"]["arena"]["environment"].get("ARENA_REMOTE_RUNNER_KEY", "")
    if len(key.encode("utf-8")) < 32:
        raise ValueError("Existing remote machine key is invalid")
    if "ARENA_RUNNER_TOKEN" in cloud["services"]["arena"]["environment"]:
        raise ValueError("Cloud pilot must not have a Controller token")
    private.mkdir(parents=True, mode=0o700, exist_ok=False)
    worker_env = private / "ec2-local.env"
    machine_key = private / "machine.key"
    # Preserve the EXISTING pilot origin, proxy key and PC machine key.
    # Add only an EC2-local Controller credential; never replace cloud.env.
    safe_private(worker_env, CLOUD_ENV.read_text(encoding="utf-8").rstrip() +
                 "\nARENA_RUNNER_TOKEN=" + secrets.token_urlsafe(48) + "\n")
    safe_private(machine_key, key + "\n")
    # Distinct image names; rebuilding these cannot overwrite the original site
    # or the running pilot Arena image. Build does not start or stop containers.
    switch.run(command(LOCAL_FILE, worker_env) + ["build", "bot-image", "controller"])
    plan = switch.prepare([LOCAL_FILE], worker_env, PROJECT, private / "site", machine_key)
    site = switch.Site(private / "site")
    matching_remote(cloud, site.model("remote"))
    # A stopped Controller must already exist for B1.3's ownership/mount checks.
    # Compose CREATE is targeted: it does not start, replace or restart Arena/Caddy.
    site.compose("local", "create", "--no-build", "--no-recreate", "controller")
    site.verify()
    return {"project": PROJECT, "volumes": plan["volumes"],
            "current_mode": "remote_sandbox", "cloud_data_reused": True,
            "local_controller": "created_not_started"}


def mode(site):
    from backend.runner_control import validate_status
    status = site.control("local", "status")
    current = {"local_sandbox": "local", "remote_sandbox": "remote"}.get(status["mode"])
    if current is None:
        raise ValueError("Unexpected runner mode")
    validate_status(status, mode=status["mode"])
    return current, status


def snapshot(site, destination):
    """One supervised cold backup/restore drill. Restarts the SAME pilot mode."""
    if Path(destination).exists():
        raise ValueError("Use a fresh backup directory")
    with site.exclusive():
        site.verify()
        source, _ = mode(site)
        site.control(source, "drain")  # Refuses an in-flight match/upload.
        stopped = False
        try:
            # Attempt recovery even if Docker partially stopped Arena before
            # reporting an error: never strand the website after partial stop.
            stopped = True
            site.compose(source, "stop", "--timeout", "30", "arena")
            site.compose("local", "stop", "--timeout", "30", "controller")
            site.compose(source, "stop", "--timeout", "30", "gateway")
            site_backup.backup(site, destination)
            site_backup.drill(site, destination)
            site_backup.verify_complete(destination, site.plan)
        finally:
            if stopped:
                # Restart is attempted even if backup/drill fails. Admission
                # remains closed unless the former runner becomes ready.
                site.compose(source, "up", "-d", "--no-deps", "--no-build", "gateway")
                if source == "local":
                    site.compose("local", "up", "-d", "--no-deps", "--no-build", "controller")
                site.compose(source, "up", "-d", "--no-deps", "--no-build", "arena")
                site.wait_ready(source, 120)
                site.control(source, "resume")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "status", "backup", "switch"))
    parser.add_argument("--directory", type=Path, default=DEFAULT_PRIVATE)
    parser.add_argument("--backup-directory", type=Path)
    parser.add_argument("--target", choices=("local", "remote"))
    parser.add_argument("--approve-downtime", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action == "prepare":
            result = prepare(args.directory.resolve())
        else:
            site = switch.Site(args.directory.resolve() / "site")
            site.verify()
            if args.action == "status":
                source, status = mode(site)
                result = {"project": PROJECT, "mode": source,
                          "ready": status["ready"], "admission_closed": status["admission_closed"],
                          "transport": status.get("transport"), "active_matches": status["active_matches"]}
            elif args.action == "backup":
                if not args.approve_downtime or not args.backup_directory:
                    raise ValueError("Backup requires a destination and explicit downtime approval")
                snapshot(site, args.backup_directory.resolve())
                result = {"project": PROJECT, "backup": "verified_cold_restore_drill",
                          "original_mode_restored": True}
            else:
                if not args.backup_directory or not args.target:
                    raise ValueError("Switch requires --target and a verified backup")
                switch.transition(site, args.target, backup_directory=args.backup_directory.resolve())
                result = {"project": PROJECT, "new_mode": args.target,
                          "storage": "unchanged"}
        print(json.dumps(result))
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        # Neither raw Docker errors nor private paths/tokens should reach logs.
        parser.exit(1, "BLOCKED: pilot shared-runner operation failed; existing volumes were not deleted.\n")


if __name__ == "__main__":
    main()
