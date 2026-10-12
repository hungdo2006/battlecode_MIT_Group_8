"""Single-process local server; threaded bot IO avoids Windows event-loop restrictions."""
import argparse
import os
import uvicorn
from backend.network import NetworkSettings, lan_addresses

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NEON ARENA local/LAN demo server")
    parser.add_argument("--host", default=os.environ.get("ARENA_HOST", "0.0.0.0"), help="Default: all local interfaces for LAN.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("ARENA_PORT", "8000")))
    parser.add_argument("--proxy-headers", action="store_true", help="Trust forwarded scheme/client IP only from configured proxy IPs.")
    parser.add_argument("--forwarded-allow-ips", default="127.0.0.1", help="Trusted proxy IPs; avoid '*' on a LAN listener.")
    args = parser.parse_args()
    settings = NetworkSettings.from_environment()  # Fail early on unsafe public-host configuration.
    print(f"\nNEON ARENA -> http://127.0.0.1:{args.port}", flush=True)
    if args.host == "0.0.0.0":
        for address in lan_addresses():
            print(f"LAN -> http://{address}:{args.port}", flush=True)
    print("Trusted group bots only. Ctrl+C to stop.\n", flush=True)
    print("Mode: " + ("READ ONLY" if settings.read_only else "TRUSTED LAN"), flush=True)
    uvicorn.run("backend.main:app", host=args.host, port=args.port, workers=1, reload=False,
                proxy_headers=args.proxy_headers, forwarded_allow_ips=args.forwarded_allow_ips)
