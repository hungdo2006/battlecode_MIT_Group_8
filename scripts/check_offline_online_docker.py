"""End-to-end Phase A rehearsal with TWO disposable Docker Compose projects.

Real Docker bot compilation, Official Match, signed offline export and separate
Account-Only online publication. Both endpoints are localhost HTTP **QA ONLY**:
this does not prove Exam LAN TLS, air-gap or independent physical hosts.

Requirements: Docker Desktop (Linux), Python requirements-dev.txt.
Command: python scripts/check_offline_online_docker.py --build

The script refuses non-QA project names, uses new random data/volumes, and
removes only resources owned by its two generated Compose projects.
"""
import argparse
import base64
from copy import deepcopy
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
QA_IMAGE_PREFIX = "neon-arena-qa"

# Unlike the public hunter.py sample, this test bot never waits at distance 2.
# A stationary opponent would otherwise cause a valid draw and automatic
# tie-breaks, leaving the first Official Match completed but the event active.
QA_AGGRESSIVE_BOT = """import json, sys
def choose(state):
    you, enemy = state["you"], state["enemy"]
    dx, dy = enemy["x"] - you["x"], enemy["y"] - you["y"]
    if abs(dx) + abs(dy) == 1:
        return {"type": "attack"}
    direction = ("right" if dx > 0 else "left") if dx else ("down" if dy > 0 else "up")
    return {"type": "move", "direction": direction}
for line in sys.stdin:
    print(json.dumps(choose(json.loads(line)), separators=(",", ":")), flush=True)
"""
SEED = """
import json,sys
from pathlib import Path
from backend.admin_cli import bootstrap_admin
from backend.account_database import AccountDatabase
from backend.writer_lock import WriterLock
from backend.auth_service import AuthService
from backend.auth_limits import AuthRateLimiter

credentials=json.load(sys.stdin)
data=Path('/app/data')
bootstrap_admin(data, 'qa.admin', credentials['password'], 'QA Event Admin')
if credentials['players']:
    with WriterLock(data) as writer, AccountDatabase(data).writer_connection(writer) as connection:
        auth=AuthService(connection,writer,login_limiter=AuthRateLimiter())
        actor=auth.login('qa.admin',credentials['password'],
                         audience='ADMIN',source_key='qa-bootstrap').principal
        for name in ('qa.alice','qa.bob'):
            invitation=auth.issue_invitation(actor,name,name=name)
            auth.activate(invitation.token,credentials['password'])
print('QA accounts prepared')
"""


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return server.getsockname()[1]


def qa_project(role, nonce):
    if role not in ("off", "on") or not nonce.isalnum() or len(nonce) != 10:
        raise ValueError("Invalid QA project identifier")
    return "neon-phase-a-" + role + "-" + nonce


def qa_environment(role, port, project, signing_key):
    if role not in ("off", "on") or not project.startswith("neon-phase-a-" + role + "-"):
        raise ValueError("Refusing a non-QA project")
    if not 1 <= port <= 65535 or len(signing_key) < 32:
        raise ValueError("Invalid local port or signing key")
    # Keep Docker CLI/Windows PATH variables, but never inherit real Arena
    # gateway/SMTP/application secrets from the operator's PowerShell session.
    docker_environment = {key: value for key, value in os.environ.items()
                          if not key.startswith("ARENA_") and key != "SANDBOX_NAMESPACE"}
    return {
        **docker_environment,
        "ARENA_BIND_IP": "127.0.0.1",
        "ARENA_PORT": str(port),
        "ARENA_ACCOUNT_AUTH": "1",
        "ARENA_ACCOUNT_ONLY": "1",
        "ARENA_SELF_REGISTRATION": "0",
        "ARENA_EMAIL_VERIFICATION": "0",
        "ARENA_AUTH_ALLOW_HTTP": "1",  # localhost QA only, never an Exam overlay
        "ARENA_PUBLIC_GATEWAY": "0",
        "ARENA_READ_ONLY": "0",
        "ARENA_ALLOWED_HOSTS": "",
        "ARENA_AUTH_ORIGINS": f"http://127.0.0.1:{port}",
        "ARENA_ADMIN_TOTP_REQUIRED": "0",  # isolated local fixture only
        "ARENA_PUBLIC_ADMIN_PASSWORD_ONLY": "0",
        "ARENA_ADMIN_CODE": "",
        "ARENA_RUNNER_TOKEN": secrets.token_hex(32),
        "ARENA_OFFLINE_RESULTS_KEY": signing_key,
        "ARENA_OFFLINE_SITE_ID": project if role == "off" else "",
        "SANDBOX_NAMESPACE": project + "-bots",
        "DOCKER_SOCKET_GID": os.environ.get("DOCKER_SOCKET_GID", "0"),
    }


