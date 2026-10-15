"""HTTP client only: the public backend has neither Docker SDK nor socket."""
import base64
import json
import os
import threading
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener

from backend.execution import RunnerUnavailable
from backend.runner import BotError, MAX_SOURCE_BYTES


class SandboxRunner:
    mode = 'sandbox'

    def __init__(self):
        self.url = os.environ.get('ARENA_CONTROLLER_URL', 'http://controller:9000').rstrip('/')
        parsed = urlparse(self.url)
        if parsed.scheme != 'http' or parsed.hostname != 'controller' or parsed.port != 9000 or parsed.path:
            raise ValueError('Controller must be http://controller:9000 on the private Compose network')
        self.token = os.environ.get('ARENA_RUNNER_TOKEN', '')
        if len(self.token) < 32:
            raise ValueError('ARENA_RUNNER_TOKEN requires at least 32 characters')
        self.owner = uuid.uuid4().hex
        self.stop = threading.Event()
        self.thread = None
        self.available = False
        self.cleanup_lock = threading.Lock()
        self.pending_closes = set()

    def rpc(self, path, payload=None, timeout=45):
        request = Request(self.url + path,
            data=json.dumps({'owner': self.owner, **payload}).encode() if payload is not None else None,
            headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'})
        try:
            # Never send control-plane credentials through an inherited HTTP proxy.
            with build_opener(ProxyHandler({})).open(request, timeout=timeout) as response:
                data = response.read(1024 * 1024 + 1)
            if len(data) > 1024 * 1024:
                raise ValueError('Controller response exceeds limit')
            return json.loads(data)
        except (HTTPError, URLError, OSError, ValueError) as exc:
            raise RunnerUnavailable('Sandbox controller unavailable or operation rejected; no legacy fallback') from exc

    def startup(self):
        self.rpc('/owner', {})
        self.available = True
        self.thread = threading.Thread(target=self._heartbeat, daemon=True)
        self.thread.start()

    def _heartbeat(self):
        while not self.stop.wait(5):
            try:
                self.rpc('/heartbeat', {}, timeout=4)
                self.available = True
                with self.cleanup_lock:
                    pending = list(self.pending_closes)
                for job_id in pending:
                    self.close_job(job_id)
            except RunnerUnavailable:
                self.available = False

    def close_job(self, job_id):
        try:
            result = self.rpc('/close/' + job_id, {}, timeout=12)
            if not result.get('closed'):
                raise RunnerUnavailable('Docker cleanup pending')
            with self.cleanup_lock:
                self.pending_closes.discard(job_id)
        except RunnerUnavailable:
            with self.cleanup_lock:
                self.pending_closes.add(job_id)

    def health(self):
        try:
            health = self.rpc('/health', timeout=3)
            return {'mode': self.mode, 'ready': self.available and health['ready'], 'toolchains': health['toolchains']}
        except RunnerUnavailable:
            return {'mode': self.mode, 'ready': False, 'toolchains': {}}

    def shutdown(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=5)
        # Reaper is a second line of defence if Engine/controller is unavailable.

    def prepare(self, source, filename, folder):
        language = Path(filename).suffix.lower()[1:]
        if language not in ('py', 'cpp', 'java') or not source or len(source) > MAX_SOURCE_BYTES:
            raise ValueError('Only .py/.cpp/.java files, 1..256 KiB, are supported')
        folder.mkdir(parents=True, exist_ok=True)
        (folder / ('Main.java' if language == 'java' else 'bot.' + language)).write_bytes(source)
        job = 'c-' + uuid.uuid4().hex
        result = self.rpc('/compile/' + job, {'language': language, 'source': base64.b64encode(source).decode()})
        return {**result, 'command': [], 'execution_backend': self.mode}

    def compatible(self, bot):
        if bot.get('execution_backend') != self.mode or not bot.get('artifact_id'):
            raise ValueError('Bot was compiled with legacy runner; resubmit source for sandbox execution')

    def session(self, bot, job_id):
        self.compatible(bot)
        return SandboxSession(self, bot, job_id)


class SandboxSession:
    def __init__(self, runner, bot, job_id):
        self.runner, self.bot, self.job_id = runner, bot, job_id
        self.closed = threading.Event()
        self.seq = 0

    def start(self):
        if self.closed.is_set():
            raise RunnerUnavailable('Session cancelled before startup')
        try:
            self.runner.rpc('/runtime/' + self.job_id, {k: self.bot[k] for k in ('artifact_id', 'artifact_digest')})
        except BaseException:
            self.close()
            raise
        if self.closed.is_set():
            self.close()
            raise RunnerUnavailable('Session cancelled during startup')

    def request(self, observation):
        result = self.runner.rpc('/runtime/' + self.job_id + '/request', {'seq': self.seq, 'observation': observation}, timeout=20)
        self.seq += 1
        if 'bot_error' in result:
            raise BotError(result['bot_error'])
        return result['action']

    def close(self):
        self.closed.set()
        self.runner.close_job(self.job_id)
