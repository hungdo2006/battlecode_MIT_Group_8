"""Operator-only in-place switch. Run on the Docker host; never uses SSH/AWS.

Resolved configurations contain secrets. Store the bundle outside Git or under
.runner-switch/, restrict its ACL, and never paste compose config into a ticket.
"""
import argparse
from copy import deepcopy
from datetime import datetime
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from backend.writer_lock import WriterLock
IMAGE = re.compile(r"sha256:[a-f0-9]{64}\Z")


def run(command, *, input=None):
    result = subprocess.run(command, cwd=ROOT, input=input, capture_output=True, text=True)
    if result.returncode:
        # Docker errors/config can contain expanded environment and credentials.
        raise RuntimeError("Docker operation failed; inspect locally without sharing raw output")
    return result.stdout


def local_engine():
    context = json.loads(run(["docker", "context", "inspect"]))[0]
    endpoints = [context["Endpoints"]["docker"]["Host"], os.environ.get("DOCKER_HOST", "")]
    if any(value and not value.startswith(("npipe://", "unix://")) for value in endpoints):
        raise RuntimeError("Run directly on the Docker host; remote Docker endpoints are refused")
    info = json.loads(run(["docker", "info", "--format", "{{json .}}"] ))
    if info["OSType"] != "linux":
        raise RuntimeError("Linux Docker Engine is required")
    return info["ID"]


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def literal(value, *, decode=False):
    if isinstance(value, str):
        return value.replace("$$", "$") if decode else value.replace("$", "$$")
    if isinstance(value, list):
        return [literal(item, decode=decode) for item in value]
    if isinstance(value, dict):
        return {key: literal(item, decode=decode) for key, item in value.items()}
    return value


def private_json(path, value, *, compose=False):
    with Path(path).open("x", encoding="utf-8") as target:
        os.chmod(path, 0o600)  # On Windows also restrict the containing NTFS ACL.
        json.dump(literal(value) if compose else value, target, indent=2)


def compose_command(path, project):
    # Explicit single full model, project and empty env: no implicit override/.env.
    return ["docker", "compose", "--env-file", str(Path(path).parent / "empty.env"),
            "-p", project, "-f", str(path)]


def resolve(command):
    # Compose config renders a reusable model: literal dollars are doubled,
    # including JSON output. Decode that serialization exactly once before
    # comparing semantic values or encoding a new full model.
    return literal(json.loads(run(command + ["config", "--format", "json"])), decode=True)


def volume_map(model):
    result = {}
    for service, destinations in {"arena": ("/app/data", "/app/uploads"),
                                  "controller": ("/artifacts",),
                                  "gateway": ("/data", "/config")}.items():
        if service not in model["services"]:
            continue
        for destination in destinations:
            mounts = [m for m in model["services"][service].get("volumes", [])
                      if m["target"] == destination]
            if len(mounts) != 1 or mounts[0]["type"] != "volume":
                raise ValueError("Expected persistent named volume missing")
            name = model["volumes"][mounts[0]["source"]].get("name")
            if not name:
                raise ValueError("Unresolved volume name")
            result[service + ":" + destination] = name
    if len(set(result.values())) != len(result):
        raise ValueError("Persistent volume aliases overlap")
    return result