class QAStack:
    def __init__(self, role, nonce, signing_key, folder):
        self.project = qa_project(role, nonce)
        self.role = role
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.env = qa_environment(role, self.port, self.project, signing_key)
        self.override = Path(folder) / (role + "-stack.json")
        images = {name: f"{QA_IMAGE_PREFIX}-{name}:local"
                  for name in ("arena", "controller", "bot-image")}
        self.override.write_text(json.dumps({"services": {
            "arena": {"image": images["arena"]},
            "controller": {"image": images["controller"],
                           "environment": {"SANDBOX_IMAGE": images["bot-image"]}},
            "bot-image": {"image": images["bot-image"]},
        }}), encoding="utf-8")
        self.command = [
            "docker", "compose", "--env-file", str(ROOT / ".env.example"),
            "-f", str(ROOT / "compose.yaml"), "-f", str(self.override),
            "-p", self.project,
        ]

    def compose(self, *args, input_data=None, check=True):
        result = subprocess.run(self.command + list(args), cwd=ROOT,
                                env=self.env, input=input_data, text=True,
                                capture_output=True)
        if check and result.returncode:
            # Never print Compose config, raw stderr or Docker inspect:
            # it may contain synthetic signing/controller secrets.
            raise RuntimeError(f"QA {self.role} Docker Compose {args[0]} failed (exit {result.returncode})")
        return result

    def seed(self, password, *, players):
        result = self.compose(
            "run", "--rm", "--no-deps", "-T", "arena", "python", "-c", SEED,
            input_data=json.dumps({"password": password, "players": players}))
        assert "QA accounts prepared" in result.stdout

    def start(self):
        self.compose("up", "-d", "--no-build", "--wait", "--wait-timeout", "120")
        with httpx.Client(trust_env=False, timeout=5) as client:
            for _ in range(40):
                try:
                    result = client.get(self.url + "/api/health")
                    if result.status_code == 200 and result.json()["runner"]["ready"]:
                        return
                except (httpx.RequestError, ValueError, KeyError):
                    pass
                time.sleep(.5)
        raise AssertionError(f"QA {self.role} Arena/Controller did not become ready")

    def stop(self):
        # Only stop OUR random Compose project. Named volumes are kept until
        # the label-checked cleanup below, never '--volumes' for unknown projects.
        self.compose("down", "--timeout", "30", check=False)

    def cleanup(self):
        self.stop()
        result = subprocess.run(
            ["docker", "volume", "ls", "--filter",
             "label=com.docker.compose.project=" + self.project,
             "--format", "{{.Name}}"],
            cwd=ROOT, env=self.env, capture_output=True, text=True, check=True)
        for volume in result.stdout.splitlines():
            info = subprocess.run(["docker", "volume", "inspect", volume],
                                  cwd=ROOT, env=self.env, capture_output=True,
                                  text=True, check=True)
            record = json.loads(info.stdout)[0]
            if (record.get("Labels", {}).get("com.docker.compose.project") != self.project
                    or not volume.startswith(self.project + "_")):
                raise RuntimeError("Refusing to delete a volume not owned by this QA project")
            subprocess.run(["docker", "volume", "rm", volume],
                           cwd=ROOT, env=self.env, capture_output=True, check=True)


class Account:
    def __init__(self, stack, audience, username, password):
        self.stack = stack
        self.audience = audience
        self.http = httpx.Client(base_url=stack.url, trust_env=False,
                                 headers={"Origin": stack.url}, timeout=30)
        self.call("POST", f"/api/{audience}/auth/login",
                  {"username": username, "password": password})
        self.csrf = self.call("GET", f"/api/{audience}/auth/csrf")["csrf_token"]

    def call(self, method, path, body=None, *, expected=200, csrf=True, retry_429=False):
        headers = {}
        if method in ("POST", "PUT", "PATCH", "DELETE") and csrf and hasattr(self, "csrf"):
            headers["X-CSRF-Token"] = self.csrf
        # A rate-limited read is safe to retry; mutating endpoints are never
        # automatically replayed since the first attempt may have committed.
        if retry_429 and (method != "GET" or expected != 200):
            raise ValueError("429 retry is allowed for successful GET reads only")
        for attempt in range(2 if retry_429 else 1):
            try:
                response = self.http.request(method, path, json=body, headers=headers)
            except httpx.RequestError as error:
                raise AssertionError(f"QA {self.audience} {path}: connection failed") from error
            if response.status_code == 429 and retry_429 and attempt == 0:
                retry_after = response.headers.get("Retry-After", "")
                if retry_after.isdigit() and 1 <= int(retry_after) <= 60:
                    print(f"QA {self.audience}: rate-limited read; respecting Retry-After ({retry_after}s)", flush=True)
                    time.sleep(int(retry_after) + 1)
                    continue
            if response.status_code != expected:
                raise AssertionError(
                    f"QA {self.audience} {method} {path}: HTTP {response.status_code}, expected {expected}")
            return response.json()
        raise AssertionError("Unexpected empty QA request loop")

    def close(self):
        self.http.close()


