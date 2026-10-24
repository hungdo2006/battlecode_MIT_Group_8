"""Disposable, one-laptop B1 PC worker Docker smoke (NOT cloud/WAN E2E).

Builds a random isolated Compose project, runs the real outbound agent's
allowlisted Controller forwarding, compiles a real Python bot in Sandbox,
opens a runtime, requests an action and closes it. Then checks that
only Controller (never agent) can access Docker Engine.

Invoke from repo root:
    .\\.venv\\Scripts\\python.exe scripts/check_remote_worker_docker.py --build

No AWS, hostname, Tailscale, real secrets, internet domain, or Arena database.
A deliberately non-resolving HTTPS URL is used solely as a safe placeholder
to keep the background agent disconnected during this LOCAL worker smoke.
This does NOT prove the remote Cloud/TLS/Official Match integration.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
QA_PREFIX = "neon-b1-worker-qa"
QA_IMAGES = {
    "bot-image": "neon-b1-qa-bot:local",
    "controller": "neon-b1-qa-controller:local",
    "agent": "neon-b1-qa-agent:local",
}

# Code executed inside the isolated Docker agent container. Only the Controller
# sees the local PC Docker socket; the agent exercises the same allowlisted RPC
# transport it would forward when connected to the cloud.
EXERCISE_AGENT = """
import base64, json, secrets
from remote_runner.agent import WorkerAgent

agent = WorkerAgent()
owner = secrets.token_hex(16)
job = 'c-' + secrets.token_hex(12)
runtime = 'r-' + secrets.token_hex(12)
lease = None

def call(path, payload=None):
    status, body = agent.controller({'path': path, 'payload': payload})
    if status != 200:
        raise AssertionError('Private Controller RPC failed: ' + path + ', HTTP ' + str(status))
    return body

try:
    health = call('/health')
    assert health['ready'] and health['sandbox_image']
    lease = call('/owner', {'owner': owner, 'epoch': health['epoch']})['lease']
    headers = {'owner': owner, 'lease': lease}
    source = b'import json,sys\\nfor line in sys.stdin: print(json.dumps({"type":"wait"}),flush=True)\\n'
    compiled = call('/compile/' + job, {
        **headers, 'language': 'py', 'source': base64.b64encode(source).decode('ascii')})
    assert compiled['artifact_id'] and compiled['artifact_digest']
    call('/runtime/' + runtime, {**headers,
        'artifact_id': compiled['artifact_id'],
        'artifact_digest': compiled['artifact_digest']})
    observation = {
        'game_id': 'robot_battle', 'turn': 0, 'protocol': 1,
        'player': 'A', 'you': {'x': 1, 'y': 1, 'hp': 100},
        'enemy': {'x': 9, 'y': 1, 'hp': 100},
        'rules': {'map_size': 12, 'max_turns': 100,
                  'initial_hp': 100, 'damage': 20},
    }
    decision = call('/runtime/' + runtime + '/request',
        {**headers, 'seq': 0, 'observation': observation})
    assert decision['action'] == {'type': 'wait'}
    print(json.dumps({'agent_to_controller': 'PASS',
        'real_docker_compile': 'PASS',
        'real_docker_runtime': 'PASS'}), flush=True)
finally:
    if lease:
        try:
            call('/close/' + runtime, {'owner': owner, 'lease': lease})
        finally:
            call('/release', {'owner': owner, 'lease': lease})