def remote_model(local, key):
    if set(local["services"]) != {"arena", "controller", "bot-image", "gateway"}:
        raise ValueError("Unknown private Compose services; review before switching")
    if local["services"]["arena"]["environment"].get("ARENA_RUNNER") not in ("sandbox", "local_sandbox"):
        raise ValueError("Capture the original local sandbox configuration")
    if len(key.encode()) < 32 or key == local["services"]["controller"]["environment"].get("ARENA_RUNNER_TOKEN"):
        raise ValueError("Remote key must be random 32+ bytes and distinct from Controller token")
    result = deepcopy(local)
    result["services"] = {name: result["services"][name] for name in ("arena", "gateway")}
    arena = result["services"]["arena"]
    arena.pop("depends_on", None)
    arena.get("networks", {}).pop("runner_private", None)
    env = arena["environment"]
    env.pop("ARENA_CONTROLLER_URL", None)
    env.pop("ARENA_RUNNER_TOKEN", None)
    env["ARENA_RUNNER"] = "remote_sandbox"
    env["ARENA_REMOTE_RUNNER_KEY"] = key
    # Compose removes unused declarations on resolution. Keep the stopped
    # Controller's artifact volume in the local rollback model and plan; the
    # actuator never deletes it. Remote references only its four live volumes.
    used_volumes = {m["source"] for service in result["services"].values()
                    for m in service.get("volumes", []) if m["type"] == "volume"}
    result["volumes"] = {k: v for k, v in result["volumes"].items() if k in used_volumes}
    used_networks = {name for service in result["services"].values() for name in service.get("networks", {})}
    result["networks"] = {k: v for k, v in result.get("networks", {}).items() if k in used_networks}
    validate_models(local, result)
    return result


def validate_models(local, remote):
    if local.get("name") != remote.get("name") or set(remote["services"]) != {"arena", "gateway"}:
        raise ValueError("Project/service mismatch")
    if len(volume_map(local)) != 5 or any(volume_map(local)[k] != v for k, v in volume_map(remote).items()):
        raise ValueError("Persistent volume mismatch")
    for kind in ("volumes", "networks"):
        if any(local.get(kind, {}).get(k) != v for k, v in remote.get(kind, {}).items()):
            raise ValueError("Persistent project resources changed")
    if local["services"]["gateway"] != remote["services"]["gateway"]:
        raise ValueError("Caddy configuration/ports/origin changed")
    original = deepcopy(local["services"]["arena"])
    actual = deepcopy(remote["services"]["arena"])
    original.pop("depends_on", None)
    original.get("networks", {}).pop("runner_private", None)
    for model in (original, actual):
        for key in ("ARENA_RUNNER", "ARENA_CONTROLLER_URL", "ARENA_RUNNER_TOKEN", "ARENA_REMOTE_RUNNER_KEY"):
            model["environment"].pop(key, None)
    if original != actual:
        raise ValueError("Unexpected Arena/auth/signup/volume/image change")
    arena = remote["services"]["arena"]
    if arena.get("depends_on") or arena.get("ports"):
        raise ValueError("Cloud Arena must have no local dependencies or published ports")
    for service in remote["services"].values():
        if service.get("privileged") or any("docker.sock" in str(m) for m in service.get("volumes", [])):
            raise ValueError("Cloud may not access Docker socket")
    if any(k in arena["environment"] for k in ("ARENA_RUNNER_TOKEN", "ARENA_CONTROLLER_URL")):
        raise ValueError("Cloud contains local Controller credentials")
    if arena["environment"].get("ARENA_RUNNER") != "remote_sandbox":
        raise ValueError("Wrong remote mode")


def public_tls(origin):
    parsed = urlsplit(origin)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("One verified HTTPS public origin is required")
    connection = http.client.HTTPSConnection(parsed.hostname, parsed.port or 443,
                                             timeout=10, context=ssl.create_default_context())
    try:
        # System roots + hostname verification; no redirects/proxy/token/CA override.
        connection.request("GET", "/api/health")
        response = connection.getresponse()
        if response.status not in (200, 503):
            raise ValueError("Public endpoint did not return Arena health")
        payload = json.loads(response.read(65537))
        if response.status == 200 and not isinstance(payload.get("runner"), dict):
            raise ValueError("Public endpoint is not Arena")
    finally:
        connection.close()


