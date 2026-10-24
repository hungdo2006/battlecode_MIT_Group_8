"""Small runner boundary. Game adapters only see observations and actions."""
import os
import threading
from pathlib import Path
from typing import Protocol

from backend.runner import BotProcess, prepare_submission, toolchains


class RunnerUnavailable(RuntimeError):
    """Infrastructure failure: never convert this into a player's forfeit."""


class Session(Protocol):
    def start(self): ...
    def request(self, observation: dict) -> dict: ...
    def close(self): ...


class LegacySession:
    def __init__(self, bot):
        self.bot, self.process = bot, None
        self.lock = threading.Lock()
        self.closed = False

    def start(self):
        with self.lock:
            if self.closed:
                raise RunnerUnavailable("Session was cancelled before startup")
            self.process = BotProcess(self.bot['command'], Path(self.bot['folder']))

    def request(self, observation):
        return self.process.request(observation)

    def close(self):
        with self.lock:
            self.closed = True
            if self.process:
                self.process.close()


class LegacyRunner:
    mode = 'legacy'

    def __init__(self, compile_fn=None):
        self.compile_fn = compile_fn or prepare_submission

    def startup(self):
        pass

    def shutdown(self):
        pass

    def health(self):
        return {'mode': self.mode, 'ready': True, 'toolchains': toolchains()}

    def prepare(self, source, filename, folder):
        status, logs, command = self.compile_fn(source, filename, folder)
        return dict(status=status, logs=logs, command=command, execution_backend=self.mode)

    def compatible(self, bot):
        if bot.get('execution_backend', 'legacy') != self.mode:
            raise ValueError('Submission belongs to another runner; submit the source again.')

    def session(self, bot, job_id):
        self.compatible(bot)
        return LegacySession(bot)


def configured_runner(compile_fn=None):
    mode = os.environ.get('ARENA_RUNNER', 'legacy')
    if mode == 'legacy':
        return LegacyRunner(compile_fn)
    if mode in ('sandbox', 'local_sandbox'):
        from backend.sandbox_client import SandboxRunner
        return SandboxRunner()
    if mode == 'remote_sandbox':
        from backend.remote_runner import RemoteSandboxRunner
        return RemoteSandboxRunner()
    raise ValueError('ARENA_RUNNER must be legacy, sandbox or remote_sandbox; no automatic fallback')
