"""Rehearse local -> remote -> local on ONE Docker host, NOT real Internet.

Creates unique QA projects/volumes, never mounts an existing site. Retains its
own stopped volumes and protected backups for inspection; never deletes data.
The internal QA CA is trusted only inside QA containers. Operator CLI has no
TLS-bypass option. Use --build to rebuild the QA images from this worktree.
"""
import argparse
import json
from pathlib import Path
import secrets
import time

try:
    from . import runner_switch as switch, runner_site_backup as backup
    from .check_b1_cloud_tls_docker import (CADDY, CLOUD_IMAGE, WORKER_IMAGES, Stack,
        env_without_operator_secrets, make_cloud_config, make_worker_override,
        project_names, wait_for_ca, SEED, QA_AGGRESSIVE_BOT)
    from .check_b1_real_world_qa import CLIENT
except ImportError:
    import runner_switch as switch, runner_site_backup as backup
    from check_b1_cloud_tls_docker import (CADDY, CLOUD_IMAGE, WORKER_IMAGES, Stack,
        env_without_operator_secrets, make_cloud_config, make_worker_override,
        project_names, wait_for_ca, SEED, QA_AGGRESSIVE_BOT)
    from check_b1_real_world_qa import CLIENT

ROOT = Path(__file__).resolve().parents[1]