def prepare(files, env_file, project, directory, key_file):
    engine = local_engine()
    directory = Path(directory).resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    (directory / "empty.env").touch(mode=0o600)
    command = ["docker", "compose", "--env-file", str(Path(env_file).resolve()), "-p", project]
    for filename in files:
        command += ["-f", str(Path(filename).resolve())]
    local = resolve(command)
    unresolved_env = literal(json.loads(run(command + ["config", "--format", "json", "--no-env-resolution"])), decode=True)
    for service in local["services"].values():
        image = json.loads(run(["docker", "image", "inspect", service["image"]]))[0]["Id"]
        service["image"] = image
        service.pop("build", None)
        service["pull_policy"] = "never"
    # Controller must launch the pinned bot image even if a mutable tag moves.
    local["services"]["controller"]["environment"]["SANDBOX_IMAGE"] = local["services"]["bot-image"]["image"]
    remote = remote_model(local, Path(key_file).read_text(encoding="utf-8").strip())
    for mode, model in (("local", local), ("remote", remote)):
        path = directory / (mode + ".json")
        private_json(path, model, compose=True)
        if resolve(compose_command(path, project)) != model:
            raise ValueError("Compose round trip changed literal values; refusing configuration")
    paths = [*map(lambda p: Path(p).resolve(), files), Path(env_file).resolve(), Path(key_file).resolve()]
    for service in unresolved_env["services"].values():
        for reference in service.get("env_file", []):
            path = Path(reference["path"] if isinstance(reference, dict) else reference)
            if path.exists():
                paths.append(path.resolve())
    for kind in ("secrets", "configs"):
        for reference in local.get(kind, {}).values():
            if reference.get("file"):
                paths.append(Path(reference["file"]).resolve())
    for name, service in local["services"].items():
        for mount in service.get("volumes", []):
            if mount["type"] != "bind":
                continue
            if (name == "controller" and mount["source"] == "/var/run/docker.sock"
                    and mount["target"] == "/var/run/docker.sock"):
                continue  # Engine socket is not a configuration file to archive.
            paths.append(Path(mount["source"]))
    if any(not path.is_file() or path.is_symlink() for path in paths):
        raise ValueError("Private/bind configuration must be regular files, not missing paths/directories/symlinks")
    sources = {str(path): sha(path) for path in paths}
    plan = {"format": 1, "project": project, "engine": engine,
            "volumes": volume_map(local), "sources": sources,
            "models": {m: sha(directory / (m + ".json")) for m in ("local", "remote")}}
    private_json(directory / "plan.json", plan)
    return plan


