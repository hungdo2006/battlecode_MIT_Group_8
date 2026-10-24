"""Local two-project Remote Runner B1 HTTPS/Official acceptance, Docker Desktop only.

No AWS or public domain. A Caddy internal CA signs the *real* QA HTTPS endpoint
arena-qa.test on a Docker-only transport network; the worker trusts only this
ephemeral CA via SSL_CERT_FILE. Production TLS verification is never disabled.

Run from project root:
  python scripts/check_b1_cloud_tls_docker.py --build

Prerequisites: Docker Desktop Linux containers, Python requirements-dev.txt.
Production Compose projects/images, .env secrets and volumes are never reused.
Physical two-machine networking, public CA and real AWS staging remain separate.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time

try:
    from .check_offline_online_docker import SEED, QA_AGGRESSIVE_BOT
except ImportError:
    from check_offline_online_docker import SEED, QA_AGGRESSIVE_BOT

ROOT = Path(__file__).resolve().parents[1]
CLOUD_IMAGE = "neon-b1-qa-cloud:local"
WORKER_IMAGES = {"bot-image": "neon-b1-qa-bot:local",
                 "controller": "neon-b1-qa-controller:local",
                 "agent": "neon-b1-qa-agent:local"}
HOSTNAME = "arena-qa.test"

CADDY = r"""arena-qa.test {
    tls internal
    header {
        X-Content-Type-Options "nosniff"
        X-Frame-Options "DENY"
        -Server
    }
    reverse_proxy arena:8000 {
        header_up -X-Forwarded-For
        header_up -X-Forwarded-Proto
        header_up -X-Forwarded-Host
        header_up -Forwarded
        header_up -X-Real-IP
        header_up Host {host}
        header_up X-Arena-Proxy-Secret {$ARENA_PROXY_SECRET}
        header_up X-Arena-Client-IP {remote_host}
        header_up X-Arena-HTTPS 1
    }
}
"""

# Executed in a disposable QA agent container. It has HTTPS access to the
# gateway, but NO cloud database mount and NO Docker Engine socket.
DRIVER = r"""
import base64, http.cookiejar, json, os, sys, time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener
from remote_runner.agent import RejectRedirects

config = json.load(sys.stdin)
origin = "https://arena-qa.test"

class HTTP:
    def __init__(self):
        self.opener = build_opener(ProxyHandler({}),
                                   HTTPCookieProcessor(http.cookiejar.CookieJar()),
                                   RejectRedirects())
    def call(self, method, path, body=None, expected=200):
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Accept": "application/json"}
        if method not in ("GET", "HEAD"):
            headers["Origin"] = origin
        if data is not None:
            headers["Content-Type"] = "application/json"
        if hasattr(self, "csrf") and method in ("POST", "PUT", "DELETE", "PATCH"):
            headers["X-CSRF-Token"] = self.csrf
        request = Request(origin + path, headers=headers, data=data, method=method)
        try:
            with self.opener.open(request, timeout=28) as response:
                status = response.status
                body = response.read(2 * 1024 * 1024)
        except HTTPError as error:
            status = error.code
            body = error.read(16384)
        if status != expected:
            raise AssertionError("%s %s returned HTTP %s, expected %s" % (method, path, status, expected))
        return json.loads(body) if body else {}
    def login(self, role, username):
        self.call("POST", "/api/%s/auth/login" % role, {
            "username": username, "password": config["password"]})
        self.csrf = self.call("GET", "/api/%s/auth/csrf" % role)["csrf_token"]

print("QA_STAGE: cloud-health", flush=True)
health = HTTP()
deadline = time.monotonic() + 105
while time.monotonic() < deadline:
    try:
        state = health.call("GET", "/api/health")
        if state["runner"]["ready"]:
            assert state["runner"]["mode"] == "sandbox"
            assert state["runner"]["transport"] == "remote-outbound"
            break
    except (AssertionError, KeyError, URLError, ValueError):
        pass
    time.sleep(3)
