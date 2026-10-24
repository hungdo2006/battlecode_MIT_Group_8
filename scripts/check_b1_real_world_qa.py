"""Extended B1 acceptance on ONE Docker Desktop host, never WAN or production.

Uses disposable, label-checked QA stacks from check_b1_cloud_tls_docker.
Only an optional browser endpoint binds 127.0.0.1; all machine RPC uses
verified HTTPS on the private Docker transport. Credentials live in memory
and a temporary directory, never in evidence. No production .env is loaded.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time

try:
    from .check_b1_cloud_tls_docker import (
        CADDY, CLOUD_IMAGE, DRIVER, HOSTNAME, SEED, WORKER_IMAGES, Stack,
        env_without_operator_secrets, make_cloud_config, make_worker_override,
        project_names, wait_for_ca,
    )
    from .check_offline_online_docker import QA_AGGRESSIVE_BOT
except ImportError:
    from check_b1_cloud_tls_docker import (
        CADDY, CLOUD_IMAGE, DRIVER, HOSTNAME, SEED, WORKER_IMAGES, Stack,
        env_without_operator_secrets, make_cloud_config, make_worker_override,
        project_names, wait_for_ca,
    )
    from check_offline_online_docker import QA_AGGRESSIVE_BOT

DEFAULT_EVIDENCE = Path(".qa-evidence/b1-real-world")


CLIENT = DRIVER.split('print("QA_STAGE: cloud-health"', 1)[0] + r'''
import hashlib, secrets

operation = config["operation"]
def output(value):
    print("QA_RESULT " + json.dumps(value, sort_keys=True), flush=True)

def machine(path, body, expected, session=None, key=None):
    headers = {"Authorization": "Bearer " + (key or os.environ["ARENA_REMOTE_RUNNER_KEY"]),
               "Content-Type": "application/json"}
    if session:
        headers["X-Arena-Runner-Session"] = session
    req = Request(origin + "/api/remote-runner/" + path,
                  data=json.dumps(body).encode(), headers=headers)
    try:
        with build_opener(ProxyHandler({}), RejectRedirects()).open(req, timeout=16) as response:
            status, result = response.status, json.load(response)
    except HTTPError as exc:
        status, result = exc.code, {}
    assert status == expected, "Unexpected machine HTTP status: " + str(status)
    return result

if operation == "healthy":
    deadline = time.monotonic() + 110
    while time.monotonic() < deadline:
        try:
            result = HTTP().call("GET", "/api/health")
            if result["runner"]["ready"]:
                assert result["runner"]["transport"] == "remote-outbound"
                output({"ready": True, "tls_verified": True})
                break
        except Exception:
            pass
        time.sleep(3)
    else:
        raise AssertionError("Remote health recovery timed out")
elif operation == "security":
    machine("connect", {}, 401, key=secrets.token_hex(32))
    machine("connect", {}, 409)
    machine("respond", {"id": "0" * 32, "status": 200, "result": {}},
            409, session="invalid-session")
    output({"wrong_key": "PASS", "competing_worker": "PASS", "forged_session": "PASS"})
elif operation == "late-response":
    session = machine("connect", {}, 200)["session"]
    machine("respond", {"id": "0" * 32, "status": 200, "result": {}}, 409, session)
    machine("disconnect", {}, 200, session)
    machine("respond", {"id": "0" * 32, "status": 200, "result": {}}, 409, session)
    output({"unknown_result": "PASS", "retired_session": "PASS"})
else:
    admin = HTTP()
    admin.login("admin", "qa.admin")
    def player(name):
        client = HTTP()
        client.login("player", name)
        return client
    def submit(client, name, source, suffix="py"):
        return client.call("POST", "/api/player/bots", {
            "filename": "qa." + suffix, "name": name, "game_id": "robot_battle",
            "source_base64": base64.b64encode(source.encode()).decode(),
        }, expected=201)["bot"]
    if operation == "setup":
        alice, bob = player("qa.alice"), player("qa.bob")
        teams = config.get("teams", [])
        if not teams:
            for client, slug in ((alice, "qa-real-alpha"), (bob, "qa-real-beta")):
                team = client.call("POST", "/api/player/teams", {
                    "slug": slug, "display_name": slug}, expected=201)["team"]
                client.call("POST", "/api/player/teams/%s/activate" % team["id"], {})
                teams.append(team["id"])
        wait = 'import json,sys\nfor line in sys.stdin: print(json.dumps({"type":"wait"}),flush=True)\n'
        slow_wait = wait.replace('import json,sys', 'import json,sys,time').replace(
            'for line in sys.stdin:', 'for line in sys.stdin: time.sleep(0.45);')
        slow_attack = config["attacker"].replace('import json, sys', 'import json, sys, time').replace(
            'for line in sys.stdin:', 'for line in sys.stdin:\n    time.sleep(0.45)')
        literal = json.dumps('{"type":"wait"}')
        cpp = '#include <iostream>\n#include <string>\nint main(){std::string s;while(std::getline(std::cin,s))std::cout<<' + literal + '<<std::endl;}\n'
        java = 'import java.util.*; public class Main { public static void main(String[] a) { Scanner s=new Scanner(System.in); while(s.hasNextLine()){s.nextLine();System.out.println(' + literal + ');} } }'
        bots = {}
        for client, key, source, suffix in (
            (alice, "fast", config["attacker"], "py"), (alice, "slow", slow_attack, "py"),
            (alice, "a_wait", slow_wait, "py"), (bob, "wait", wait, "py"),
            (bob, "b_wait", slow_wait, "py"), (bob, "cpp", cpp, "cpp"),
            (bob, "java", java, "java"), (bob, "crash", "raise RuntimeError('synthetic QA crash')", "py"),
            (bob, "timeout", "import time; time.sleep(15)", "py"),
        ):
            bot = submit(client, "QA " + key, source, suffix)
            assert bot["status"] == "ready", "Remote compile failed for " + key
            bots[key] = bot["id"]
        bad = submit(bob, "QA invalid C++", "this is invalid C++", "cpp")
        assert bad["status"] != "ready"
        output({"teams": teams, "bots": bots, "invalid_compile": "PASS"})
    elif operation in ("tournament", "tournament-persist"):
        if operation == "tournament":
            for name, key in (("qa.alice", "fast"), ("qa.bob", "wait")):
                player(name).call("PUT", "/api/player/active-bot", {
                    "game_id": "robot_battle", "bot_id": config["bots"][key]})
            event = admin.call("POST", "/api/admin/team-tournaments", {
                "name": "QA B1 persistent standings", "game_id": "robot_battle",
                "team_ids": config["teams"], "format": "round_robin"}, expected=201)["tournament"]
            event = admin.call("POST", "/api/admin/team-tournaments/" + event["id"] + "/start", {})["tournament"]
            fixture = event["fixtures"][0]
            now = int(time.time())
            admin.call("POST", "/api/admin/team-tournaments/%s/fixtures/%s/schedule" % (event["id"], fixture["id"]),
                       {"bot_lock_at": now + 4, "scheduled_at": now + 8}, expected=201)
            event_id = event["id"]
        else:
            event_id = config["event_id"]
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            event = admin.call("GET", "/api/admin/team-tournaments/" + event_id)["tournament"]
            if event["status"] == "COMPLETED":
                assert event["standings"] and any(row.get("wins") == 1 for row in event["standings"])
                saved = {k: event[k] for k in ("standings", "fixtures", "status")}
                output({"event_id": event_id, "standings": event["standings"],
                        "sha256": hashlib.sha256(json.dumps(saved, sort_keys=True).encode()).hexdigest()})
                break
            time.sleep(5)
        else:
            raise AssertionError("Tournament standings did not complete")
    elif operation == "schedule":
        for name, key in (("qa.alice", config["a"]), ("qa.bob", config["b"])):
            player(name).call("PUT", "/api/player/active-bot", {
                "game_id": "robot_battle", "bot_id": config["bots"][key]})
        now = int(time.time())
        ids = []
        for _ in range(config.get("count", 1)):
            row = admin.call("POST", "/api/admin/official-matches", {
                "team_a_id": config["teams"][0], "team_b_id": config["teams"][1],
                "game_id": "robot_battle", "bot_lock_at": now + 4,
                "scheduled_at": now + 8}, expected=201)["request"]
            ids.append(row["id"])
        output({"ids": ids})
    elif operation in ("complete", "running", "interrupted"):
        deadline = time.monotonic() + 180
        max_active, queued_at_capacity = 0, False
        while time.monotonic() < deadline:
            system = admin.call("GET", "/api/admin/system")
            count = len(system["active_matches"])
            assert count <= 2 and system["capacity"] == 2
            max_active = max(max_active, count)
            rows = [admin.call("GET", "/api/admin/official-matches/" + rid)["request"]
                    for rid in config["ids"]]
            queued_at_capacity |= count == 2 and any(r["status"] == "LOCKED" for r in rows)
            if operation == "running":
                live = [r for r in rows if r["status"] == "RUNNING"]
                if len(live) >= config.get("min_running", len(rows)):
                    replays = [admin.call("GET", "/api/admin/official-matches/" + r["id"] + "/replay") for r in live]
                    if all(len(r["frames"]) >= 2 for r in replays):
                        output({"running": len(live), "max_active": max_active,
                                "queued_at_capacity": queued_at_capacity})
                        break
            elif all(r["status"] == ("COMPLETED" if operation == "complete" else "INTERRUPTED") for r in rows):
                summaries = []
                for row in rows:
                    replay = admin.call("GET", "/api/admin/official-matches/" + row["id"] + "/replay")
                    frames, match = replay["frames"], replay["match"]
                    assert len(frames) >= 2
                    if operation == "complete":
                        assert match["status"] == "completed"
                        assert match["result"] == row["outcome"]["result"]
                        assert frames[-1]["turn"] == row["outcome"]["turn"]
                        assert frames[-1]["result"]["winner"] == row["outcome"]["winner_side"]
                    else:
                        assert row["outcome"] is None and match["winner"] is None
                        assert match["result"]["winner"] is None
                        assert all(not f.get("result") for f in frames)
                    summaries.append({"id": row["id"], "status": row["status"],
                        "reason": row["status_reason"], "frames": len(frames),
                        "winner": match["winner"], "outcome": row["outcome"],
                        "replay_sha256": hashlib.sha256(json.dumps(replay, sort_keys=True).encode()).hexdigest()})
                output({"matches": summaries, "max_active": max_active,
                        "queued_at_capacity": queued_at_capacity})
                break
            elif any(r["status"] in ("BLOCKED", "CANCELLED") for r in rows):
                raise AssertionError("Official unexpectedly blocked or cancelled")
            elif operation == "complete" and any(r["status"] == "INTERRUPTED" for r in rows):
                raise AssertionError("Official unexpectedly interrupted")
            time.sleep(5)
        else:
            raise AssertionError("Official observation deadline: " + operation)
    elif operation == "offline":
        HTTP().call("GET", "/api/health", expected=503)
        alice = player("qa.alice")
        alice.call("POST", "/api/player/bots", {
            "filename": "offline.py", "name": "QA must reject offline",
            "game_id": "robot_battle", "source_base64": base64.b64encode(b'pass').decode()}, expected=503)
        output({"health_503": "PASS", "upload_503": "PASS"})
'''


def docker(*args, env=None):
    result = subprocess.run(["docker", *args], env=env, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("QA Docker command failed: " + args[0])
    return result.stdout


def require_local_engine():
    context = docker("context", "show").strip()
    metadata = json.loads(docker("context", "inspect", context))[0]
    # Context selection and DOCKER_HOST can coexist. A local-looking host
    # override must never hide a remote context selected by the Docker CLI.
    endpoints = [metadata["Endpoints"]["docker"]["Host"]]
    if os.environ.get("DOCKER_HOST"):
        endpoints.append(os.environ["DOCKER_HOST"])
    if any(not endpoint.startswith(("npipe://", "unix://")) for endpoint in endpoints):
        raise RuntimeError("Refusing a non-local Docker Engine for laptop QA")
    if json.loads(docker("version", "--format", "{{json .Server}}"))["Os"] != "linux":
        raise RuntimeError("B1 QA requires Linux containers")
    return context


def write_report(evidence, report):
    (evidence / "extended-results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def finalize_report(evidence, report, stacks):
    cleanup = {}
    for stack in stacks:
        try:
            stack.clean()
            for resource, command in (("containers", ("ps", "-aq")),
                                      ("volumes", ("volume", "ls", "-q")),
                                      ("networks", ("network", "ls", "-q"))):
                remaining = docker(*command, "--filter",
                                   "label=com.docker.compose.project=" + stack.project)
                if remaining.strip():
                    raise RuntimeError("QA cleanup left " + resource)
            cleanup[stack.project] = "PASS"
        except Exception:
            cleanup[stack.project] = "INCOMPLETE"
    report["cleanup"] = cleanup
    report["status"] = ("FAIL" if report.get("failure") or "INCOMPLETE" in cleanup.values()
                        or any(v.get("status") == "FAIL" for v in report["cases"].values()) else "PASS")
    write_report(evidence, report)
    print("Extended QA cleanup:", json.dumps(cleanup), flush=True)
    # Also fail when a --ui-only return is pending inside the try block.
    if report["status"] != "PASS":
        raise SystemExit(1)


def client(worker, operation, password, **kwargs):
    result = worker.compose("run", "--rm", "--no-deps", "-T", "agent", "python", "-c", CLIENT,
                           input_data=json.dumps({"operation": operation, "password": password, **kwargs}), check=False)
    if result.returncode:
        # Never disclose arbitrary traces, request headers or container logs.
        raise RuntimeError("Extended B1 QA client failed: " + operation + " (exit " + str(result.returncode) + ")")
    lines = [line[10:] for line in result.stdout.splitlines() if line.startswith("QA_RESULT ")]
    if len(lines) != 1:
        raise RuntimeError("Missing structured QA result: " + operation)
    return json.loads(lines[0])


def browser_check(port, password, request_id, evidence):
    from playwright.sync_api import expect, sync_playwright
    errors, failed_resources = [], []
    stage = "browser-launch"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True, args=[
            "--host-resolver-rules=MAP arena-qa.test 127.0.0.1", "--no-proxy-server"])
        try:
            # Only this browser context accepts the ephemeral local CA. Machine
            # TLS tests still require certificate + hostname verification.
            page = browser.new_page(ignore_https_errors=True, viewport={"width": 1440, "height": 1000})
            page.on("pageerror", lambda error: errors.append(type(error).__name__))
            page.on("response", lambda response: failed_resources.append(response.status)
                    if "/static/" in response.url and response.status >= 400 else None)
            stage = "landing"
            page.goto("https://arena-qa.test:" + str(port))
            page.click("#landing-login")
            stage = "login"
            page.fill("#account-username", "qa.admin")
            page.fill("#account-login-form [name=password]", password)
            page.click("#account-login-form [type=submit]")
            page.wait_for_function("app.initialized && !app.initializing")
            stage = "system"
            page.evaluate("location.hash='system'")
            expect(page.locator("#system-health")).to_have_attribute("data-status", "ready", timeout=20000)
            page.screenshot(path=str(evidence / "admin-system-desktop.png"), full_page=True)
            stage = "official-list"
            page.evaluate("location.hash='official'")
            row = page.locator('[data-request-id="' + request_id + '"]')
            expect(row).to_be_visible()
            stage = "official-replay"
            row.get_by_role("button", name="Xem Live / Replay").click()
            expect(page.locator("#view-replay")).to_be_visible()
            expect(page.locator("#timeline")).not_to_have_attribute("max", "0")
            expect(page.locator("#replay-meta")).not_to_contain_text("Invalid Date")
            page.screenshot(path=str(evidence / "official-replay-desktop.png"), full_page=True, animations="disabled")
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=str(evidence / "official-replay-mobile.png"), full_page=True, animations="disabled")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            assert not errors, "Browser raised JavaScript page errors"
            assert not failed_resources, "Browser static resource returned HTTP error"
            return {"status": "PASS", "engine": "Playwright Python / Chrome", "mcp": False,
                    "local_qa_ca_browser_exception": True, "javascript_errors": len(errors)}
        except Exception as exc:
            raise RuntimeError("Browser QA failed at " + stage + ": " + type(exc).__name__) from None
        finally:
            browser.close()


def main(build, evidence, ui_only=False):
    evidence.mkdir(parents=True, exist_ok=True)
    context = require_local_engine()
    report = {"scope": "ONE physical Windows laptop; isolated local Docker HTTPS, NOT Internet E2E",
              "source_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
              "docker_context": context, "ui_only": ui_only,
              "worktree_sha256": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in (
                  Path("backend/main.py"), Path("frontend/app.js"), Path(__file__))},
              "cases": {}}
    def record(name, value):
        report["cases"][name] = value
        write_report(evidence, report)
        print("PASS " + name, flush=True)

    nonce = secrets.token_hex(5)
    cloud_name, worker_name = project_names(nonce)
    key, token, proxy, password = [secrets.token_urlsafe(48) for _ in range(4)]
    transport = cloud_name + "_transport"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="neon-b1-real-qa-", dir=Path.home()) as folder:
        root = Path(folder)
        # The loopback browser uses a random external port; preserve it in
        # Host so strict Origin validation sees the same port as Chrome.
        (root / "Caddyfile").write_text(CADDY.replace("header_up Host {host}",
                                                     "header_up Host {hostport}"), encoding="utf-8")
        cert = root / "b1-ca.crt"
        cloud_path = make_cloud_config(root, cloud_name, transport, key, proxy)
        cfg = json.loads(cloud_path.read_text(encoding="utf-8"))
        cfg["services"]["gateway"]["ports"] = ["127.0.0.1:%d:443" % port]
        cfg["services"]["arena"]["environment"]["ARENA_AUTH_ORIGINS"] += ",https://%s:%d" % (HOSTNAME, port)
        cloud_path.write_text(json.dumps(cfg), encoding="utf-8")
        worker_path = make_worker_override(root, transport, cert)
        base = env_without_operator_secrets()
        env = {**base, "ARENA_REMOTE_SERVER_URL": "https://" + HOSTNAME,
               "ARENA_REMOTE_RUNNER_KEY": key, "ARENA_RUNNER_TOKEN": token,
               "SANDBOX_NAMESPACE": worker_name + "-bots", "DOCKER_SOCKET_GID": "0"}
        cloud = Stack(cloud_name, cloud_path, base)
        worker = Stack(worker_name, worker_path, env, compose_base="compose.remote-worker.yaml")
        report["projects"] = [cloud_name, worker_name]
        print("Isolated extended QA:", cloud_name, worker_name, flush=True)
        try:
            if build:
                cloud.compose("build", "arena")
                worker.compose("build")
            report["image_ids"] = {tag: json.loads(docker("image", "inspect", tag))[0]["Id"]
                                   for tag in (CLOUD_IMAGE, *WORKER_IMAGES.values())}
            cloud.compose("run", "--rm", "--no-deps", "-T", "arena", "python", "-c", SEED,
                          input_data=json.dumps({"password": password, "players": True}))
            cloud.compose("up", "-d", "--no-build")
            wait_for_ca(cloud, cert)
            worker.compose("up", "-d", "--no-build", "--wait", "--wait-timeout", "120")
            record("verified_https", client(worker, "healthy", password))
            record("machine_authentication", client(worker, "security", password))
            state = client(worker, "setup", password, attacker=QA_AGGRESSIVE_BOT)
            record("remote_compile_python_cpp_java_and_invalid_cpp", state)

            def schedule(a="fast", b="wait", count=1):
                return client(worker, "schedule", password, **state, a=a, b=b, count=count)["ids"]
            def wait(ids, operation="complete"):
                return client(worker, operation, password, ids=ids)
            for name, opponent in (() if ui_only else (("cpp_runtime", "cpp"), ("java_runtime", "java"),
                                   ("bot_crash_forfeit", "crash"), ("bot_timeout_forfeit", "timeout"))):
                result = wait(schedule(b=opponent))
                assert result["matches"][0]["winner"] == "A"
                faults = result["matches"][0]["outcome"]["result"]["faults"]
                if opponent in ("cpp", "java"):
                    assert not faults
                else:
                    assert set(faults) == {"B"}
                record(name, result)
            ids = schedule("slow", "b_wait", count=1 if ui_only else 3)
            concurrent = wait(ids)
            if not ui_only:
                assert concurrent["max_active"] == 2 and concurrent["queued_at_capacity"]
            record("ui_fixture_official" if ui_only else "two_simultaneous_officials_third_queued", concurrent)
            persisted_ids = ids
            baseline = concurrent["matches"]
            standings = client(worker, "tournament", password, **state)
            record("tournament_standings", standings)
            try:
                record("browser_ui", browser_check(port, password, ids[0], evidence))
            except Exception as exc:
                report["cases"]["browser_ui"] = {"status": "FAIL", "exception_type": type(exc).__name__,
                                                 "stage": str(exc) if isinstance(exc, RuntimeError) else "redacted"}
                reason = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
                print("FAIL browser_ui: " + reason, flush=True)
            if ui_only:
                if report["cases"]["browser_ui"].get("status") != "PASS":
                    raise RuntimeError("UI acceptance failed; see structured browser stage")
                return

            for disruption in ("agent_network_loss", "controller_restart", "cloud_restart"):
                ids = schedule("a_wait", "b_wait", count=2 if disruption == "agent_network_loss" else 1)
                wait(ids, "running")
                bot_ids = docker("ps", "-q", "--filter", "label=io.neonarena.sandbox=" + env["SANDBOX_NAMESPACE"]).split()
                assert len(bot_ids) == 2 * len(ids)
                records = json.loads(docker("inspect", *bot_ids))
                assert all(r["HostConfig"]["NetworkMode"] == "none" and not r["HostConfig"]["Privileged"]
                           and r["HostConfig"]["ReadonlyRootfs"] for r in records)
                report.setdefault("runtime_samples", []).append({"scenario": disruption,
                    "bot_containers": len(bot_ids), "stats": [json.loads(line) for line in
                        docker("stats", "--no-stream", "--format", "{{json .}}", *bot_ids).splitlines()]})
                started = time.monotonic()
                if disruption == "agent_network_loss":
                    agent_id = worker.compose("ps", "-q", "agent").stdout.strip()
                    agent = json.loads(docker("inspect", agent_id))[0]
                    assert agent["Config"]["Labels"]["com.docker.compose.project"] == worker_name
                    docker("network", "disconnect", transport, agent_id)
                    result = wait(ids, "interrupted")
                    record("offline_fail_closed", client(worker, "offline", password))
                    docker("network", "connect", transport, agent_id)
                elif disruption == "controller_restart":
                    worker.compose("kill", "-s", "SIGKILL", "controller")
                    worker.compose("up", "-d", "--no-build", "controller")
                    result = wait(ids, "interrupted")
                else:
                    cloud.compose("kill", "-s", "SIGKILL", "arena")
                    cloud.compose("up", "-d", "--no-build", "arena")
                    client(worker, "healthy", password)
                    result = wait(ids, "interrupted")
                result["seconds_to_observed_interrupt"] = round(time.monotonic() - started, 2)
                client(worker, "healthy", password)
                deadline = time.monotonic() + 65
                while time.monotonic() < deadline:
                    remaining = docker("ps", "-aq", "--filter", "label=io.neonarena.sandbox=" + env["SANDBOX_NAMESPACE"]).split()
                    if not remaining:
                        break
                    time.sleep(2)
                else:
                    raise AssertionError("Orphan QA bot containers after recovery")
                result["orphan_containers"] = 0
                record(disruption, result)
                record(disruption + "_fresh_official", wait(schedule()))

            persistence = wait(persisted_ids)
            assert [r["replay_sha256"] for r in persistence["matches"]] == [r["replay_sha256"] for r in baseline]
            record("cloud_results_replay_persist_after_restart", persistence)
            restored = client(worker, "tournament-persist", password, event_id=standings["event_id"])
            assert restored["sha256"] == standings["sha256"]
            record("cloud_standings_persist_after_restart", restored)
            worker.compose("stop", "agent")
            time.sleep(24)
            record("unknown_result_and_retired_session", client(worker, "late-response", password))
            worker.compose("start", "agent")
            client(worker, "healthy", password)
            record("final_post_reconnect_official", wait(schedule()))
        except Exception as exc:
            report["failure"] = {"type": type(exc).__name__, "stage": str(exc) if isinstance(exc, (AssertionError, RuntimeError)) else "redacted"}
            raise
        finally:
            finalize_report(evidence, report, (worker, cloud))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--ui-only", action="store_true", help="Only compile, run Official, standings and browser acceptance")
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    args = parser.parse_args()
    main(args.build, args.evidence.resolve(), args.ui_only)