class Site:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.plan = json.loads((self.directory / "plan.json").read_text(encoding="utf-8"))
        self.project = self.plan["project"]

    def exclusive(self):
        identity = hashlib.sha256((self.plan["engine"] + ":" + self.project).encode()).hexdigest()
        return WriterLock(Path(tempfile.gettempdir()) / "neon-runner-switch-locks" / identity)

    def command(self, mode):
        return compose_command(self.directory / (mode + ".json"), self.project)

    def compose(self, mode, *args):
        return run(self.command(mode) + list(args))

    def model(self, mode):
        return resolve(self.command(mode))

    def verify(self):
        if local_engine() != self.plan["engine"]:
            raise ValueError("Docker engine changed")
        for mode, digest in self.plan["models"].items():
            if sha(self.directory / (mode + ".json")) != digest:
                raise ValueError("Private configuration bundle changed")
        for path, digest in self.plan["sources"].items():
            if sha(path) != digest:
                raise ValueError("Original config/key/bind file changed; prepare a new bundle")
        local, remote = self.model("local"), self.model("remote")
        validate_models(local, remote)
        if volume_map(local) != self.plan["volumes"]:
            raise ValueError("Volume plan changed")
        run(["docker", "volume", "inspect", *self.plan["volumes"].values()])
        images = [service["image"] for service in local["services"].values()]
        if not all(IMAGE.fullmatch(image) for image in images):
            raise ValueError("Unpinned image")
        run(["docker", "image", "inspect", *images])
        # Do not adopt another Compose project or a container on different data.
        ids = self.compose("local", "ps", "-a", "-q", "arena").split()
        if len(ids) != 1:
            raise ValueError("Exactly one existing site Arena container is required")
        record = json.loads(run(["docker", "inspect", ids[0]]))[0]
        mounts = {m["Destination"]: m.get("Name") for m in record["Mounts"]}
        for destination in ("/app/data", "/app/uploads"):
            if mounts.get(destination) != self.plan["volumes"]["arena:" + destination]:
                raise ValueError("Running site volume mismatch")
        if record["Image"] != local["services"]["arena"]["image"]:
            raise ValueError("Running Arena image differs from pinned rollback image")
        environment = dict(value.split("=", 1) for value in record["Config"].get("Env", []) if "=" in value)
        active = remote if environment.get("ARENA_RUNNER") == "remote_sandbox" else local
        expected = active["services"]["arena"]["environment"]
        if any(environment.get(key) != str(value) for key, value in expected.items()):
            raise ValueError("Running Arena settings differ from prepared configuration")
        for service, destinations in (("gateway", ("/data", "/config")), ("controller", ("/artifacts",))):
            ids = self.compose("local", "ps", "-a", "-q", service).split()
            if len(ids) != 1:
                raise ValueError("Original site service is missing")
            other = json.loads(run(["docker", "inspect", ids[0]]))[0]
            if other["Image"] != local["services"][service]["image"]:
                raise ValueError("Original service image differs from pinned plan")
            mounts = {m["Destination"]: m.get("Name") for m in other["Mounts"]}
            if any(mounts.get(path) != self.plan["volumes"][service + ":" + path] for path in destinations):
                raise ValueError("Original service volume mismatch")

    def control(self, mode, action):
        return json.loads(self.compose(mode, "exec", "-T", "arena", "python", "-m",
                                      "backend.runner_control", action))

    def wait_ready(self, mode, timeout=90):
        container = self.compose(mode, "ps", "-q", "arena").strip()
        state = json.loads(run(["docker", "inspect", container]))[0]["State"]
        started = datetime.fromisoformat(state["StartedAt"].replace("Z", "+00:00")).timestamp()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                status = self.control(mode, "status")
                if (status["time"] >= started and status["mode"] == mode + "_sandbox"
                        and status["ready"] and status["admission_closed"]):
                    if mode == "local" or status["transport"] == "remote-outbound":
                        return status
            except (RuntimeError, KeyError, ValueError):
                pass
            time.sleep(1)
        raise RuntimeError("Target runner did not become ready with admission closed")

    def audit(self, event, **details):
        with (self.directory / "operations.jsonl").open("a", encoding="utf-8") as target:
            target.write(json.dumps({"time": time.time(), "event": event, **details}) + "\n")
            target.flush()
            os.fsync(target.fileno())


def transition(site, target, *, backup_directory, timeout=90, tls_check=public_tls):
    with site.exclusive():
        return _transition(site, target, backup_directory=backup_directory, timeout=timeout, tls_check=tls_check)


