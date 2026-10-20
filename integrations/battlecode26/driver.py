"""Fixed worker protocol. Runs only inside the isolated Battlecode container."""
import ast
import base64
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import sys
import time

MAPS = ("DefaultSmall", "DefaultMedium", "DefaultLarge")
JAR = "/opt/battlecode/engine.jar"
MAX_SOURCE = 256 * 1024
MAX_RESULT = 12 * 1024 * 1024


def prepare(bot, side):
    source = base64.b64decode(bot["source"], validate=True)
    if not 0 < len(source) <= MAX_SOURCE:
        raise ValueError("Source must be 1..256 KiB")
    folder = Path("/work") / side
    package = folder / "arena"
    package.mkdir(parents=True)
    text = source.decode("utf-8")
    if bot["language"] == "py":
        parsed = ast.parse(text)
        if not any(isinstance(node, ast.FunctionDef) and node.name == "turn"
                   and not (node.args.args or node.args.posonlyargs or node.args.kwonlyargs or node.args.vararg or node.args.kwarg)
                   for node in parsed.body):
            raise ValueError("Python Battlecode bot needs a top-level turn() function")
        (package / "bot.py").write_bytes(source)
        return folder
    if bot["language"] != "java":
        raise ValueError("Battlecode supports Python and Java")
    if not re.search(r"\bpackage\s+arena\s*;", text):
        raise ValueError("Java bot must declare package arena and public class RobotPlayer")
    path = package / "RobotPlayer.java"
    path.write_bytes(source)
    result = subprocess.run(["javac", "-J-Xmx256m", "-encoding", "UTF-8", "-cp", JAR,
                             "-d", str(folder), str(path)], capture_output=True, timeout=30)
    if result.returncode:
        raise ValueError(result.stderr[:32768].decode("utf-8", errors="replace"))
    if not (package / 'RobotPlayer.class').is_file():
        raise ValueError('Expected package arena and public class RobotPlayer')
    methods = subprocess.run(['javap','-public','-classpath',str(folder),'arena.RobotPlayer'],capture_output=True,timeout=5)
    if not re.search(rb'public static void run\(battlecode\.common\.RobotController\)',methods.stdout):
        raise ValueError('Expected public static void run(RobotController rc)')
    return folder


def run(payload):
    operation = sys.argv[1]
    # The container also has cgroup limits; file size bounds prevent disk exhaustion.
    resource.setrlimit(resource.RLIMIT_FSIZE, (32*1024*1024, 32*1024*1024))
    if operation == "compile":
        prepare(payload, "compile")
        return {"status": "ready", "logs": "Validated against the pinned official Battlecode engine."}
    if operation != "match" or payload["map"] not in MAPS:
        raise ValueError("Unknown operation/map")
    folders = {side: prepare(payload[side], side) for side in ("A", "B")}
    python = any(payload[side]["language"] == "py" for side in ("A", "B"))
    bridge = None
    with open("/work/engine.log", "wb") as log:
        try:
            if python:
                bridge = subprocess.Popen([sys.executable, "-m", "battlecode26",
                    "--teamA", "arena" if payload["A"]["language"] == "py" else "/",
                    "--teamB", "arena" if payload["B"]["language"] == "py" else "/",
                    "--dirA", str(folders["A"]), "--dirB", str(folders["B"])], stdout=log, stderr=log)
            command = ["java", "-Xmx512m", "-XX:ActiveProcessorCount=2"]
            command.extend("--add-opens=java.base/" + part + "=ALL-UNNAMED" for part in (
                "jdk.internal.misc", "jdk.internal.math", "jdk.internal.util", "jdk.internal.access", "sun.security.action"))
            properties = {"bc.server.mode": "headless", "bc.server.websocket": "false",
                "bc.server.wait-for-client": "false", "bc.server.robot-player-to-system-out": "false",
                "bc.server.robot-player-replay-file-per-team-limit-bytes": "32768",
                "bc.engine.debug-methods": "false", "bc.engine.enable-profiler": "false",
                "bc.engine.show-indicators": "false", "bc.server.debug": "false",
                "bc.game.maps": payload["map"], "bc.server.validate-maps": "true",
                "bc.server.alternate-order": "false", "bc.server.save-file": "/work/match.bc26"}
            for side in ("A", "B"):
                prefix = "bc.game.team-" + side.lower()
                properties.update({prefix: "Arena" + side, prefix + ".language": "python" if payload[side]["language"] == "py" else "java",
                    prefix + ".url": str(folders[side]), prefix + ".package": "arena"})
            command.extend("-D" + key + "=" + value for key, value in properties.items())
            command.extend(["-cp", JAR, "battlecode.server.Main", "-c=-"])
            subprocess.run(command, stdout=log, stderr=log, check=True, timeout=150)
            if not Path("/work/match.bc26").is_file():
                raise RuntimeError("Official engine did not produce a replay")
            subprocess.run(["java", "-Xmx512m", "-cp", JAR + ":/opt/arena", "ArenaReplay",
                "/work/match.bc26", "/work/replay.json"], stdout=log, stderr=log, check=True, timeout=20)
        finally:
            if bridge:
                bridge.terminate()
                try:
                    bridge.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    bridge.kill(); bridge.wait()
    if Path("/work/replay.json").stat().st_size > MAX_RESULT:
        raise RuntimeError("Official replay exceeds supported visualization size")
    replay = json.loads(Path("/work/replay.json").read_text())
    replay["raw_replay"] = base64.b64encode(Path("/work/match.bc26").read_bytes()).decode()
    return replay


if __name__ == "__main__":
    try:
        request = sys.stdin.buffer.readline(800000)
        result = run(json.loads(request))
    except (ValueError, SyntaxError, UnicodeError) as error:
        result = {"status": "error", "logs": str(error)[:32768]}
    except Exception as error:
        diagnostics = Path("/work/engine.log")
        result = {"infrastructure_error": str(error), "logs": diagnostics.read_bytes()[-32768:].decode("utf-8", errors="replace") if diagnostics.is_file() else ""}
    print(json.dumps(result, separators=(",", ":")))