else:
    raise AssertionError("Cloud did not become healthy after the PC connected")
print("PASS HTTPS: trusted QA Caddy certificate, cloud remote sandbox ready", flush=True)

print("QA_STAGE: account-login", flush=True)
admin = HTTP()
alice, bob = HTTP(), HTTP()
admin.login("admin", "qa.admin")
alice.login("player", "qa.alice")
bob.login("player", "qa.bob")
print("QA_STAGE: remote-bot-compile", flush=True)
teams = []
for client, slug, source in (
    (alice, "qa-b1-aggressive", config["attacker"]),
    (bob, "qa-b1-wait", 'import json,sys\nfor line in sys.stdin: print(json.dumps({"type":"wait"}),flush=True)\n'),
):
    team = client.call("POST", "/api/player/teams", {
        "slug": slug, "display_name": slug.replace("-", " ").title()}, expected=201)["team"]
    client.call("POST", "/api/player/teams/%s/activate" % team["id"], {})
    teams.append(team["id"])
    bot = client.call("POST", "/api/player/bots", {
        "filename": "qa.py", "name": slug, "game_id": "robot_battle",
        "source_base64": base64.b64encode(source.encode("utf-8")).decode("ascii"),
    }, expected=201)["bot"]
    # Public Account APIs deliberately never expose private artifact IDs.
    assert bot["status"] == "ready" and bot["id"]
    client.call("PUT", "/api/player/active-bot", {
        "game_id": "robot_battle", "bot_id": bot["id"]})
print("PASS cloud-to-PC: compiled two bot sources on remote Docker Controller", flush=True)

print("QA_STAGE: official-tournament", flush=True)
event = admin.call("POST", "/api/admin/team-tournaments", {
    "name": "QA B1 Remote Championship", "game_id": "robot_battle",
    "team_ids": teams, "format": "single_elimination",
}, expected=201)["tournament"]
started = admin.call("POST", "/api/admin/team-tournaments/%s/start" % event["id"], {})
fixture = started["tournament"]["fixtures"][0]
now = int(time.time())
scheduled = admin.call(
    "POST", "/api/admin/team-tournaments/%s/fixtures/%s/schedule" % (event["id"],fixture["id"]),
    {"bot_lock_at": now + 5, "scheduled_at": now + 9},
    expected=201)["request"]

deadline = time.monotonic() + 180
while time.monotonic() < deadline:
    request = admin.call("GET", "/api/admin/official-matches/%s" % scheduled["id"])["request"]
    if request["status"] in ("BLOCKED", "CANCELLED", "INTERRUPTED"):
        raise AssertionError("Remote Official Match failed: %s" % request["status"])
    if request["status"] == "COMPLETED":
        event = admin.call("GET", "/api/admin/team-tournaments/%s" % event["id"])["tournament"]
        if event["status"] == "COMPLETED":
            break
        raise AssertionError("Official finished but bracket not completed (check bot draw)")
    time.sleep(6)
else:
    raise AssertionError("Remote Official Match timed out")

assert request["outcome"]["winner_team_id"] in teams
print("QA_STAGE: replay", flush=True)
replay = admin.call("GET", "/api/admin/official-matches/%s/replay" % scheduled["id"])
assert replay["match"]["status"] == "completed"
assert len(replay["frames"]) >= 2
print("PASS Remote Official: real match + %d replay frames" % len(replay["frames"]), flush=True)
print(json.dumps({"b1_https_e2e": "PASS", "remote_official_matches": 1,
                  "replay_frames": len(replay["frames"]),
                  "tls_verified": True}), flush=True)
"""

# Executed in an ephemeral worker client *without* launching the actual agent.
# Used to validate fail-closed health while the background agent is stopped.
CHECK_HEALTH = r"""
import json, ssl
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener
status = None
try:
    with build_opener(ProxyHandler({})).open(Request(
        "https://arena-qa.test/api/health"),
        timeout=16) as result:
        status = result.status
except HTTPError as error:
    status = error.code
