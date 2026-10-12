"""Legacy multi-client command, now checks Organizer + two Player browsers."""
import argparse
import os
from check_multiplayer_ui import check

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--game", choices=("robot_battle", "ott_v2"), default="robot_battle")
    args = parser.parse_args()
    check(args.url.rstrip("/"), os.environ["ARENA_ADMIN_CODE"], games=(args.game,))
