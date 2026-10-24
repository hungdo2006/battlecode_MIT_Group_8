"""Operator-only disposable B1.4 pilot on the existing EC2.

The original checkout, private overrides and named volumes are never edited.
No SSH/AWS API, prune, down -v, remove or volume delete operations.
All Docker commands operate on an explicitly named project and Compose file set.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

PILOT_PROJECT = "neon-b1-ec2-pilot"
OLD_PROJECT = "neon-arena"
DOMAIN = "traitimcodon.duckdns.org"
PILOT_FILE = "compose.ec2-pilot.yaml"
OLD_FILES = ("compose.yaml", "compose.override.yaml", "compose.public.yaml")
OLD_SERVICES = {"arena", "controller", "bot-image", "gateway"}
PILOT_SERVICES = {"arena", "gateway"}
OLD_VOLUMES = {
    "neon-arena_arena_data", "neon-arena_arena_uploads",
    "neon-arena_arena_artifacts", "neon-arena_caddy_data",
    "neon-arena_caddy_config",
}
PILOT_VOLUMES = {
    f"{PILOT_PROJECT}_{suffix}"
    for suffix in ("pilot_data", "pilot_uploads", "pilot_caddy_data", "pilot_caddy_config")
}


class Blocked(RuntimeError):
    """An unsafe or unverified pilot condition."""


def execute(command, cwd, *, interactive=False):
    kwargs = {} if interactive else {"capture_output": True, "text": True}
    process = subprocess.run(command, cwd=str(cwd), **kwargs, check=False, timeout=None if interactive else 90)
    if process.returncode:
        # Docker/Compose stderr can interpolate secrets: never show it.
        raise Blocked("LOCAL_COMMAND_FAILED")
    return "" if interactive else process.stdout


def safe_environment():
    # Avoid accidental overrides from an unrelated interactive shell.
    return {k: v for k, v in os.environ.items()
            if not k.startswith(("ARENA_", "SANDBOX_", "COMPOSE_"))}


def docker(command, cwd, *, interactive=False):
    # Caller supplies only fixed, reviewed project names and paths.
    kwargs = {} if interactive else {"capture_output": True, "text": True}
    result = subprocess.run(["docker", *command], cwd=str(cwd), env=safe_environment(),
                            **kwargs, check=False, timeout=None if interactive else 90)
    if result.returncode:
        raise Blocked("DOCKER_COMMAND_FAILED")
    return "" if interactive else result.stdout


def require_local_engine(root):
    if os.environ.get("DOCKER_HOST"):
        raise Blocked("DOCKER_HOST_OVERRIDE_FORBIDDEN")
    name = docker(["context", "show"], root).strip()
    context = json.loads(docker(["context", "inspect", name], root))[0]
    endpoint = context["Endpoints"]["docker"]["Host"]
    if not endpoint.startswith("unix:///"):
        raise Blocked("LOCAL_UNIX_DOCKER_REQUIRED")
    info = json.loads(docker(["version", "--format", "{{json .Server}}"], root))
    if info["Os"] != "linux":
        raise Blocked("LINUX_ENGINE_REQUIRED")


def get_sha(root):
    # Read-only; explicitly declare this directory safe for Git ownership checks.
    return execute(["git", "-c", f"safe.directory={root}", "rev-parse", "HEAD"], root).strip()


def commands(root, old_root, env):
    original = ["compose", "--env-file", str(old_root / ".env"), "-p", OLD_PROJECT]
    for name in OLD_FILES:
        original += ["-f", str(old_root / name)]
    pilot = ["compose", "--env-file", str(env), "-p", PILOT_PROJECT,
             "-f", str(root / PILOT_FILE)]
    return original, pilot


def resolved(command, root):
    return json.loads(docker([*command, "config", "--format", "json"], root))


def ports(service):
    return {(int(p["target"]), int(p["published"]), p.get("protocol", "tcp"))
            for p in service.get("ports", [])}


def volumes(model):
    return {value.get("name") for value in model.get("volumes", {}).values()}


def validate_models(old, pilot):
    if old["name"] != OLD_PROJECT or set(old["services"]) != OLD_SERVICES:
        raise Blocked("UNEXPECTED_ORIGINAL_PROJECT")
    if pilot["name"] != PILOT_PROJECT or set(pilot["services"]) != PILOT_SERVICES:
        raise Blocked("UNEXPECTED_PILOT_PROJECT")
    if volumes(old) != OLD_VOLUMES or volumes(pilot) != PILOT_VOLUMES:
        raise Blocked("VOLUME_NAMES_MISMATCH")
    if volumes(old) & volumes(pilot):
        raise Blocked("SHARED_VOLUME_FORBIDDEN")
    expected = {(80, 80, "tcp"), (443, 443, "tcp"), (443, 443, "udp")}
    if ports(old["services"]["gateway"]) != expected or ports(pilot["services"]["gateway"]) != expected:
        raise Blocked("PUBLIC_INGRESS_PORT_MISMATCH")
    for m in (old, pilot):
        if m["services"]["arena"].get("ports"):
            raise Blocked("ARENA_PORT_PUBLISHED")
    old_env = old["services"]["arena"]["environment"]
    env = pilot["services"]["arena"]["environment"]
    if old_env.get("ARENA_RUNNER") not in ("sandbox", "local_sandbox"):
        raise Blocked("OLD_RUNNER_NOT_LOCAL")
    if env.get("ARENA_RUNNER") != "remote_sandbox":
        raise Blocked("PILOT_NOT_REMOTE")
    if any(env.get(k) != "1" for k in ("ARENA_ACCOUNT_AUTH", "ARENA_ACCOUNT_ONLY",
                                       "ARENA_PUBLIC_GATEWAY", "ARENA_PUBLIC_ADMIN_PASSWORD_ONLY")):
        raise Blocked("PILOT_ACCOUNT_PASSWORD_AUTH_REQUIRED")
    # This supervised pilot intentionally uses the project's explicit
    # password-only Admin opt-in, matching the already running AWS site.
    if env.get("ARENA_AUTH_ALLOW_HTTP") != "0" or env.get("ARENA_ADMIN_TOTP_REQUIRED") != "0":
        raise Blocked("UNSAFE_PILOT_AUTH")
    if env.get("ARENA_ALLOWED_HOSTS") != DOMAIN or env.get("ARENA_AUTH_ORIGINS") != "https://" + DOMAIN:
        raise Blocked("PILOT_DOMAIN_MISMATCH")
    if pilot["services"]["gateway"]["environment"].get("ARENA_PUBLIC_DOMAIN") != DOMAIN:
        raise Blocked("PILOT_DOMAIN_MISMATCH")
    if len(env.get("ARENA_REMOTE_RUNNER_KEY", "").encode()) < 32 or len(env.get("ARENA_PROXY_SECRET", "")) < 48:
        raise Blocked("PILOT_SECRETS_NOT_READY")
    if env["ARENA_REMOTE_RUNNER_KEY"] == env["ARENA_PROXY_SECRET"]:
        raise Blocked("SECRETS_MUST_DIFFER")
    if any(k in env for k in ("ARENA_RUNNER_TOKEN", "ARENA_CONTROLLER_URL")):
        raise Blocked("CONTROLLER_TOKEN_ON_CLOUD")
    if pilot["services"]["arena"].get("depends_on"):
        raise Blocked("PILOT_LOCAL_CONTROLLER_DEPENDENCY")
    for service in pilot["services"].values():
        if service.get("privileged") or any(
            "/var/run/docker.sock" in str(m) for m in service.get("volumes", [])
        ):
            raise Blocked("PILOT_DOCKER_SOCKET_FORBIDDEN")
        for mount in service.get("volumes", []):
            if mount["type"] == "volume":
                name = pilot["volumes"][mount["source"]]["name"]
                if name not in PILOT_VOLUMES:
                    raise Blocked("PILOT_FOREIGN_VOLUME")
            elif mount["type"] == "bind":
                if mount["target"] != "/etc/caddy/Caddyfile" or not mount.get("read_only"):
                    raise Blocked("UNEXPECTED_PILOT_BIND")
    if pilot["networks"]["ingress_private"].get("internal") is not True:
        raise Blocked("PILOT_APP_NETWORK_NOT_PRIVATE")


def current_containers(root):
    ids = docker(["ps", "-q", "--filter", "publish=443"], root).split()
    if not ids:
        return set()
    inspected = json.loads(docker(["inspect", *ids], root))
    projects = {item["Config"].get("Labels", {}).get("com.docker.compose.project")
                for item in inspected}
    if not projects <= {OLD_PROJECT, PILOT_PROJECT}:
        raise Blocked("UNRELATED_SERVICE_ON_443")
    return projects


def is_running(command, role, root):
    ids = docker([*command, "ps", "-q", role], root).split()
    return bool(ids)


def context(args):
    root = Path(__file__).resolve().parents[1]
    old_root = Path(args.old_root).expanduser().resolve()
    env = (root / ".b1-pilot" / "cloud.env").resolve()
    if root == old_root:
        raise Blocked("MUST_USE_SEPARATE_CHECKOUT")
    if not all((old_root / n).is_file() for n in (*OLD_FILES, ".env")):
        raise Blocked("ORIGINAL_FILES_MISSING")
    if not env.is_file() or env.is_symlink():
        raise Blocked("PILOT_PRIVATE_ENV_MISSING")
    if args.old_sha and get_sha(old_root) != args.old_sha:
        raise Blocked("ORIGINAL_REVISION_CHANGED")
    if not (root / PILOT_FILE).is_file():
        raise Blocked("PILOT_COMPOSE_MISSING")
    require_local_engine(root)
    old, pilot = commands(root, old_root, env)
    validate_models(resolved(old, root), resolved(pilot, root))
    current_containers(root)
    return root, old_root, old, pilot


def check_disk(root):
    # Conservative minimum just for new image build; not a backup estimate.
    if shutil.disk_usage(root).free < 3 * 1024 ** 3:
        raise Blocked("LESS_THAN_3_GIB_FREE")


def prepare(args):
    root, _, old, pilot = context(args)
    if is_running(pilot, "gateway", root):
        raise Blocked("PILOT_ALREADY_STARTED")
    if not is_running(old, "gateway", root):
        raise Blocked("ORIGINAL_SITE_NOT_RUNNING")
    marker = root / ".b1-pilot" / "prepared"
    if marker.exists():
        raise Blocked("PILOT_ALREADY_PREPARED")
    check_disk(root)
    # Build and initialize only the NEW data volume; no port binding.
    docker([*pilot, "build", "arena"], root, interactive=True)
    for cli in (("migrate",), ("check",),
                ("create-admin", "--username", "b1.operator")):
        docker([*pilot, "run", "--rm", "--no-deps", "arena",
                "python", "-m", "backend.admin_cli", "--data-dir", "/app/data", *cli],
               root, interactive=True)
    marker.write_text("Fresh pilot initialized; old site unchanged.\n", encoding="utf-8")
    os.chmod(marker, 0o600)
    print("PASS: pilot images built, test DB/password-only Admin initialized; old website untouched")


def switch_to_pilot(args):
    if not args.confirm_downtime:
        raise Blocked("EXPLICIT_DOWNTIME_ACK_REQUIRED")
    root, _, old, pilot = context(args)
    if not (root / ".b1-pilot" / "prepared").is_file():
        raise Blocked("RUN_PREPARE_FIRST")
    if not is_running(old, "gateway", root) or is_running(pilot, "gateway", root):
        raise Blocked("UNEXPECTED_SITE_STATE")
    if current_containers(root) != {OLD_PROJECT}:
        raise Blocked("OLD_GATEWAY_MUST_OWN_443")
    # The owner has approved downtime. This is the only point that stops old services.
    try:
        docker([*old, "stop", "gateway", "arena", "controller"], root, interactive=True)
        docker([*pilot, "up", "-d", "--no-build"], root, interactive=True)
        if not is_running(pilot, "gateway", root):
            raise Blocked("PILOT_GATEWAY_NOT_RUNNING")
    except Exception:
        # Start failure happened before Windows worker was connected or any
        # pilot official was scheduled. Restore the old website immediately.
        try:
            docker([*pilot, "stop", "gateway", "arena"], root, interactive=True)
            docker([*old, "up", "-d", "--no-build", "--wait"], root, interactive=True)
        except Exception:
            raise Blocked("CUTOVER_AND_ROLLBACK_FAILED_MANUAL_INTERVENTION") from None
        raise Blocked("PILOT_FAILED_ORIGINAL_RESTARTED") from None
    print("PASS: pilot started on existing EC2; old project stopped, volumes intact")
    print("Next: verify public HTTPS, start Windows Worker, then run Official/replay tests")


def rollback(args):
    if not args.confirm_rollback:
        raise Blocked("EXPLICIT_ROLLBACK_ACK_REQUIRED")
    root, _, old, pilot = context(args)
    if not is_running(pilot, "gateway", root):
        raise Blocked("PILOT_GATEWAY_NOT_RUNNING")
    if is_running(old, "gateway", root):
        raise Blocked("ORIGINAL_GATEWAY_ALREADY_RUNNING")
    docker([*pilot, "stop", "gateway", "arena"], root, interactive=True)
    docker([*old, "up", "-d", "--no-build", "--wait"], root, interactive=True)
    print("PASS: original website restored with unchanged checkout, images and volumes")
    print("Pilot volumes retained; stop Windows Worker separately")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "prepare", "cutover", "rollback", "status"))
    parser.add_argument("--old-root", required=True, help="Existing EC2 checkout")
    parser.add_argument("--old-sha", required=True, help="Full pre-pilot old checkout SHA")
    parser.add_argument("--confirm-downtime", action="store_true")
    parser.add_argument("--confirm-rollback", action="store_true")
    args = parser.parse_args(argv)
    try:
        root, _, old, pilot = context(args) if args.action in ("check", "status") else (None, None, None, None)
        if args.action == "check":
            print("PASS: local Engine; separate projects/volumes; Cloud-only remote config; unchanged original")
        elif args.action == "status":
            print(json.dumps({"original_gateway_running": is_running(old, "gateway", root),
                              "pilot_gateway_running": is_running(pilot, "gateway", root),
                              "projects_on_public_443": sorted(current_containers(root))}))
        elif args.action == "prepare":
            prepare(args)
        elif args.action == "cutover":
            switch_to_pilot(args)
        elif args.action == "rollback":
            rollback(args)
    except (Blocked, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        parser.exit(1, "BLOCKED: B1.4 pilot safety check/action failed. No secrets printed; see operator runbook.\n")


if __name__ == "__main__":
    main()
