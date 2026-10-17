"""Container readiness without curl, credentials or extra Python dependencies."""
import json
from urllib.request import ProxyHandler, build_opener


def main():
    opener = build_opener(ProxyHandler({}))
    with opener.open("http://127.0.0.1:8000/api/health", timeout=3) as response:
        state = json.load(response)
    if state.get("status") != "ok" or not all(
            state.get("toolchains", {}).get(key) for key in ("python", "cpp", "javac", "java")):
        raise SystemExit("API/toolchains are not ready")


if __name__ == "__main__":
    main()