def wait_for_official_complete(admin, tournament_id, request_id, *, timeout=240, poll_interval=6):
    """Poll only the Official status until completion, then check event once.

    One read per six seconds stays far below the production 60/session/minute
    budget. A legitimate rate limit is respected, never disabled or bypassed.
    """
    deadline = time.monotonic() + timeout
    status = "SCHEDULED"
    current_id = request_id
    tournament_status = "ACTIVE"
    bracket_status = "READY"
    while time.monotonic() < deadline:
        request = admin.call(
            "GET", f"/api/admin/official-matches/{current_id}", retry_429=True)["request"]
        status = request["status"]
        if status in ("BLOCKED", "INTERRUPTED", "CANCELLED"):
            raise AssertionError(f"Real Official request did not complete: {status}")
        if status == "COMPLETED":
            detail = admin.call(
                "GET", f"/api/admin/team-tournaments/{tournament_id}", retry_429=True)["tournament"]
            tournament_status = detail["status"]
            if tournament_status == "COMPLETED":
                return request, detail
            bracket = detail.get("bracket", [])
            bracket_status = bracket[-1]["status"] if bracket else "MISSING"
            if any(slot.get("status") == "TIE" for slot in bracket):
                raise AssertionError("Official Match tied; Admin must resolve bracket after tie-breaks")
            # After a tied Official attempt, follow the replacement scheduled
            # against the SAME fixture, not the already completed request ID.
            next_id = next((fixture.get("official_request_id")
                           for fixture in detail.get("fixtures", [])
                           if fixture.get("official_request_id")
                           and fixture["official_request_id"] != current_id), None)
            if next_id:
                print("QA Official: observing scheduled tie-break rematch", flush=True)
                current_id = next_id
        time.sleep(poll_interval)
    raise AssertionError(
        f"Official QA deadline: Official={status}, tournament={tournament_status}, "
        f"bracket={bracket_status}. Check tie-breaks/fixture scheduling.")


