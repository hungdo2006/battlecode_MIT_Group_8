"""Run real official-engine acceptance in disposable networkless containers."""
import base64
import json
import subprocess
from pathlib import Path

JAVA_RESIGN = b"package arena; import battlecode.common.*; public class RobotPlayer { public static void run(RobotController rc) { rc.resign(); } }"
JAVA_WAIT = b"package arena; import battlecode.common.*; public class RobotPlayer { public static void run(RobotController rc) { while(true) Clock.yield(); } }"
PY_RESIGN = b"def turn():\n    if rc.get_round_num() >= 3:\n        rc.resign()\n"
PY_WAIT = b"def turn():\n    pass\n"


def bot(language, source):
    return {"language": language, "source": base64.b64encode(source).decode()}


def worker(operation, payload):
    command = ["docker", "run", "--rm", "-i", "--network=none", "--read-only",
        "--user=10001:10001", "--memory=1g", "--memory-swap=1g", "--cpus=2", "--pids-limit=256",
        "--cap-drop=ALL", "--security-opt=no-new-privileges:true",
        "--tmpfs=/work:rw,nosuid,nodev,size=256m,uid=10001,gid=10001,mode=0700",
        "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=64m,uid=10001,gid=10001,mode=0700",
        "neon-arena-battlecode:2026", "python", "/opt/arena/driver.py", operation]
    completed = subprocess.run(command, input=json.dumps(payload).encode()+b"\n",
                               capture_output=True, timeout=190)
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    result = json.loads(completed.stdout)
    assert not result.get("infrastructure_error"), result
    return result


def run():
    root = Path(__file__).resolve().parent.parent
    for language, source in (("py", b"def turn(rc):\n    pass\n"),
                             ("java", b"package arena; public class RobotPlayer {}"),
                             ("java", b"/* package arena; */ public class RobotPlayer { public static void run() {} }")):
        result = worker("compile", bot(language, source))
        assert result.get("status") == "error", result
    for language, path in (("py", "bot.py"), ("java", "RobotPlayer.java")):
        result = worker("compile", bot(language, (root / "samples/battlecode26" / path).read_bytes()))
        assert result.get("status") == "ready", result
    print("PASS starter compilation and invalid entrypoint rejection", flush=True)
    # Execute both published starter APIs for several turns, then end deterministically.
    sample_py = (root / "samples/battlecode26/bot.py").read_bytes().replace(
        b"def turn():", b"def turn():\n    if rc.get_round_num() >= 5:\n        rc.resign()\n        return")
    sample_java = (root / "samples/battlecode26/RobotPlayer.java").read_bytes()
    results = []
    for label, first, second, winner in (
        ("java-java", bot("java", JAVA_RESIGN), bot("java", JAVA_WAIT), "B"),
        ("python-java", bot("py", PY_RESIGN), bot("java", JAVA_WAIT), "B"),
        ("python-python", bot("py", PY_WAIT), bot("py", PY_RESIGN), "A"),
        ("published-starter-apis", bot("py", sample_py), bot("java", sample_java), "B"),
    ):
        payload = worker("match", {"map": "DefaultSmall", "A": first, "B": second})
        assert payload.get("result", {}).get("winner") == winner, payload
        assert payload["result"]["reason"] == "RESIGNATION", payload
        assert payload["frames"] and payload["frames"][-1]["result"] == payload["result"]
        assert payload["board"]["width"] > 0
        assert base64.b64decode(payload["raw_replay"]).startswith(b"\x1f\x8b")
        assert all(0 <= score['kings'] <= 5 and score['cheese'] >= 0
                   for frame in payload['frames'][1:] for score in frame['scores'].values())
        if label == 'published-starter-apis':
            positions = {unit['id']:(unit['x'],unit['y']) for unit in payload['frames'][0]['units']}
            assert any((unit['x'],unit['y']) != positions.get(unit['id'])
                       for frame in payload['frames'][1:] for unit in frame['units']), 'Starter bots did not move'
        results.append({"case": label, "winner": winner, "reason": payload["result"]["reason"], "frames": len(payload["frames"])})
        print("PASS", json.dumps(results[-1]), flush=True)
    print("PASS official Battlecode engine Java/Python + decoded replay + raw .bc26", flush=True)


if __name__ == "__main__":
    run()