assert status == 503, "Cloud was not fail-closed without PC: " + str(status)
print('PASS fail-closed: no healthy Runner after PC Agent lost connection', flush=True)
"""


def project_names(nonce):
    if not isinstance(nonce, str) or len(nonce) != 10 or any(c not in "0123456789abcdef" for c in nonce):
        raise ValueError("Refusing invalid QA project identifier")
    return ("neon-b1-cloud-qa-" + nonce, "neon-b1-worker-qa-" + nonce)


def env_without_operator_secrets():
    return {key: value for key, value in os.environ.items()
            if not key.startswith("ARENA_") and key != "SANDBOX_NAMESPACE"}


class Stack:
    def __init__(self, project, filename, env, *, compose_base=None):
        if not (project.startswith("neon-b1-cloud-qa-") or project.startswith("neon-b1-worker-qa-")):
            raise ValueError("Refusing non-QA Compose stack")
        self.project, self.env = project, env
        self.command = ["docker", "compose", "--env-file", str(ROOT / ".env.example")]
        if compose_base:
            self.command.extend(["-f", str(ROOT / compose_base)])
        self.command.extend(["-f", str(filename), "-p", project])

    def compose(self, *args, input_data=None, check=True):
        result = subprocess.run(self.command + list(args), cwd=ROOT, env=self.env,
                                input=input_data, text=True, capture_output=True)
        if check and result.returncode:
            raise RuntimeError("B1 QA %s Docker %s failed (code %s)" %
                               (self.project, args[0], result.returncode))
        return result

    def clean(self):
        self.compose("down", "--timeout", "30", check=False)
        found = subprocess.run(["docker", "volume", "ls", "--filter",
                                "label=com.docker.compose.project=" + self.project,
                                "--format", "{{.Name}}"], cwd=ROOT, env=self.env,
                                capture_output=True, text=True, check=True)
        for volume in found.stdout.splitlines():
            record = json.loads(subprocess.run(["docker", "volume", "inspect", volume],
                              cwd=ROOT, env=self.env, capture_output=True, text=True,
                              check=True).stdout)[0]
            if (not volume.startswith(self.project + "_")
                    or record.get("Labels", {}).get("com.docker.compose.project") != self.project):
                raise RuntimeError("Refusing cleanup of volume outside QA project")
            subprocess.run(["docker", "volume", "rm", volume],
                           cwd=ROOT, env=self.env, text=True,
                           capture_output=True, check=True)


def make_cloud_config(folder, project, transport, key, proxy_key):
    cfg = {
        "services": {
            "arena": {
                "build": {"context": str(ROOT), "dockerfile": "Dockerfile", "target": "runtime"},
                "image": CLOUD_IMAGE,
                "init": True,
                "networks": ["cloud_private"],
                "environment": {
                    "ARENA_RUNNER": "remote_sandbox",
                    "ARENA_REMOTE_RUNNER_KEY": key,
                    "ARENA_ACCOUNT_AUTH": "1", "ARENA_ACCOUNT_ONLY": "1",
                    "ARENA_PUBLIC_GATEWAY": "1",
                    "ARENA_PUBLIC_ADMIN_PASSWORD_ONLY": "1",  # LOCAL QA ONLY; production requires MFA
                    "ARENA_ADMIN_TOTP_REQUIRED": "0",
                    "ARENA_AUTH_ALLOW_HTTP": "0", "ARENA_SELF_REGISTRATION": "0",
                    "ARENA_EMAIL_VERIFICATION": "0",
                    "ARENA_READ_ONLY": "0",
                    "ARENA_ALLOWED_HOSTS": HOSTNAME,
                    "ARENA_AUTH_ORIGINS": "https://" + HOSTNAME,
                    "ARENA_PROXY_SECRET": proxy_key,
                },
                "volumes": ["qa_cloud_data:/app/data", "qa_cloud_uploads:/app/uploads"],
                "cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"],
                "mem_limit": "512m", "pids_limit": 128,
            },
            "gateway": {
                "image": "caddy:2.9.1-alpine",
                "depends_on": ["arena"],
                "networks": {"cloud_private": {}, "transport": {"aliases": [HOSTNAME]}},
                "environment": {"ARENA_PROXY_SECRET": proxy_key},
                "volumes": [str(Path(folder) / "Caddyfile") + ":/etc/caddy/Caddyfile:ro",
                            "qa_caddy_data:/data", "qa_caddy_config:/config"],
                "security_opt": ["no-new-privileges:true"],
                # Deliberately NO published ports.
            },
        },
        "networks": {"cloud_private": {"internal": True},
                     "transport": {"name": transport, "driver": "bridge"}},
        "volumes": {"qa_cloud_data": {}, "qa_cloud_uploads": {},
                    "qa_caddy_data": {}, "qa_caddy_config": {}},
    }
    path = Path(folder) / "cloud.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return path


def make_worker_override(folder, transport, ca_file):
    cfg = {
        "services": {
            "bot-image": {"image": WORKER_IMAGES["bot-image"]},
            "controller": {"image": WORKER_IMAGES["controller"],
                           "environment": {"SANDBOX_IMAGE": WORKER_IMAGES["bot-image"]}},
            "agent": {
                "image": WORKER_IMAGES["agent"],
                "networks": ["runner_private", "default", "transport"],
                "volumes": [str(ca_file) + ":/certs/b1-root.crt:ro"],
                "environment": {"SSL_CERT_FILE": "/certs/b1-root.crt"},
            },
        },
        "networks": {"transport": {"external": True, "name": transport}},
    }
    path = Path(folder) / "worker.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return path


def run_client(worker, code, payload=None, *, one_off=False):
    args = ("run", "--rm", "--no-deps", "-T", "agent") if one_off else ("exec", "-T", "agent")
    # Container traces may contain credentials: disclose stage IDs only.
    result = worker.compose(*args, "python", "-c", code,
                            input_data=json.dumps(payload) if payload is not None else None,
                            check=False)
    if result.returncode:
        allowed = {"cloud-health", "account-login", "remote-bot-compile",
                   "official-tournament", "replay"}
        stages = [stage for line in result.stdout.splitlines()
                  if line.startswith("QA_STAGE: ")
                  for stage in [line.split(":", 1)[1].strip()]
                  if stage in allowed]
        phase = stages[-1] if stages else "startup-before-first-stage"
        raise RuntimeError("B1 QA client failed at stage " + phase
                           + " (exit " + str(result.returncode) + ")")
    return result.stdout


def wait_for_ca(cloud, cert):
    for _ in range(35):
        # Caddy's "tls internal" issues this root certificate on first startup.
        result = cloud.compose("exec", "-T", "gateway", "cat",
                               "/data/caddy/pki/authorities/local/root.crt", check=False)
        if result.returncode == 0 and "BEGIN CERTIFICATE" in result.stdout:
            cert.write_text(result.stdout, encoding="ascii")
            return
        time.sleep(1)
    raise AssertionError("Caddy internal CA certificate not available")


def main(build=False):
    nonce = secrets.token_hex(5)
    cloud_name, worker_name = project_names(nonce)
    transport = cloud_name + "_transport"
    key, controller_token, proxy_key = (secrets.token_hex(32),
                                        secrets.token_hex(32),
                                        secrets.token_hex(32))
    password = "Qa#2026-" + secrets.token_urlsafe(32)
    with tempfile.TemporaryDirectory(prefix="neon-b1-https-qa-", dir=Path.home()) as tmp:
        root = Path(tmp)
        (root / "Caddyfile").write_text(CADDY, encoding="utf-8")
        cert = root / "b1-ca.crt"
        cloud_path = make_cloud_config(root, cloud_name, transport, key, proxy_key)
        worker_path = make_worker_override(root, transport, cert)
        base = env_without_operator_secrets()
        cloud_env = {**base, "ARENA_REMOTE_RUNNER_KEY": key}
        worker_env = {**base,
                      "ARENA_REMOTE_SERVER_URL": "https://" + HOSTNAME,
                      "ARENA_REMOTE_RUNNER_KEY": key,
                      "ARENA_RUNNER_TOKEN": controller_token,
                      "SANDBOX_NAMESPACE": worker_name + "-bots",
                      "DOCKER_SOCKET_GID": os.environ.get("DOCKER_SOCKET_GID", "0")}
        cloud = Stack(cloud_name, cloud_path, cloud_env)
        worker = Stack(worker_name, worker_path, worker_env,
                       compose_base="compose.remote-worker.yaml")
        print("QA isolated Docker projects:", cloud_name, worker_name, flush=True)
        try:
            # Do not start a second server until Account SQLite is initialized.
            if build:
                cloud.compose("build", "arena")
                worker.compose("build")
            else:
                for tag in (CLOUD_IMAGE, *WORKER_IMAGES.values()):
                    if subprocess.run(["docker", "image", "inspect", tag], cwd=ROOT,
                                      capture_output=True).returncode:
                        raise RuntimeError("B1 QA image missing; rerun with --build")
            seed = cloud.compose("run", "--rm", "--no-deps", "-T", "arena",
                                 "python", "-c", SEED,
                                 input_data=json.dumps({"password": password, "players": True}))
            assert "QA accounts prepared" in seed.stdout
            cloud.compose("up", "-d", "--no-build")
            wait_for_ca(cloud, cert)
            worker.compose("up", "-d", "--no-build", "--wait", "--wait-timeout", "120")
            report = run_client(worker, DRIVER, {
                "password": password, "attacker": QA_AGGRESSIVE_BOT})
            # Never print raw failure responses or full Compose logs; public
            # output is limited to the driver-created PASS statements.
            for line in report.splitlines():
                if line.startswith("PASS ") or '"b1_https_e2e": "PASS"' in line:
                    print(line, flush=True)
            verified = json.loads(report.strip().splitlines()[-1])
            assert verified["b1_https_e2e"] == "PASS"
            assert verified["remote_official_matches"] == 1
            assert verified["tls_verified"] is True
            # Agent disconnected: after bounded stale session expiry, the cloud
            # must report unavailable; no local / legacy execution fallback.
            print("QA_STAGE: disconnect", flush=True)
            worker.compose("stop", "agent")
            time.sleep(24)
            remote_health = run_client(worker, CHECK_HEALTH, one_off=True)
            assert "PASS fail-closed" in remote_health
            print("PASS fail-closed: cloud rejects work without PC Runner", flush=True)
            print("QA_STAGE: reconnect", flush=True)
            worker.compose("start", "agent")
            recovered = run_client(worker, r"""
import json, time
from urllib.request import ProxyHandler, Request, build_opener
deadline = time.monotonic() + 100
while time.monotonic() < deadline:
    try:
        with build_opener(ProxyHandler({})).open(
            Request("https://arena-qa.test/api/health"), timeout=12) as resp:
            result = json.load(resp)
        if result["runner"]["ready"]:
            print("PASS recovery: remote Controller became healthy again", flush=True)
            break
    except Exception:
        pass
    time.sleep(3)
else:
    raise AssertionError("Worker reconnect did not restore remote runner availability")
""")
            assert "PASS recovery" in recovered
            print(recovered.strip(), flush=True)
            print(json.dumps({**verified,
                              "agent_disconnect": "PASS",
                              "agent_reconnect": "PASS"},
                             ensure_ascii=False, indent=2), flush=True)
        finally:
            # Cloud transport must only be torn down AFTER worker leaves it.
            for stack in (worker, cloud):
                try:
                    stack.clean()
                except Exception:
                    print("WARNING: QA cleanup incomplete for " + stack.project, flush=True)
            print("B1 QA projects stopped; only label-verified QA volumes deleted.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true",
                        help="Build QA-specific cloud, controller, bot and agent images")
    main(parser.parse_args().build)