def main(build=False):
    switch.local_engine()
    nonce = secrets.token_hex(5)
    project, pc_project = project_names(nonce)
    directory = ROOT / ".runner-switch" / ("qa-" + nonce)
    directory.mkdir(parents=True, mode=0o700)
    evidence = ROOT / ".qa-evidence" / ("b13-" + nonce + ".json")
    evidence.parent.mkdir(exist_ok=True)
    report = {"scope": "ONE Docker Desktop host; internal HTTPS, NOT Internet",
              "project": project, "worker_project": pc_project, "cases": {}}
    def record(name, details=True):
        report["cases"][name] = details
        evidence.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("PASS " + name, flush=True)
    key, token, local_token, proxy, password = [secrets.token_hex(32) for _ in range(5)]
    transport = project + "_transport"
    env = env_without_operator_secrets()
    (directory / "Caddyfile").write_text(CADDY, encoding="utf-8")
    (directory / "empty.env").touch()
    (directory / "key.private").write_text(key, encoding="utf-8")
    cloud_path = make_cloud_config(directory, project, transport, key, proxy)
    cert = directory / "b1-ca.crt"
    worker_path = make_worker_override(directory, transport, cert)
    worker_env = {**env, "ARENA_REMOTE_SERVER_URL": "https://arena-qa.test",
                  "ARENA_REMOTE_RUNNER_KEY": key, "ARENA_RUNNER_TOKEN": token,
                  "SANDBOX_NAMESPACE": pc_project + "-bots", "DOCKER_SOCKET_GID": "0"}
    worker = Stack(pc_project, worker_path, worker_env, compose_base="compose.remote-worker.yaml")
    cloud = Stack(project, cloud_path, env)
    current = None
    try:
        if build:
            cloud.compose("build", "arena")
            worker.compose("build")
        cfg = json.loads(cloud_path.read_text(encoding="utf-8"))
        pc = json.loads(worker.compose("config", "--format", "json").stdout)
        for name in ("bot-image", "controller"):
            cfg["services"][name] = pc["services"][name]
        controller = cfg["services"]["controller"]
        controller["environment"]["ARENA_RUNNER_TOKEN"] = local_token
        controller["environment"]["SANDBOX_NAMESPACE"] = project + "-bots"
        controller["volumes"] = [m if m["target"] != "/artifacts" else
                                  {"type": "volume", "source": "qa_artifacts", "target": "/artifacts"}
                                  for m in controller["volumes"]]
        arena = cfg["services"]["arena"]
        arena["environment"].pop("ARENA_REMOTE_RUNNER_KEY")
        arena["environment"].update(ARENA_RUNNER="sandbox", ARENA_RUNNER_TOKEN=local_token,
                                    ARENA_CONTROLLER_URL="http://controller:9000",
                                    SMTP_PASSWORD="qa-literal-$FOO-${BAR}-$$")
        arena["networks"].append("runner_private")
        arena["depends_on"] = {"controller": {"condition": "service_healthy"}}
        cfg["networks"]["runner_private"] = {"internal": True}
        cfg["volumes"]["qa_artifacts"] = {}
        cloud_path.unlink()
        switch.private_json(cloud_path, cfg, compose=True)
        cloud.compose("run", "--rm", "--no-deps", "-T", "arena", "python", "-c", SEED,
                      input_data=json.dumps({"password": password, "players": True}))
        cloud.compose("up", "-d", "--no-build")
        wait_for_ca(cloud, cert)
        plan = switch.prepare([cloud_path], directory / "empty.env", project,
                              directory / "bundle", directory / "key.private")
        current = switch.Site(directory / "bundle")
        report["volumes"] = plan["volumes"]
        current.verify()
        arena_id = current.compose("local", "ps", "-q", "arena").strip()
        inspect = json.loads(switch.run(["docker", "inspect", arena_id]))[0]
        synthetic = next(value for value in inspect["Config"]["Env"] if value.startswith("SMTP_PASSWORD="))
        assert synthetic.split("=", 1)[1] == "qa-literal-$FOO-${BAR}-$$"
        record("resolved_same_project_five_volumes_exact_roundtrip_and_dollar_secrets")
        def ready(mode):
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                try:
                    value = current.control(mode, "status")
                    if value["ready"] and value["mode"] == mode + "_sandbox": return value
                except RuntimeError:
                    pass
                time.sleep(1)
            raise RuntimeError("QA runner did not become ready")
        ready("local")
        def client(operation, **extra):
            result = worker.compose("run", "--rm", "--no-deps", "-T", "agent", "python", "-c", CLIENT,
                input_data=json.dumps({"operation": operation, "password": password, **extra}), check=False)
            if result.returncode:
                # Preserve exception type only; never raw traceback/request/config.
                raise RuntimeError("QA client failed at " + operation)
            return json.loads(next(line[10:] for line in result.stdout.splitlines() if line.startswith("QA_RESULT ")))
        state = client("setup", attacker=QA_AGGRESSIVE_BOT)
        local_ids = client("schedule", **state, a="fast", b="wait")["ids"]
        local_replays = client("complete", ids=local_ids)
        record("local_python_cpp_java_and_official_replay", local_replays)
        current.control("local", "drain")
        cloud.compose("stop", "arena", "controller", "gateway")
        backup.backup(current, directory / "cold-backup")
        drill = backup.drill(current, directory / "cold-backup")
        backup.verify_complete(directory / "cold-backup", plan)
        record("complete_cold_backup_all_images_private_config_caddy_and_restore_drill")
        report["restore_volumes"] = drill["restored_volumes"]
        current.compose("local", "up", "-d", "--no-build")
        ready("local")
        current.control("local", "resume")
        gateway_id = current.compose("local", "ps", "-q", "gateway").strip()
        # QA-only trust injected into the Python test harness, never operator CLI.
        # Prove the real CLI's system trust rejects this private certificate.
        def qa_tls(origin):
            code = "import urllib.request; urllib.request.urlopen('https://arena-qa.test/api/health',timeout=15).read()"
            result = worker.compose("run", "--rm", "--no-deps", "-T", "agent", "python", "-c", code, check=False)
            if result.returncode: raise RuntimeError("QA verified TLS check failed")
        # No PC started yet: readiness failure must return to the local mode.
        try:
            switch.transition(current, "remote", backup_directory=directory / "cold-backup", timeout=12, tls_check=qa_tls)
        except RuntimeError:
            pass
        else:
            raise AssertionError("Missing worker incorrectly committed")
        assert current.control("local", "status")["mode"] == "local_sandbox"
        assert not current.control("local", "status")["admission_closed"]
        record("missing_worker_rejected_and_actual_docker_rollback")
        worker.compose("up", "-d", "--no-build", "--wait", "--wait-timeout", "120")
        switch.transition(current, "remote", backup_directory=directory / "cold-backup", tls_check=qa_tls)
        remote = current.control("remote", "status")
        assert remote["mode"] == "remote_sandbox" and remote["transport"] == "remote-outbound"
        assert not current.compose("local", "ps", "--status", "running", "-q", "controller").strip()
        assert current.compose("remote", "ps", "-q", "gateway").strip() == gateway_id
        arena_id = current.compose("remote", "ps", "-q", "arena").strip()
        inspect = json.loads(switch.run(["docker", "inspect", arena_id]))[0]
        assert not any(value.startswith(("ARENA_RUNNER_TOKEN=", "ARENA_CONTROLLER_URL=")) for value in inspect["Config"]["Env"])
        assert not inspect["HostConfig"]["PortBindings"]
        assert not any("docker.sock" in str(mount) for mount in inspect["Mounts"])
        record("local_to_remote_same_volumes_and_gateway_controller_stopped")
        assert client("complete", ids=local_ids)["matches"] == local_replays["matches"]
        record("historical_official_result_and_replay_identical_after_switch")
        # Verify old active artifacts are rejected on the new store, then re-upload.
        stale = worker.compose("run", "--rm", "--no-deps", "-T", "agent", "python", "-c",
            CLIENT.split('operation = config["operation"]')[0] + '''
alice=HTTP(); alice.login("player","qa.alice")
alice.call("PUT","/api/player/active-bot",{"game_id":"robot_battle","bot_id":config["id"]},expected=409)
''', input_data=json.dumps({"password": password, "id": state["bots"]["fast"]}), check=False)
        assert stale.returncode == 0
        record("old_cloud_artifact_rejected_on_pc_with_same_image")
        remote_state = client("setup", attacker=QA_AGGRESSIVE_BOT, teams=state["teams"])
        ids = client("schedule", **remote_state, a="slow", b="b_wait", count=3)["ids"]
        live = client("running", ids=ids, min_running=2)
        try: current.control("remote", "drain")
        except RuntimeError: pass
        else: raise AssertionError("Drain accepted active matches")
        assert current.control("remote", "status")["admission_closed"]
        assert current.control("remote", "status")["mode"] == "remote_sandbox"
        record("refuses_switch_during_two_active_official_matches", live)
        # Resume only this same mode to let the queued third match finish.
        current.control("remote", "resume")
        completed = client("complete", ids=ids)
        completed["max_active"] = max(completed["max_active"], live["max_active"])
        completed["queued_at_capacity"] |= live["queued_at_capacity"]
        assert completed["max_active"] == 2 and completed["queued_at_capacity"]
        record("remote_two_matches_and_third_queued_replay", completed)
        standings = client("tournament", **remote_state)
        switch.transition(current, "local", backup_directory=directory / "cold-backup")
        assert client("complete", ids=ids)["matches"] == completed["matches"]
        assert client("tournament-persist", event_id=standings["event_id"])["sha256"] == standings["sha256"]
        record("remote_to_local_preserves_remote_results_replays_standings")
        local_again = client("schedule", **state, a="fast", b="wait")["ids"]
        client("complete", ids=local_again)
        record("original_local_artifact_volume_runs_new_official_after_rollback")
        report["result"] = "PASS"
    except Exception as exc:
        report["result"] = "FAIL"
        report["error_type"] = type(exc).__name__
        raise
    finally:
        # Stop only these two unique QA projects. No down/prune/volume deletion.
        for stack in (worker, cloud):
            stack.compose("stop", "--timeout", "30", check=False)
        # Use the current full model as well: the original local file can refer
        # to a stopped Controller while the last Arena is in remote mode.
        if current:
            current.compose("local", "stop", "--timeout", "30", "arena", "controller", "gateway")
        evidence.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("Evidence: " + str(evidence), flush=True)
        print("QA stopped; volumes and protected backups retained. NOT Internet acceptance.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true")
    main(parser.parse_args().build)
