"""Portable subprocess + threaded pipes (works with Windows' asyncio event loop).

This is NOT a sandbox. Only run trusted group submissions on your own computer.
"""
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from time import monotonic

MAX_SOURCE_BYTES = 256 * 1024
MAX_LINE_BYTES = 4096
MAX_STDOUT_BYTES = 256 * 1024
MAX_STDERR_BYTES = 64 * 1024
TURN_TIMEOUT = 1.0
STARTUP_TIMEOUT = 3.0
COMPILE_TIMEOUT = 30.0
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


class BotError(RuntimeError):
    pass


def reject_constant(value: str):
    raise ValueError(f"Non-finite number is not valid JSON: {value}")


def jdk_bin() -> Path | None:
    """Prefer a matching java/javac pair; a JRE in PATH cannot compile Java."""
    suffix = ".exe" if os.name == "nt" else ""
    candidates = []
    if os.environ.get("JAVA_HOME"):
        candidates.append(Path(os.environ["JAVA_HOME"]) / "bin")
    compiler = shutil.which("javac")
    if compiler:
        candidates.append(Path(compiler).resolve().parent)
    if os.name == "nt":
        program_files = Path(os.environ.get("ProgramFiles", "C:/Program Files"))
        local_programs = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs"
        # A few conventional install locations; no registry changes or global PATH edits.
        for root, pattern in [(program_files / "Java", "*/bin"),
                              (program_files / "Eclipse Adoptium", "*/bin"),
                              (program_files / "JetBrains", "IntelliJ*/jbr/bin"),
                              (local_programs, "IntelliJ*/jbr/bin")]:
            candidates.extend(sorted(root.glob(pattern), reverse=True))
    for candidate in candidates:
        if all((candidate / (name + suffix)).is_file() for name in ("java", "javac")):
            return candidate
    return None


def tool(name: str) -> str | None:
    if name in ("java", "javac"):
        bindir = jdk_bin()
        if bindir:
            return str(bindir / (name + (".exe" if os.name == "nt" else "")))
    return shutil.which(name)


def toolchains() -> dict:
    return {"python": sys.executable, "cpp": tool("g++"),
            "javac": tool("javac"), "java": tool("java")}


def direct_python_launch(command: list[str]) -> tuple[list[str], dict | None]:
    """Avoid the Windows venv redirector: kill() must own the actual interpreter.

    __PYVENV_LAUNCHER__ preserves the venv's packages while launching its base
    interpreter directly, following CPython's own Windows multiprocessing code.
    Stored commands remain portable within the current project's environment.
    """
    args = list(command)
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"
    if (os.name == "nt" and sys.prefix != sys.base_prefix
            and Path(args[0]).resolve() == Path(sys.executable).resolve()):
        args[0] = getattr(sys, "_base_executable", sys.executable)
        environment["__PYVENV_LAUNCHER__"] = sys.executable
    return args, environment


