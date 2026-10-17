"""Isolated Docker Compose acceptance check (never uses normal app volumes).

Requires a built neon-arena:4.0 image, Docker Engine, and Python requirements.
Creates random QA project/volumes, verifies persistence, then removes only its
own labeled volumes. --browser also checks three Chrome sessions on the service.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import secrets
import subprocess
import tarfile
import tempfile
import time
from urllib.error import HTTPError

from backup_docker import backup
from check_lan import Player, invited_match, presence, watch

ROOT = Path(__file__).resolve().parent.parent


class DockerCheck:
    def __init__(self, lan_ip=None):
        self.project = "neon-arena-qa-" + secrets.token_hex(5)
        self.host = lan_ip or "127.0.0.1"
        self.code = secrets.token_urlsafe(32)
        self.env = {**os.environ, "ARENA_ADMIN_CODE": self.code, "ARENA_PORT": "0",
                    "ARENA_RUNNER_TOKEN": secrets.token_hex(32), "SANDBOX_NAMESPACE": self.project + "-test",
                    "ARENA_BIND_IP": "0.0.0.0", "ARENA_READ_ONLY": "0", "ARENA_ALLOWED_HOSTS": ""}
        self.volumes = []

    def compose(self, *args, capture=True):
        return subprocess.run(["docker", "compose", "--env-file", str(ROOT / ".env.example"),
                               "-f", str(ROOT / "compose.yaml"), "-p", self.project, *args],
                              cwd=ROOT, env=self.env, check=True, text=True,
                              capture_output=capture)

    def up(self):
        self.compose("up", "-d", "--no-build", "--wait", "--wait-timeout", "90")
        return self.refresh_url()

    def refresh_url(self):
        port = self.compose("port", "arena", "8000").stdout.strip().rsplit(":", 1)[1]
        self.url = f"http://{self.host}:{port}"
        return self.url

    def inspect(self):
        cid = self.compose("ps", "-q", "arena").stdout.strip()
        record = json.loads(subprocess.run(["docker", "inspect", cid], env=self.env,
                                          check=True, capture_output=True, text=True).stdout)[0]
        mounts = record["Mounts"]
        assert record["Config"]["User"] == "arena:arena"
        assert not record["HostConfig"]["Privileged"]
        assert record["State"]["Health"]["Status"] == "healthy"
        assert {m["Destination"] for m in mounts} == {"/app/data", "/app/uploads"}
        assert all(m["Type"] == "volume" and m["RW"] for m in mounts)
        self.volumes = [m["Name"] for m in mounts]
        cid = self.compose('ps', '-q', 'controller').stdout.strip()
        controller = json.loads(subprocess.run(['docker', 'inspect', cid], env=self.env,
            check=True, capture_output=True, text=True).stdout)[0]
        assert controller['Config']['User'] == '10001:10001'
        assert not controller['HostConfig']['PortBindings']
        assert not controller['HostConfig']['Privileged']
        networks = controller['NetworkSettings']['Networks']
        assert len(networks) == 1
        network_id = next(iter(networks.values()))['NetworkID']
        network = json.loads(subprocess.run(['docker', 'network', 'inspect', network_id], env=self.env,
            check=True, capture_output=True, text=True).stdout)[0]
        assert network['Internal'] is True
        return record["Id"]

    def uploads(self):
        script = "import json,hashlib; from pathlib import Path; root=Path('/app/uploads'); print(json.dumps({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()},sort_keys=True))"
        return json.loads(self.compose("exec", "-T", "arena", "python", "-c", script).stdout)

    def ready(self):
        self.compose("up", "-d", "--no-build", "--wait", "--wait-timeout", "90")
        self.refresh_url()
        player = Player(self.url)
        for _ in range(100):
            try:
                assert player.request("/api/health")["status"] == "ok"
                return
            except (OSError, AssertionError):
                time.sleep(0.2)
        raise RuntimeError("Container API did not become ready")

    def cleanup(self):
        # A random, tool-owned project; validate labels before deleting QA volumes.
        self.compose("down", "--timeout", "30")
        listed = subprocess.run(["docker", "volume", "ls", "--filter",
                                 "label=com.docker.compose.project=" + self.project, "--format", "{{.Name}}"],
                                env=self.env, check=True, capture_output=True, text=True)
        self.volumes = listed.stdout.split()
        for volume in self.volumes:
            record = json.loads(subprocess.run(["docker", "volume", "inspect", volume],
                env=self.env, check=True, capture_output=True, text=True).stdout)[0]
            assert record["Labels"]["com.docker.compose.project"] == self.project
            assert volume.startswith(self.project + "_")
            subprocess.run(["docker", "volume", "rm", volume], env=self.env, check=True, capture_output=True)


def denied(player, path, body):
    try:
        player.request(path, body)
        raise AssertionError(f"Permission bypass: {path}")
    except HTTPError as error:
        assert error.code == 403


async def matches(qa, org, a, b):
    records = []
    pairs = (("python", "cpp"), ("cpp", "java"), ("python", "java"))
    async with presence(org), presence(a), presence(b):
        for game in ("robot_battle", "ott_v2"):
            rules = {"max_turns": 100} if game == "robot_battle" else {"max_turns": 100, "rounds": 2}
            await asyncio.to_thread(org.prepare_competition, game, rules)
            for languages in pairs:
                bots = [await asyncio.to_thread(p.upload, game, lang, f"Docker {lang}")
                        for p, lang in zip((a, b), languages)]
                assert all(bot["status"] == "ready" for bot in bots), bots
                match = await invited_match(org, a, b, bots)
                streams = await asyncio.gather(*(watch(p, match["id"]) for p in (org, a, b)))
                replay = await asyncio.to_thread(a.request, f"/api/matches/{match['id']}/replay")
                assert streams[0] == streams[1] == streams[2]
                assert streams[0][0] == replay["frames"]
                assert replay["match"]["status"] == "completed", replay["match"]
                assert replay["match"]["result"]["reason"] != "bot_error"
                records.append({"game": game, "languages": languages, "id": match["id"],
                                "frames": len(replay["frames"]), "result": replay["match"]["result"]})
                print(f"PASS {game} {languages}: {match['id']} / {len(replay['frames'])} frames", flush=True)
            # Ensure completed bots have been fully cleaned up before the next invite.
            await asyncio.to_thread(org.prepare_competition, game, rules)
        # Invitation decline and one pending accept persisted across restart.
        ids = [(await asyncio.to_thread(p.request, "/api/session"))["participant"]["id"] for p in (a, b)]
        payload = dict(zip(("player_a_id", "player_b_id"), ids))
        inv = await asyncio.to_thread(org.request, "/api/invitations", payload)
        partial = await asyncio.to_thread(a.request, f"/api/invitations/{inv['id']}/accept", {})
        assert partial["status"] == "PARTIALLY_ACCEPTED" and not partial["match_id"]
        assert (await asyncio.to_thread(b.request, f"/api/invitations/{inv['id']}/decline", {}))["status"] == "DECLINED"
        pending = await asyncio.to_thread(org.request, "/api/invitations", payload)
        await asyncio.to_thread(a.request, f"/api/invitations/{pending['id']}/accept", {})
    return records, bots, pending["id"]


def verify_persistence(org, a, b, expected, hashes, qa):
    for player, identity in zip((org, a, b), expected["identities"]):
        session = player.request("/api/session")
        assert session["participant"] == identity and session["role"] == "player"
    actual = a.request("/api/competition")
    assert actual["competition_locked"] and actual["active_rules_snapshot"] == expected["rules"]
    assert {bot["id"] for bot in a.request("/api/bots")} == expected["bot_ids"]
    assert qa.uploads() == hashes  # source, C++ binary, Java classes and bytecode survived
    for mid, replay in expected["replays"].items():
        assert a.request(f"/api/matches/{mid}/replay") == replay
    assert a.request("/api/players/me")["active_bot_id"] == expected["active_a"]
    assert b.request("/api/players/me")["active_bot_id"] == expected["active_b"]
    assert not a.request("/api/players/me")["online"]
    invitations = a.request("/api/invitations")
    old = next(i for i in invitations if i["id"] == expected["pending"])
    assert old["status"] == "CANCELLED" and old["reason"] == "server_restart"


async def reuse(org, a, b, bots):
    async with presence(org), presence(a), presence(b):
        match = await invited_match(org, a, b, bots)
        streams = await asyncio.gather(*(watch(p, match["id"]) for p in (org, a, b)))
        assert streams[0] == streams[1] == streams[2]
        assert streams[0][1]["status"] == "completed", streams[0][1]
        assert streams[0][1]["result"]["reason"] != "bot_error"
    return match["id"]


def main(args):
    qa = DockerCheck(args.lan_ip)
    print(f"QA project: {qa.project} (separate named volumes)", flush=True)
    try:
        qa.up()
        original_id = qa.inspect()
        print(f"Compose healthy / non-root / named volumes: {qa.url}", flush=True)
        org, a, b = [Player(qa.url) for _ in range(3)]
        for p, name in ((org, "Docker Organizer"), (a, "Hoang"), (b, "Minh")):
            p.request("/api/session", {"name": name}, "PUT")
        org.request("/api/session/organizer", {"code": qa.code})
        assert "LIVE ARENA" in a.request("/", raw=True).decode()
        assert a.request("/api/health")["runner"]["mode"] == "sandbox"
        assert a.request("/api/health")["runner"]["ready"]
        assert a.request("/static/app.js", raw=True)
        denied(org, "/api/samples/python/submit", {})
        denied(a, "/api/invitations", {"player_a_id": "x", "player_b_id": "y"})
        denied(a, "/api/matches", {"bot_a": "x", "bot_b": "y"})
        # Existing script reads this only for its separate Organizer identity.
        before_code = os.environ.get("ARENA_ADMIN_CODE")
        os.environ["ARENA_ADMIN_CODE"] = qa.code
        try:
            records, bots, pending = asyncio.run(matches(qa, org, a, b))
        finally:
            if before_code is None: os.environ.pop("ARENA_ADMIN_CODE", None)
            else: os.environ["ARENA_ADMIN_CODE"] = before_code
        hashes = qa.uploads()
        expected = {"identities": [p.request("/api/session")["participant"] for p in (org, a, b)],
                    "rules": a.request("/api/competition")["active_rules_snapshot"],
                    "bot_ids": {bot["id"] for bot in a.request("/api/bots")},
                    "replays": {r["id"]: a.request(f"/api/matches/{r['id']}/replay") for r in records},
                    "active_a": bots[0]["id"], "active_b": bots[1]["id"], "pending": pending}
        qa.compose("restart", "arena")
        qa.ready()
        for p in (org, a, b): p.url = qa.url
        verify_persistence(org, a, b, expected, hashes, qa)
        print("PASS restart: sessions/settings/invitations/history/replays/source/artifacts", flush=True)
        org.request("/api/session/organizer", {"code": qa.code})
        reused_id = asyncio.run(reuse(org, a, b, bots))
        assert qa.uploads() == hashes
        expected["replays"][reused_id] = a.request(f"/api/matches/{reused_id}/replay")
        qa.compose("restart", "controller")
        qa.ready()
        for p in (org, a, b): p.url = qa.url
        controller_reuse = asyncio.run(reuse(org, a, b, bots))
        expected["replays"][controller_reuse] = a.request(f"/api/matches/{controller_reuse}/replay")
        print("PASS controller restart and artifact reuse", flush=True)
        # Restart metadata grant should be revoked again after container recreation.
        qa.compose("down", "--timeout", "30")
        qa.up()
        assert qa.inspect() != original_id
        # Ports assigned dynamically can change after down/up: keep cookie jars.
        for p in (org, a, b): p.url = qa.url
        verify_persistence(org, a, b, expected, hashes, qa)
        print("PASS down/up: new container, same volumes; compiled submissions reused", flush=True)
        qa.compose("stop", "arena", "controller")
        with tempfile.TemporaryDirectory(prefix="arena-volume-backup-") as folder:
            archive = backup(Path(folder) / "arena.tar.gz", qa.project, qa.env)
            with tarfile.open(archive, "r:gz") as stream:
                names = set(stream.getnames())
                assert {"data/bots.json", "data/matches.json", "data/sessions.json", "data/players.json",
                        "data/rules.json", "data/invitations.json"} <= names
                assert any(n.startswith("uploads/") and n.endswith(".cpp") for n in names)
                assert any(n.startswith("data/replays/") and n.endswith(".jsonl") for n in names)
                assert not any(n.endswith(".env") for n in names)
                assert any(n.startswith("artifacts/") and n.endswith(".tar") for n in names)
            from restore_docker import verify_bundle
            bundle = verify_bundle(archive)
            assert bundle['image_archive_sha256'] and bundle['manifest']['artifact_images']
            print(f"PASS verified three-volume backup + pinned images: {archive.stat().st_size} bytes", flush=True)
        if args.browser:
            qa.ready()
            from check_multiplayer_ui import check
            check(qa.url, qa.code, output_dir=ROOT / "docs/screenshots/sandbox")
        print(json.dumps({"docker": "PASS", "project": qa.project, "matches": records,
                          "restart": True, "down_up": True, "artifact_reuse_match": reused_id,
                          "backup": True}, ensure_ascii=False, indent=2))
    finally:
        qa.cleanup()
        print("Owned QA containers/network/volumes removed; normal app data untouched.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lan-ip", help="Host Wi-Fi IPv4 to exercise published LAN port")
    parser.add_argument("--browser", action="store_true", help="Also run Chrome 3-context QA")
    main(parser.parse_args())