"""


def qa_project(nonce):
    if not (isinstance(nonce, str) and len(nonce) == 10
            and all(ch in "0123456789abcdef" for ch in nonce)):
        raise ValueError("Refusing invalid QA identifier")
    return QA_PREFIX + "-" + nonce


def isolated_env(project):
    if not project.startswith(QA_PREFIX + "-") or len(project) != len(QA_PREFIX) + 11:
        raise ValueError("Refusing non-QA Docker project")
    # Never pass the operator's actual Arena/Runner keys, SMTP credentials or
    # existing namespaces into the throwaway worker.
    host = {k: v for k, v in os.environ.items()
            if not k.startswith("ARENA_") and k != "SANDBOX_NAMESPACE"}
    return {
        **host,
        "ARENA_REMOTE_SERVER_URL": "https://qa-disconnected.invalid",
        "ARENA_REMOTE_RUNNER_KEY": secrets.token_hex(32),
        "ARENA_RUNNER_TOKEN": secrets.token_hex(32),
        "SANDBOX_NAMESPACE": project + "-bots",
        "DOCKER_SOCKET_GID": os.environ.get("DOCKER_SOCKET_GID", "0"),
    }


class WorkerQA:
    def __init__(self, folder, nonce):
        self.project = qa_project(nonce)
        self.env = isolated_env(self.project)
        override = Path(folder) / "worker-smoke.json"
        override.write_text(json.dumps({"services": {
            "bot-image": {"image": QA_IMAGES["bot-image"]},
            "controller": {"image": QA_IMAGES["controller"], "environment": {
                "SANDBOX_NAMESPACE": self.env["SANDBOX_NAMESPACE"],
                "SANDBOX_IMAGE": QA_IMAGES["bot-image"],
            }},
            "agent": {"image": QA_IMAGES["agent"]},
        }}), encoding="utf-8")
        self.command = [
            "docker", "compose", "--env-file", str(ROOT / ".env.example"),
            "-f", str(ROOT / "compose.remote-worker.yaml"),
            "-f", str(override), "-p", self.project,
        ]

    def compose(self, *args, check=True):
        result = subprocess.run(self.command + list(args), cwd=ROOT, env=self.env,
                                text=True, capture_output=True)
        if check and result.returncode != 0:
            # Never print the raw Docker inspect/config output: it contains
            # temporary bearer secrets even in an otherwise safe local test.
            raise RuntimeError("QA worker Docker operation failed: " + args[0]
                               + " (exit=" + str(result.returncode) + ")")
        return result

    def container(self, service):
        identifier = self.compose("ps", "-q", service).stdout.strip()
        if not identifier:
            raise AssertionError("Expected running QA service: " + service)
        result = subprocess.run(["docker", "inspect", identifier], cwd=ROOT,
                                env=self.env, text=True, capture_output=True, check=True)
        return json.loads(result.stdout)[0]

    def assert_sandbox_isolation(self):
        controller = self.container("controller")
        agent = self.container("agent")
        assert controller["State"]["Health"]["Status"] == "healthy"
        assert controller["Config"]["User"] == "10001:10001"
        assert not controller["HostConfig"]["Privileged"]
        assert not controller["HostConfig"]["PortBindings"]
        assert controller["HostConfig"]["ReadonlyRootfs"]
        mounted = {m["Destination"] for m in controller["Mounts"]}
        assert "/var/run/docker.sock" in mounted
        networks = controller["NetworkSettings"]["Networks"]
        assert len(networks) == 1
        net_id = next(iter(networks.values()))["NetworkID"]
        net = json.loads(subprocess.run(["docker", "network", "inspect", net_id],
                         cwd=ROOT, env=self.env, text=True, capture_output=True,
                         check=True).stdout)[0]
        assert net["Internal"] is True
        assert not agent["HostConfig"]["Privileged"]
        assert not agent["HostConfig"]["PortBindings"]
        assert agent["HostConfig"]["ReadonlyRootfs"]
        assert all(m["Destination"] != "/var/run/docker.sock" for m in agent["Mounts"])
        assert len(agent["NetworkSettings"]["Networks"]) == 2
        print("PASS worker isolation: private Controller, non-root, no exposed ports,"
              " agent without Docker socket", flush=True)

    def run(self, build):
        if build:
            self.compose("build")
        else:
            for image in QA_IMAGES.values():
                if subprocess.run(["docker", "image", "inspect", image], cwd=ROOT,
                                  env=self.env, capture_output=True).returncode:
                    raise RuntimeError("B1 QA images missing; rerun with --build")
        self.compose("up", "-d", "--no-build", "--wait", "--wait-timeout", "120")
        self.assert_sandbox_isolation()
        # Run against the actual Controller from inside the agent network,
        # with no outbound Cloud secret or Docker Engine mounts added.
        cmd = self.command + ["exec", "-T", "agent", "python", "-c", EXERCISE_AGENT]
        process = subprocess.run(cmd, cwd=ROOT, env=self.env, text=True,
                                 capture_output=True)
        if process.returncode != 0:
            # Python exception type and path are safe, but raw stderr could
            # include an authorization header in third-party error messages.
            raise RuntimeError("Real PC agent/Controller bot execution FAILED "
                               "(inspect only QA container logs locally)")
        report = json.loads(process.stdout.strip().splitlines()[-1])
        assert report == {
            "agent_to_controller": "PASS",
            "real_docker_compile": "PASS",
            "real_docker_runtime": "PASS",
        }
        print(json.dumps({**report, "b1_worker_smoke": "PASS"},
                         ensure_ascii=False, indent=2), flush=True)

    def cleanup(self):
        self.compose("down", "--timeout", "30", check=False)
        volumes = subprocess.run([
            "docker", "volume", "ls",
            "--filter", "label=com.docker.compose.project=" + self.project,
            "--format", "{{.Name}}",
        ], cwd=ROOT, env=self.env, text=True, capture_output=True, check=True)
        for volume in volumes.stdout.splitlines():
            record = json.loads(subprocess.run(
                ["docker", "volume", "inspect", volume], cwd=ROOT, env=self.env,
                text=True, capture_output=True, check=True).stdout)[0]
            if (not volume.startswith(self.project + "_") or
                    record.get("Labels", {}).get("com.docker.compose.project") != self.project):
                raise RuntimeError("Refusing to delete a non-QA volume")
            subprocess.run(["docker", "volume", "rm", volume], cwd=ROOT,
                           env=self.env, text=True, capture_output=True, check=True)


def main(build):
    with tempfile.TemporaryDirectory(prefix="neon-b1-worker-smoke-") as folder:
        qa = WorkerQA(folder, secrets.token_hex(5))
        print("QA PC worker project:", qa.project, flush=True)
        try:
            qa.run(build)
        finally:
            try:
                qa.cleanup()
            except Exception:
                print("WARNING: QA cleanup incomplete; inspect " + qa.project,
                      flush=True)
            print("QA worker project stopped; no production volumes touched.",
                  flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="Build isolated QA worker images")
    main(parser.parse_args().build)