def _transition(site, target, *, backup_directory, timeout=90, tls_check=public_tls):
    try:
        from .runner_site_backup import verify_complete
    except ImportError:
        from runner_site_backup import verify_complete
    site.verify()
    verify_complete(backup_directory, site.plan)
    initial = site.control("local", "status")
    source = {"local_sandbox": "local", "remote_sandbox": "remote"}.get(initial["mode"])
    if source is None or source == target:
        raise ValueError("Unsupported source mode or already using requested mode")
    if target == "remote":
        origin = site.model("remote")["services"]["arena"]["environment"].get("ARENA_AUTH_ORIGINS", "")
        tls_check(origin)
    site.audit("drain_requested", source=source, target=target)
    site.control(source, "drain")  # Busy/unknown writer: refuse before stopping anything.
    site.audit("drained", source=source, target=target)
    try:
        # Gateway stays attached to the same networks and Caddy volumes.
        site.compose(source, "stop", "--timeout", "30", "arena")
        site.compose("local", "stop", "--timeout", "30", "controller")
        if target == "local":
            site.compose("local", "up", "-d", "--no-deps", "--no-build", "controller")
        site.compose(target, "up", "-d", "--no-deps", "--no-build", "arena")
        site.wait_ready(target, timeout)
        site.audit("target_ready_admission_closed", source=source, target=target)
    except Exception:
        site.audit("target_failed", source=source, target=target)
        # No work was admitted on target: this is a failed maintenance transaction,
        # never automatic runtime fallback for an active Official match.
        try:
            site.compose(target, "stop", "--timeout", "30", "arena")
            site.compose("local", "stop", "--timeout", "30", "controller")
            if source == "local":
                site.compose("local", "up", "-d", "--no-deps", "--no-build", "controller")
            site.compose(source, "up", "-d", "--no-deps", "--no-build", "arena")
            site.wait_ready(source, timeout)
        except Exception:
            site.audit("rollback_blocked", restored=source)
            raise RuntimeError("Rollback not ready: admission remains closed; operator intervention required") from None
        try:
            site.control(source, "resume")
            site.audit("rollback_complete", restored=source)
        except Exception:
            raise RuntimeError("Original mode is running; resume/audit acknowledgement uncertain. Inspect admission before further changes") from None
        raise RuntimeError("Target failed readiness; original mode restored with the same data") from None
    # Point of no automatic return: resume can succeed even if its reply is
    # lost. An audit IO failure after resume must never stop newly admitted jobs.
    try:
        site.control(target, "resume")
        site.audit("committed", source=source, target=target)
    except Exception:
        raise RuntimeError("Target is running; resume/audit acknowledgement uncertain. Inspect admission; no automatic rollback after resume") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--compose", action="append", required=True)
    prep.add_argument("--env-file", required=True)
    prep.add_argument("--project", required=True)
    prep.add_argument("--directory", required=True)
    prep.add_argument("--key-file", required=True)
    for action in ("status", "preflight", "drain", "resume", "switch"):
        command = sub.add_parser(action)
        command.add_argument("--directory", required=True)
        if action == "preflight":
            command.add_argument("--target", choices=("local", "remote"), required=True)
        if action == "switch":
            command.add_argument("--target", choices=("local", "remote"), required=True)
            command.add_argument("--backup-directory", required=True)
            command.add_argument("--execute-project", required=True)
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            plan = prepare(args.compose, args.env_file, args.project, args.directory, args.key_file)
            print(json.dumps({"project": plan["project"], "volumes": plan["volumes"],
                              "remote_services": ["arena", "gateway"], "config_roundtrip": "PASS"}))
        else:
            site = Site(args.directory)
            site.verify()
            if args.action == "switch":
                if args.execute_project != site.project:
                    raise ValueError("Explicit project acknowledgement mismatch")
                transition(site, args.target, backup_directory=args.backup_directory)
                print("PASS: switch committed; verify bot re-upload, Official matches and replay")
            elif args.action == "preflight":
                status = site.control("local", "status")
                if args.target == "remote":
                    public_tls(site.model("remote")["services"]["arena"]["environment"].get("ARENA_AUTH_ORIGINS", ""))
                env = site.model("local")["services"]["arena"]["environment"]
                flags = {key: env.get(key) for key in ("ARENA_ACCOUNT_ONLY", "ARENA_SELF_REGISTRATION",
                    "ARENA_EMAIL_VERIFICATION", "ARENA_PUBLIC_USERNAME_SIGNUP",
                    "ARENA_ADMIN_TOTP_REQUIRED", "ARENA_PUBLIC_ADMIN_PASSWORD_ONLY")}
                print(json.dumps({"project": site.project, "volumes": site.plan["volumes"],
                                  "account_flags": flags, "status": status,
                                  "target": args.target, "backup_verified": False,
                                  "target_worker": "checked_during_closed_admission_transition"}))
            else:
                if args.action in ("drain", "resume"):
                    with site.exclusive():
                        print(json.dumps(site.control("local", args.action)))
                else:
                    print(json.dumps(site.control("local", args.action)))
    except (OSError, ValueError, RuntimeError, ssl.SSLError, http.client.HTTPException):
        # Do not expose exception strings carrying filesystem/config/HTTP secrets.
        parser.exit(1, "BLOCKED: switch checks failed. Review private local evidence and the B1.3 runbook.\n")


if __name__ == "__main__":
    main()
