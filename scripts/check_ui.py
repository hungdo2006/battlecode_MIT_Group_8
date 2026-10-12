"""Legacy QA command, now runs the v3 three-browser invitation workflow."""
import argparse
import os
from check_multiplayer_ui import check

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--spectator-url", help="Retained CLI argument; all v3 participants use --url")
    args = parser.parse_args()
    check(args.url.rstrip("/"), os.environ["ARENA_ADMIN_CODE"])
