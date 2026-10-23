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


class ControllerRejected(RunnerUnavailable):
    def __init__(self, status):
        self.status = status
        super().__init__('Controller rejected operation; no legacy fallback')


class SandboxRunner:
    mode = 'sandbox'

    def __init__(self, *, remote=False):
        if remote:
            # The cloud must never know the PC Controller's Docker authority token.
            self.url, self.token = None, None
        else:
            self.url = os.environ.get('ARENA_CONTROLLER_URL', 'http://controller:9000').rstrip('/')
            parsed = urlparse(self.url)
            if parsed.scheme != 'http' or parsed.hostname != 'controller' or parsed.port != 9000 or parsed.path:
                raise ValueError('Controller must be http://controller:9000 on the private Compose network')
            self.token = os.environ.get('ARENA_RUNNER_TOKEN', '')
            if len(self.token) < 32:
                raise ValueError('ARENA_RUNNER_TOKEN requires at least 32 characters')
        self.owner = uuid.uuid4().hex
        self.epoch = self.lease = None
        self.lease_lock = threading.RLock()
        self.stop = threading.Event()
        self.thread = None
        self.available = False
        self.image_ids = {}
        self.cleanup_lock = threading.Lock()
        self.pending_closes = {}  # job_id -> its original lease, never the next lease.

    def rpc(self, path, payload=None, timeout=45, lease=None, max_bytes=1024 * 1024):
        body = None
        if payload is not None:
            with self.lease_lock:
                body = {'owner': self.owner, **payload}
                if path != '/owner':
                    body['lease'] = self.lease if lease is None else lease
        request = Request(self.url + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'})
        try:
            # Never send control-plane credentials through an inherited HTTP proxy.
            with build_opener(ProxyHandler({})).open(request, timeout=timeout) as response:
                data = response.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise ValueError('Controller response exceeds limit')
            return json.loads(data)
        except HTTPError as exc:
            raise ControllerRejected(exc.code) from exc
        except (URLError, OSError, ValueError) as exc:
            raise RunnerUnavailable('Sandbox controller unavailable or operation rejected; no legacy fallback') from exc

    def startup(self):
        health = self.rpc('/health', timeout=3)
        self.claim_epoch(health['epoch'])
        self._save_image_ids(health)
        self.available = True
        self.thread = threading.Thread(target=self._heartbeat, daemon=True)
        self.thread.start()

    def claim_epoch(self, epoch):
        with self.lease_lock:
            result = self.rpc('/owner', {'epoch': epoch})
            self.epoch, self.lease = result['epoch'], result['lease']

    def _save_image_ids(self, health):
        with self.lease_lock:
            # A controller pinned to a different Docker image invalidates
            # previously compiled artifacts, even when it is otherwise healthy.
            self.image_ids = {'sandbox': health.get('sandbox_image'),
                              'battlecode26': health.get('battlecode_image')}

    def image_for_game(self, game_id):
        with self.lease_lock:
            if not self.available:
                return None
            return self.image_ids.get('battlecode26' if game_id == 'battlecode26' else 'sandbox')

    def heartbeat_once(self):
        try:
            self.rpc('/heartbeat', {}, timeout=4)
            health = self.rpc('/health', timeout=3)
        except ControllerRejected as exc:
            if exc.status != 409:
                raise
            health = self.rpc('/health', timeout=3)
            if health['epoch'] == self.epoch:
                # An expired/superseded owner may never resurrect itself.
                raise
            self.available = False
            self.claim_epoch(health['epoch'])  # Controller restart swept old containers.
        self._save_image_ids(health)
        self.available = True
        with self.cleanup_lock:
            pending = list(self.pending_closes.items())
        for job_id, lease in pending:
            self.close_job(job_id, lease)

    def _heartbeat(self):
        while not self.stop.wait(5):
            try:
                self.heartbeat_once()
            except RunnerUnavailable:
                self.available = False

    def close_job(self, job_id, lease=None):
        lease = self.lease if lease is None else lease
        try:
            result = self.rpc('/close/' + job_id, {}, timeout=12, lease=lease)
            if not result.get('closed'):
                raise RunnerUnavailable('Docker cleanup pending')
            with self.cleanup_lock:
                self.pending_closes.pop(job_id, None)
        except ControllerRejected as exc:
            if exc.status not in (404, 409):
                with self.cleanup_lock:
                    self.pending_closes[job_id] = lease
            else:
                # Old-lease jobs are controller-owned cleanup, not a new close.
                with self.cleanup_lock:
                    self.pending_closes.pop(job_id, None)
        except RunnerUnavailable:
            with self.cleanup_lock:
                self.pending_closes[job_id] = lease

    def health(self):
        try:
            health = self.rpc('/health', timeout=3)
            self._save_image_ids(health)
            return {'mode': self.mode, 'ready': self.available and health['ready'], 'toolchains': health['toolchains'],
                    'battlecode26': health.get('battlecode26', False)}
        except RunnerUnavailable:
            self.available = False
            return {'mode': self.mode, 'ready': False, 'toolchains': {}}

    def shutdown(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=5)
        if self.lease is not None:
            try:
                self.rpc('/release', {}, timeout=4)
            except RunnerUnavailable:
                pass  # Reaper expires the lease if Engine/controller is offline.
        self.available = False

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

    def prepare_battlecode(self, source, filename, folder):
        language = Path(filename).suffix.lower()[1:]
        if language not in ('py', 'java') or not 0 < len(source) <= MAX_SOURCE_BYTES:
            raise ValueError('Battlecode supports .py/.java, 1..256 KiB')
        folder.mkdir(parents=True, exist_ok=True)
        (folder / ('Main.java' if language == 'java' else 'bot.py')).write_bytes(source)
        job = 'bc-c-' + uuid.uuid4().hex
        result = self.rpc('/battlecode/compile/' + job, {'language': language, 'source': base64.b64encode(source).decode()})
        return {**result, 'command': [], 'execution_backend': self.mode, 'engine': 'battlecode26'}

    def whole_match(self, bots, job_id):
        for bot in bots.values():
            self.compatible(bot)
            if bot.get('engine') != 'battlecode26':
                raise RunnerUnavailable('Submission is not compiled against Battlecode')
        return BattlecodeSession(self, bots, job_id)

    def session(self, bot, job_id):
        self.compatible(bot)
        return SandboxSession(self, bot, job_id)


class SandboxSession:
    def __init__(self, runner, bot, job_id):
        self.runner, self.bot, self.job_id = runner, bot, job_id
        self.lease = runner.lease
        self.closed = threading.Event()
        self.seq = 0

    def start(self):
        if self.closed.is_set():
            raise RunnerUnavailable('Session cancelled before startup')
        try:
            self.runner.rpc('/runtime/' + self.job_id,
                            {k: self.bot[k] for k in ('artifact_id', 'artifact_digest')}, lease=self.lease)
        except BaseException:
            self.close()
            raise
        if self.closed.is_set():
            self.close()
            raise RunnerUnavailable('Session cancelled during startup')

    def request(self, observation):
        result = self.runner.rpc('/runtime/' + self.job_id + '/request',
                                 {'seq': self.seq, 'observation': observation}, timeout=20, lease=self.lease)
        self.seq += 1
        if 'bot_error' in result:
            raise BotError(result['bot_error'])
        return result['action']

    def close(self):
        self.closed.set()
        self.runner.close_job(self.job_id, self.lease)


class BattlecodeSession:
    def __init__(self, runner, bots, job_id):
        self.runner, self.bots, self.job_id = runner, bots, job_id
        self.lease = runner.lease

    def run(self, rules):
        payload = {'map': rules['map']}
        for side, bot in self.bots.items():
            payload['artifact_' + side.lower()] = bot['artifact_id']
            payload['digest_' + side.lower()] = bot['artifact_digest']
        return self.runner.rpc('/battlecode/match/' + self.job_id, payload, timeout=190,
                               lease=self.lease, max_bytes=16 * 1024 * 1024)

    def close(self):
        self.runner.close_job(self.job_id, self.lease)
