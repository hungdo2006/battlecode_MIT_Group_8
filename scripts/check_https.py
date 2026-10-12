"""Optional real TLS HTTPS/WSS smoke check using OpenSSL, isolated temporary data.

Does not publish anything, change certificates/firewall, or run bot code. It
serves a real completed replay from this workspace on an ephemeral loopback port.
"""
import argparse
import asyncio
from http.cookiejar import CookieJar
import json
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import time
from urllib.error import HTTPError
from urllib.request import HTTPSHandler, HTTPCookieProcessor, ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import uvicorn
from websockets.asyncio.client import connect
from backend.main import create_app
from backend.network import NetworkSettings


async def watch(base, match_id, context, cookie):
    frames = []
    async with connect(base.replace("https://", "wss://") + f"/ws/matches/{match_id}",
                       ssl=context, origin=base, additional_headers={"Cookie": cookie}) as socket:
        async for raw in socket:
            message = json.loads(raw)
            if message["type"] == "state":
                assert message["seq"] == len(frames)
                frames.append(message["state"])
            if message["type"] == "complete":
                return frames
    raise AssertionError("WSS closed before complete")


async def competition_state(base, context, cookie):
    async with connect(base.replace("https://", "wss://") + "/ws/competition", ssl=context,
                       origin=base, additional_headers={"Cookie": cookie}) as socket:
        message = json.loads(await socket.recv())
        assert message["type"] == "competition"
        return message["state"]


def main(args):
    openssl = shutil.which("openssl")
    if not openssl:
        raise SystemExit("Optional check requires openssl on PATH; not required to run the LAN app.")
    matches = json.loads((ROOT / "data/matches.json").read_text(encoding="utf-8"))
    match = matches[args.match_id]
    assert match["status"] == "completed", "Use a real completed match."
    with TemporaryDirectory(prefix="arena-tls-") as folder:
        temporary = Path(folder)
        data = temporary / "data"
        (data / "replays").mkdir(parents=True)
        (data / "matches.json").write_text(json.dumps({match["id"]: match}), encoding="utf-8")
        shutil.copy2(ROOT / "data/rules.json", data / "rules.json")
        replay = ROOT / f"data/replays/{match['id']}.jsonl"
        if not replay.exists():
            replay = replay.with_suffix(".json")
        shutil.copy2(replay, data / "replays" / replay.name)
        cert, key = temporary / "cert.pem", temporary / "key.pem"
        subprocess.run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-sha256", "-nodes",
                        "-keyout", str(key), "-out", str(cert), "-days", "1", "-subj", "/CN=localhost",
                        "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1"],
                       check=True, capture_output=True, timeout=15)
        context = ssl.create_default_context(cafile=str(cert))  # Verify, don't disable TLS checks.
        app = create_app(temporary, network=NetworkSettings(read_only=True, allowed_hosts=("arena.example.com",)))
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, ssl_certfile=str(cert),
                                               ssl_keyfile=str(key), log_level="error", proxy_headers=False))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                if not thread.is_alive() or time.monotonic() > deadline:
                    raise RuntimeError("TLS server did not start")
                time.sleep(0.05)
            port = server.servers[0].sockets[0].getsockname()[1]
            base = f"https://127.0.0.1:{port}"
            jar = CookieJar()
            opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context), HTTPCookieProcessor(jar))

            def get(path):
                with opener.open(base + path, timeout=10) as response:
                    return json.load(response)

            participant = get("/api/session")["participant"]
            assert get("/api/session")["participant"] == participant
            assert next(iter(jar)).secure
            cookie_request = Request(base + "/")
            jar.add_cookie_header(cookie_request)
            frames = asyncio.run(watch(base, match["id"], context, cookie_request.get_header("Cookie")))
            assert frames == get(f"/api/matches/{match['id']}/replay")["frames"]
            assert asyncio.run(competition_state(base, context, cookie_request.get_header("Cookie"))) == get("/api/competition")
            try:
                opener.open(Request(base + "/api/bots", data=b"", method="POST"), timeout=10)
                raise AssertionError("Read-only HTTPS accepted upload")
            except HTTPError as exc:
                assert exc.code == 403
            print(f"HTTPS/WSS PASS: verified TLS; Secure cookie; {len(frames)} replay frames; competition WSS equals REST; read-only upload blocked.")
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            assert not thread.is_alive(), "Owned TLS server must stop."


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-id", required=True)
    main(parser.parse_args())
