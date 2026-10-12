import sys
from pathlib import Path

import pytest

from backend.engine.robot import RobotBattle
from backend.engine.robot import RobotRules as Rules
from backend.runner import BotError, BotProcess, prepare_submission, tool

ROOT = Path(__file__).resolve().parent.parent


def process(tmp_path, code):
    source = tmp_path / "bot.py"
    source.write_text(code, encoding="utf-8")
    return BotProcess([sys.executable, "-u", str(source)], tmp_path)


def test_persistent_python_bot(tmp_path):
    bot = process(tmp_path, "import sys,json\nfor line in sys.stdin:\n print(json.dumps({'type':'wait'}),flush=True)\n")
    try:
        pid = bot.proc.pid
        for _ in range(3):
            assert bot.request({"turn": 0}, timeout=2) == {"type": "wait"}
        assert bot.proc.pid == pid
    finally:
        bot.close()
    assert bot.proc.poll() is not None


def test_python_runner_owns_real_pid_and_preserves_venv(tmp_path):
    bot = process(tmp_path, "import os,sys,json\nfor line in sys.stdin:\n print(json.dumps({'pid':os.getpid(),'prefix':sys.prefix}),flush=True)\n")
    try:
        response = bot.request({}, timeout=2)
        assert response["pid"] == bot.proc.pid, "Windows venv must not hide the bot behind a launcher"
        assert Path(response["prefix"]) == Path(sys.prefix)
    finally:
        bot.close()


def test_unicode_json_output_uses_utf8_on_windows(tmp_path):
    bot = process(tmp_path, "import sys,json\nfor line in sys.stdin:\n print(json.dumps({'message':'Chào'},ensure_ascii=False),flush=True)\n")
    try:
        assert bot.request({}, timeout=2) == {"message": "Chào"}
    finally:
        bot.close()


def test_server_admin_code_is_not_in_bot_or_compiler_environment(tmp_path, monkeypatch):
    from backend.runner import direct_python_launch
    monkeypatch.setenv("ARENA_ADMIN_CODE", "private-organizer-credential")
    monkeypatch.setenv("ARENA_BOT_TEST_VALUE", "keep-normal-environment")
    bot = process(tmp_path, "import os,sys,json\nfor line in sys.stdin:\n print(json.dumps({'has_admin_code':'ARENA_ADMIN_CODE' in os.environ,'normal':os.environ.get('ARENA_BOT_TEST_VALUE')}),flush=True)\n")
    try:
        assert bot.request({}, timeout=2) == {"has_admin_code": False, "normal": "keep-normal-environment"}
    finally:
        bot.close()
    _, environment = direct_python_launch(["g++", "--version"])
    assert "ARENA_ADMIN_CODE" not in environment


def test_timeout_kills_bot(tmp_path):
    bot = process(tmp_path, "import time\ntime.sleep(30)\n")
    try:
        with pytest.raises(BotError, match="timeout"):
            bot.request({}, timeout=0.15)
    finally:
        bot.close()
    assert bot.proc.poll() is not None


def test_crash_does_not_hang(tmp_path):
    bot = process(tmp_path, "raise RuntimeError('boom')\n")
    try:
        with pytest.raises(BotError):
            bot.request({}, timeout=2)
    finally:
        bot.close()


@pytest.mark.parametrize("output", ["not json", '{"type":NaN}', "\\xff"])
def test_bad_json(tmp_path, output):
    code = "import sys\nfor line in sys.stdin:\n print(" + repr(output) + ",flush=True)\n"
    bot = process(tmp_path, code)
    try:
        with pytest.raises(BotError, match="JSON"):
            bot.request({}, timeout=2)
    finally:
        bot.close()


def test_large_stdout_is_rejected(tmp_path):
    bot = process(tmp_path, "import sys,time\nfor line in sys.stdin:\n print('x'*7000,flush=True)\n")
    try:
        with pytest.raises(BotError, match="giới hạn"):
            bot.request({}, timeout=2)
    finally:
        bot.close()


def test_stderr_limit_is_enforced(tmp_path):
    bot = process(tmp_path, "import sys,time\nfor line in sys.stdin:\n sys.stderr.write('x'*100000);sys.stderr.flush();time.sleep(5)\n")
    try:
        with pytest.raises(BotError, match="stderr"):
            bot.request({}, timeout=2)
    finally:
        bot.close()


def test_syntax_failure_and_invalid_upload(tmp_path):
    status, logs, command = prepare_submission(b"def broken(:\n", "code.py", tmp_path / "broken")
    assert status == "error" and "SyntaxError" in logs and command == []
    with pytest.raises(ValueError):
        prepare_submission(b"code", "test.txt", tmp_path / "invalid")
    with pytest.raises(ValueError):
        prepare_submission(b"x" * (256 * 1024 + 1), "test.py", tmp_path / "large")


@pytest.mark.parametrize("filename,compiler", [("hunter.cpp", "g++"), ("Main.java", "javac")])
def test_compiled_sample_uses_same_process_for_multiple_turns(tmp_path, filename, compiler):
    if not tool(compiler) or (compiler == "javac" and not tool("java")):
        pytest.skip(f"Missing {compiler}")
    status, logs, command = prepare_submission((ROOT / "samples" / filename).read_bytes(), filename, tmp_path)
    assert status == "ready", logs
    bot = BotProcess(command, tmp_path)
    try:
        game = RobotBattle(Rules())
        pid = bot.proc.pid
        for _ in range(3):
            action = bot.request(game.observation("B"))
            assert game.validate_action(action)["type"] == "move"
        assert bot.proc.pid == pid
    finally:
        bot.close()