def compile_command(command: list[str], cwd: Path) -> tuple[bool, str]:
    """Drain diagnostics continuously, with a byte cap and a hard time limit."""
    try:
        args, environment = direct_python_launch(command)
        proc = subprocess.Popen(args, cwd=cwd, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
    except OSError as exc:
        return False, str(exc)
    captured = bytearray()
    overflow = threading.Event()

    def drain():
        while chunk := proc.stdout.read1(2048):
            remaining = 32 * 1024 - len(captured)
            captured.extend(chunk[:max(0, remaining)])
            if len(chunk) > remaining:
                overflow.set()
                proc.kill()
                break

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    timed_out = False
    try:
        proc.wait(timeout=COMPILE_TIMEOUT)
    except subprocess.TimeoutExpired:
        timed_out = True
        proc.kill()
        proc.wait(timeout=2)
    reader.join(timeout=2)
    diagnostics = captured.decode("utf-8", errors="replace")
    if timed_out:
        diagnostics += "\nBiên dịch vượt quá giới hạn 30 giây."
    if overflow.is_set():
        diagnostics += "\nCompiler output vượt 32 KiB."
    if not reader.is_alive():
        proc.stdout.close()
    return proc.returncode == 0 and not timed_out and not overflow.is_set(), diagnostics


def prepare_submission(source: bytes, filename: str, folder: Path) -> tuple[str, str, list[str]]:
    """One compile per upload; the stored command is reused for every turn/match."""
    extension = Path(filename).suffix.lower()
    if extension not in (".py", ".cpp", ".java"):
        raise ValueError("Chỉ hỗ trợ .py, .cpp và .java.")
    if not source or len(source) > MAX_SOURCE_BYTES:
        raise ValueError("File phải có nội dung và không vượt quá 256 KiB.")
    folder.mkdir(parents=True, exist_ok=True)
    # Use fixed filenames, never a client-controlled path. Java has a fixed public class.
    source_path = folder / ("Main.java" if extension == ".java" else "bot" + extension)
    source_path.write_bytes(source)
    if extension == ".py":
        success, logs = compile_command([sys.executable, "-m", "py_compile", str(source_path)], folder)
        command = [sys.executable, "-u", str(source_path)]
    elif extension == ".cpp":
        compiler = tool("g++")
        if not compiler:
            return "error", "Không tìm thấy g++. Hãy cài MinGW-w64 và thêm bin vào PATH.", []
        executable = folder / ("bot.exe" if os.name == "nt" else "bot")
        success, logs = compile_command([compiler, "-std=c++17", "-O2", str(source_path), "-o", str(executable)], folder)
        command = [str(executable)]
    else:
        compiler, runtime = tool("javac"), tool("java")
        if not compiler or not runtime:
            return "error", "Thiếu JDK: cần cả javac và java. Thiết lập JAVA_HOME tới thư mục JDK.", []
        success, logs = compile_command([compiler, "-encoding", "UTF-8", str(source_path)], folder)
        command = [runtime, "-Xmx64m", "-cp", str(folder), "Main"]
    return ("ready" if success else "error"), logs, (command if success else [])


class BotProcess:
    def __init__(self, command: list[str], cwd: Path):
        self.proc: subprocess.Popen | None = None
        self.outputs: queue.Queue = queue.Queue(maxsize=8)
        self.inputs: queue.Queue = queue.Queue(maxsize=1)
        self.error: str | None = None
        self.error_lock = threading.Lock()
        self.stderr = bytearray()
        self.threads: list[threading.Thread] = []
        self.requests = 0
        try:
            args, environment = direct_python_launch(command)
            self.proc = subprocess.Popen(args, cwd=cwd, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, creationflags=NO_WINDOW)
        except OSError as exc:
            raise BotError(f"Không thể khởi chạy bot: {exc}") from exc
        for target in (self._write_input, self._read_output, self._read_error):
            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            self.threads.append(thread)

    def _fail(self, message: str):
        with self.error_lock:
            if self.error is None:
                self.error = message
        if self.proc.poll() is None:
            try:
                self.proc.kill()
            except OSError:
                pass
        try:
            self.outputs.put_nowait(None)
        except queue.Full:
            pass

    def _write_input(self):
        try:
            while True:
                payload = self.inputs.get()
                if payload is None:
                    return
                self.proc.stdin.write(payload)
                self.proc.stdin.flush()
        except (OSError, ValueError):
            self._fail("Bot đã đóng stdin hoặc bị crash.")

    def _read_output(self):
        total = 0
        try:
            while True:
                line = self.proc.stdout.readline(MAX_LINE_BYTES + 1)
                if not line:
                    self._fail("Bot đã thoát mà không trả hành động (crash/EOF).")
                    return
                total += len(line)
                if len(line) > MAX_LINE_BYTES or total > MAX_STDOUT_BYTES:
                    self._fail("Output vượt giới hạn: 4 KiB/dòng, 256 KiB/trận.")
                    return
                try:
                    self.outputs.put_nowait(line)
                except queue.Full:
                    self._fail("Bot xuất quá nhiều hành động: chỉ một dòng JSON cho mỗi lượt.")
                    return
        except (OSError, ValueError):
            self._fail("Không thể đọc stdout của bot.")

    def _read_error(self):
        try:
            while chunk := self.proc.stderr.read1(2048):
                remaining = MAX_STDERR_BYTES - len(self.stderr)
                self.stderr.extend(chunk[:max(0, remaining)])
                if len(chunk) > remaining:
                    self._fail("stderr vượt giới hạn 64 KiB/trận.")
                    return
        except (OSError, ValueError):
            pass

    def request(self, observation: dict, timeout: float | None = None) -> dict:
        if self.error:
            raise BotError(self.error)
        limit = timeout if timeout is not None else (STARTUP_TIMEOUT if self.requests == 0 else TURN_TIMEOUT)
        self.requests += 1
        deadline = monotonic() + limit
        payload = (json.dumps(observation, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            # A dedicated writer means a bot that doesn't consume stdin cannot block the server.
            self.inputs.put(payload, timeout=max(0, deadline - monotonic()))
            line = self.outputs.get(timeout=max(0, deadline - monotonic()))
        except (queue.Empty, queue.Full):
            self._fail(f"Bot timeout sau {limit:g} giây. Cần trả JSON và flush stdout.")
            raise BotError(self.error)
        if self.error or line is None:
            raise BotError(self.error or "Bot đã dừng.")
        try:
            return json.loads(line.decode("utf-8"), parse_constant=reject_constant)
        except (ValueError, UnicodeDecodeError, RecursionError) as exc:
            raise BotError("Bot trả JSON lỗi. stdout chỉ được chứa hành động JSON từng dòng.") from exc

    def close(self):
        if not self.proc:
            return
        if self.proc.poll() is None:
            self.proc.kill()
        try:
            self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        try:
            self.inputs.put_nowait(None)
        except queue.Full:
            pass
        for thread in self.threads:
            thread.join(timeout=0.5)
        for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            try:
                stream.close()
            except (OSError, ValueError):
                pass