def run_qa(offline, online, password):
    actors = []
    try:
        admin = Account(offline, "admin", "qa.admin", password)
        online_admin = Account(online, "admin", "qa.admin", password)
        alice = Account(offline, "player", "qa.alice", password)
        bob = Account(offline, "player", "qa.bob", password)
        actors.extend((admin, online_admin, alice, bob))

        before = online_admin.call("GET", "/api/public/standings")
        assert before["offline_tournaments"] == []
        online_teams = online_admin.call("GET", "/api/admin/teams")["teams"]

        teams = []
        for actor, slug in ((alice, "qa-hunters"), (bob, "qa-sentinels")):
            created = actor.call("POST", "/api/player/teams",
                                 {"slug": slug, "display_name": slug.replace("-", " ").title()},
                                 expected=201)
            team_id = created["team"]["id"]
            actor.call("POST", f"/api/player/teams/{team_id}/activate", {})
            teams.append(team_id)
            source = (QA_AGGRESSIVE_BOT.encode("utf-8") if actor is alice
                      else b'import json,sys\nfor line in sys.stdin: print(json.dumps({"type":"wait"}),flush=True)\n')
            uploaded = actor.call("POST", "/api/player/bots", {
                "filename": "bot.py", "name": "QA Hunter" if actor is alice else "QA Wait",
                "game_id": "robot_battle", "source_base64": base64.b64encode(source).decode("ascii"),
            }, expected=201)["bot"]
            if uploaded["status"] != "ready":
                raise AssertionError("Real Docker Sandbox did not compile the bot")
            actor.call("PUT", "/api/player/active-bot",
                       {"game_id": "robot_battle", "bot_id": uploaded["id"]})
        print("PASS offline: two active Teams, real Docker-compiled bots, active selections", flush=True)

        created = admin.call("POST", "/api/admin/team-tournaments", {
            "name": "QA Offline School Final", "game_id": "robot_battle",
            "team_ids": teams, "format": "single_elimination",
        }, expected=201)["tournament"]
        tournament_id = created["id"]
        started = admin.call("POST", f"/api/admin/team-tournaments/{tournament_id}/start", {})
        fixture = started["tournament"]["fixtures"][0]
        now = int(time.time())
        scheduled = admin.call(
            "POST", f"/api/admin/team-tournaments/{tournament_id}/fixtures/{fixture['id']}/schedule",
            {"bot_lock_at": now + 5, "scheduled_at": now + 9}, expected=201)
        request_id = scheduled["request"]["id"]
        request, detail = wait_for_official_complete(admin, tournament_id, request_id)
        if not request["outcome"] or not request["outcome"].get("winner_team_id"):
            raise AssertionError("QA Official had no recorded winning Team")
        replay = admin.call("GET", f"/api/admin/official-matches/{request_id}/replay")
        if not replay.get("frames") or replay["match"]["status"] != "completed":
            raise AssertionError("Official Match replay was not persisted")
        print(f"PASS offline: real Official completed, {len(replay['frames'])} replay frames", flush=True)

        package = admin.call("GET", f"/api/admin/team-tournaments/{tournament_id}/offline-export")["package"]
        signed = json.dumps(package, ensure_ascii=False)
        if ("source_base64" in signed or "source_sha256" in signed
                or "artifact_id" in signed or "arena_account" in signed):
            raise AssertionError("Signed public event contains a private data field")
        preview_path = "/api/admin/offline-results/preview"
        import_path = "/api/admin/offline-results/import"
        preview = online_admin.call("POST", preview_path, {"package": package})["preview"]
        assert preview["teams"] == 2 and preview["matches"] >= 1
        assert preview["source"] == offline.project
        assert online_admin.call("GET", "/api/public/standings")["offline_tournaments"] == []
        online_admin.call("POST", preview_path, {"package": package}, expected=403, csrf=False)
        tampered = deepcopy(package)
        tampered["payload"]["tournament"]["name"] = "Tampered QA Final"
        online_admin.call("POST", preview_path, {"package": tampered}, expected=422)
        assert online_admin.call("GET", "/api/public/standings")["offline_tournaments"] == []
        first = online_admin.call("POST", import_path,
                                  {"package": package, "confirm_publish": True})["publication"]
        second = online_admin.call("POST", import_path,
                                   {"package": package, "confirm_publish": True})["publication"]
        assert first["already_imported"] is False and second["already_imported"] is True
        public = online_admin.call("GET", "/api/public/standings")
        assert public["tournaments"] == before["tournaments"]
        assert len(public["offline_tournaments"]) == 1
        assert public["offline_tournaments"][0]["name"] == "QA Offline School Final"
        assert public["offline_tournaments"][0]["matches"]
        assert online_admin.call("GET", "/api/admin/teams")["teams"] == online_teams
        assert online_admin.http.get("/results").status_code == 200
        print("PASS transfer: preview isolated, bad signature/CSRF denied, published, idempotent, online data preserved", flush=True)

        online.compose("restart", "arena")
        online.start()
        persisted = online_admin.call("GET", "/api/public/standings")
        assert persisted == public
        print("PASS online: publication survives container restart", flush=True)
        print(json.dumps({"phase_a": "PASS", "official_matches": 1,
                          "replay_frames": len(replay["frames"]), "published_events": 1,
                          "offline_project": offline.project, "online_project": online.project},
                         ensure_ascii=False, indent=2), flush=True)
    finally:
        for actor in actors:
            actor.close()


def main(build=False):
    nonce = secrets.token_hex(5)
    shared_key = secrets.token_urlsafe(48)
    password = "Qa#2026-" + secrets.token_urlsafe(32)
    with tempfile.TemporaryDirectory(prefix="neon-phase-a-e2e-") as folder:
        offline = QAStack("off", nonce, shared_key, folder)
        online = QAStack("on", nonce, shared_key, folder)
        stacks = (offline, online)
        print("QA projects:", offline.project, online.project, flush=True)
        try:
            # Prebuilt tags are generated by scripts/check_docker.py --build.
            # --build rechecks the current revision using the SAME QA-only tags.
            if build:
                offline.compose("build")
            else:
                for name in ("arena", "controller", "bot-image"):
                    name = f"{QA_IMAGE_PREFIX}-{name}:local"
                    if subprocess.run(["docker", "image", "inspect", name],
                                      capture_output=True).returncode:
                        raise RuntimeError("QA images missing: use --build")
            for stack in stacks:
                stack.seed(password, players=stack is offline)
                stack.start()
            run_qa(offline, online, password)
        finally:
            for stack in reversed(stacks):
                try:
                    stack.cleanup()
                except Exception:
                    # Never continue deleting other projects when ownership or
                    # Engine connectivity cannot be established. Preserve data
                    # for manual investigation, but do not print credentials.
                    print(f"WARNING: QA {stack.role} cleanup incomplete; review {stack.project}", flush=True)
            print("QA-owned projects stopped; only label-verified QA volumes may be removed.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true",
                        help="Build all three QA-only images for the current checkout first")
    args = parser.parse_args()
    main(build=args.build)
