"""Single-process local server; threaded bot IO avoids Windows event-loop restrictions."""
import argparse
import uvicorn
from backend.network import lan_addresses

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NEON ARENA local/LAN demo server")
    parser.add_argument("--host", default="0.0.0.0", help="Default: all local interfaces for LAN. Use 127.0.0.1 for one laptop.")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    print(f"\nNEON ARENA -> http://127.0.0.1:{args.port}", flush=True)
    if args.host == "0.0.0.0":
        for address in lan_addresses():
            print(f"LAN -> http://{address}:{args.port}", flush=True)
    print("Trusted group bots only. Ctrl+C to stop.\n", flush=True)
    uvicorn.run("backend.main:app", host=args.host, port=args.port, workers=1, reload=False)
