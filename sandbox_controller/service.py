"""Private control plane: fixed operations, bearer auth, no Docker options API."""
import base64
import hashlib
import hmac
import logging
import os
import secrets
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import docker
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.runner import BotError, MAX_SOURCE_BYTES
from sandbox_controller.artifacts import ArtifactStore, identifier, unpack
from sandbox_controller.engine import Engine, InfrastructureError, Pipe

log = logging.getLogger(__name__)


LEASE_SECONDS = 20
CLOSED_RETENTION = 120
MAX_USED_IDS = 65536


class Claim(BaseModel):
    model_config = ConfigDict(extra='forbid')
    owner: str = Field(pattern=r'^[a-f0-9]{32}$')
    epoch: str = Field(pattern=r'^[a-f0-9]{32}$')


class Payload(BaseModel):
    model_config = ConfigDict(extra='forbid')
    owner: str = Field(pattern=r'^[a-f0-9]{32}$')
    lease: str = Field(pattern=r'^[a-f0-9]{32}$')


class Compile(Payload):
    language: str = Field(pattern=r'^(py|cpp|java)$')
    source: str = Field(max_length=350000)


class Open(Payload):
    artifact_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,80}$')
    artifact_digest: str = Field(pattern=r'^[a-f0-9]{64}$')


class BattlecodeCompile(Compile):
    language: str = Field(pattern=r'^(py|java)$')


class BattlecodeMatch(Payload):
    artifact_a: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,80}$')
    digest_a: str = Field(pattern=r'^[a-f0-9]{64}$')
    artifact_b: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,80}$')
    digest_b: str = Field(pattern=r'^[a-f0-9]{64}$')
    map: str = Field(pattern=r'^(DefaultSmall|DefaultMedium|DefaultLarge)$')


class Observation(Payload):
    seq: int = Field(ge=0, le=100000)
    observation: dict


@dataclass
class Job:
    kind: str
    owner: str
    fingerprint: str
    lease: str = ''
    created: float = field(default_factory=time.monotonic)
    closed_at: float | None = None
    cleanup_lock: threading.RLock = field(default_factory=threading.RLock)
    starting: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)
    cancelled: threading.Event = field(default_factory=threading.Event)
    container: object = None
    pipe: object = None
    result: dict | None = None
    failure: Exception | None = None
    seq: int = -1
    request_hash: str | None = None
    response: object = None


class Controller:
    def __init__(self):
        namespace = os.environ.get('SANDBOX_NAMESPACE', 'neon-arena')
        identifier(namespace)
        self.engine = Engine(os.environ.get('SANDBOX_IMAGE', 'neon-arena-bot:4.0'), namespace)
        self.store = ArtifactStore(os.environ.get('SANDBOX_ARTIFACTS', '/artifacts'))
        self.lock = threading.RLock()
        self.epoch = secrets.token_hex(16)  # A restart fences every old request.
        self.owner, self.lease, self.heartbeat = None, None, 0
        self.retired_owners = set()
        # Compact, bounded ledger survives removal of heavy job/result records.
        # IDs are never reusable within this controller epoch.
        self.used_ids = set()
        self.jobs = {}
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self.reap, daemon=True)
        self.thread.start()

    def expire_lease(self, now):
        if self.owner is not None and now - self.heartbeat >= LEASE_SECONDS:
            self.retired_owners.add(self.owner)
            self.owner = self.lease = None
            for job in self.jobs.values():
                self.close(job)

    def authorize_owner(self, owner, lease):
        self.expire_lease(time.monotonic())
        if self.owner != owner or self.lease != lease:
            raise HTTPException(409, 'Backend lease is no longer current')

    def claim(self, owner, epoch):
        with self.lock:
            if epoch != self.epoch:
                raise HTTPException(409, 'Controller restarted; stale epoch')
            self.expire_lease(time.monotonic())
            if owner in self.retired_owners:
                raise HTTPException(409, 'Retired owner cannot reclaim this epoch')
            if self.owner is not None and self.owner != owner:
                raise HTTPException(409, 'Another backend has a live lease')
            if self.owner != owner:
                if len(self.retired_owners) >= 4096:
                    raise HTTPException(503, 'Lease ledger full; controlled restart required')
                self.owner = owner
                self.lease = secrets.token_hex(16)
            self.heartbeat = time.monotonic()
            return {'ready': True, 'epoch': self.epoch, 'lease': self.lease}

    def renew(self, payload):
        with self.lock:
            self.authorize_owner(payload.owner, payload.lease)
            self.heartbeat = time.monotonic()

    def release(self, payload):
        with self.lock:
            self.authorize_owner(payload.owner, payload.lease)
            self.retired_owners.add(self.owner)
            self.owner = self.lease = None
            for job in self.jobs.values():
                self.close(job)

    def remember_id(self, job_id):
        if job_id in self.used_ids:
            raise HTTPException(409, 'Job ID has already been used in this controller epoch')
        if len(self.used_ids) >= MAX_USED_IDS:
            raise HTTPException(503, 'Job ID ledger full; controlled restart required')
        self.used_ids.add(job_id)

    def reserve(self, job_id, payload, kind):
        identifier(job_id)
        fingerprint = hashlib.sha256(payload.model_dump_json().encode()).hexdigest()
        with self.lock:
            self.authorize_owner(payload.owner, payload.lease)
            if job_id in self.jobs:
                job = self.jobs[job_id]
                if (job.owner != payload.owner or job.lease != payload.lease
                        or job.kind != kind or job.fingerprint != fingerprint):
                    raise HTTPException(409, 'Job ID already used with different parameters')
                if job.cancelled.is_set() and not (kind in ('compile', 'battlecode_compile', 'battlecode_match') and job.result is not None):
                    raise HTTPException(409, 'Job is closed; never restart a closed job ID')
                return job
            active = sum(j.kind == kind and (not j.cancelled.is_set() or j.container is not None)
                         for j in self.jobs.values())
            capacity = 1 if kind in ('compile', 'battlecode_compile') else 2 if kind == 'battlecode_match' else 4
            if active >= capacity or len(self.jobs) >= 4096:
                raise HTTPException(503, 'Sandbox capacity reached')
            self.remember_id(job_id)
            job = Job(kind, payload.owner, fingerprint, lease=payload.lease)
            self.jobs[job_id] = job
            return job

    def get(self, job_id, payload):
        identifier(job_id)
        with self.lock:
            self.authorize_owner(payload.owner, payload.lease)
            job = self.jobs.get(job_id)
            if not job or job.owner != payload.owner or job.lease != payload.lease:
                raise HTTPException(404, 'Unknown job')
            return job

    def ensure_container(self, job_id, job):
        with self.lock:
            self.authorize_owner(job.owner, job.lease)
        if job.cancelled.is_set():
            raise InfrastructureError('Job cancelled before startup')
        with job.cleanup_lock:
            job.starting = True
        try:
            container = self.engine.create(job_id, job.kind, job.owner)
            with job.cleanup_lock:
                job.container = container
        finally:
            with job.cleanup_lock:
                job.starting = False
        if job.cancelled.is_set():
            self.close(job)
            raise InfrastructureError('Job cancelled during startup')

    def close(self, job):
        # Mark before cleanup, including while another thread is creating the container.
        with job.cleanup_lock:
            if job.closed_at is None:
                job.closed_at = time.monotonic()
            job.cancelled.set()
            if job.pipe:
                try:
                    job.pipe.close()
                except Exception:
                    log.exception('Pipe cleanup failed; still attempting container removal')
            if job.container:
                try:
                    job.container.remove(force=True)
                    job.container = None
                except docker.errors.NotFound:
                    job.container = None
                except Exception:
                    # Retain handle; reaper retries when Engine recovers.
                    log.exception('Sandbox cleanup pending; Engine unavailable')

    def close_id(self, job_id, payload):
        identifier(job_id)
        with self.lock:
            self.authorize_owner(payload.owner, payload.lease)
            job = self.jobs.get(job_id)
            if job is None:
                if job_id in self.used_ids:
                    return {'closed': True}  # Already closed and compacted.
                if len(self.jobs) >= 4096:
                    raise HTTPException(503, 'Tombstone capacity reached')
                self.remember_id(job_id)
                job = Job('closed', payload.owner, '', lease=payload.lease)
                self.jobs[job_id] = job
            elif job.owner != payload.owner or job.lease != payload.lease:
                raise HTTPException(409, 'Job belongs to another lease')
            self.close(job)
            return {'closed': job.container is None and not job.starting}

    def compile(self, job_id, payload):
        try:
            source = base64.b64decode(payload.source, validate=True)
        except ValueError:
            raise HTTPException(400, 'Invalid source encoding')
        if not source or len(source) > MAX_SOURCE_BYTES:
            raise HTTPException(400, 'Source must be 1..256 KiB')
        job = self.reserve(job_id, payload, 'compile')
        with job.lock:
            with self.lock:
                self.authorize_owner(payload.owner, payload.lease)
            if job.result is not None:
                return job.result
            if job.failure:
                raise InfrastructureError('Previous compile attempt failed; resubmit explicitly')
            try:
                self.ensure_container(job_id, job)
                success, logs, archive = self.engine.compile(job.container, payload.language, source, job.cancelled)
                with self.lock:
                    self.authorize_owner(payload.owner, payload.lease)
                if job.cancelled.is_set():
                    raise InfrastructureError('Compile cancelled; no bot fault')
                artifact = {}
                if success:
                    try:
                        files = unpack(archive, payload.language)
                    except ValueError as exc:
                        success, logs = False, f'Unsafe compiler artifact: {exc}'
                    else:
                        artifact = self.store.save(job_id, payload.language, files, self.engine.image)
                job.result = dict(status='ready' if success else 'error', logs=logs, **artifact)
                return job.result
            except Exception as exc:
                job.failure = exc
                raise
            finally:
                # Keep result for duplicate HTTP calls, but remove all processes/workspace.
                self.close(job)

    def battlecode(self, job_id, payload, operation):
        with self.lock:
            self.authorize_owner(payload.owner, payload.lease)
        if not getattr(self.engine, 'battlecode_image', None):
            raise HTTPException(503, 'Battlecode image is not configured')
        source = None
        if operation == 'compile':
            try:
                source = base64.b64decode(payload.source, validate=True)
            except ValueError:
                raise HTTPException(400, 'Invalid source encoding') from None
            if not 0 < len(source) <= MAX_SOURCE_BYTES:
                raise HTTPException(400, 'Source must be 1..256 KiB')
            request = {'language': payload.language, 'source': payload.source}
        else:
            try:
                request = {'map': payload.map,
                    'A': self.store.load_battlecode(payload.artifact_a, payload.digest_a, self.engine.battlecode_image),
                    'B': self.store.load_battlecode(payload.artifact_b, payload.digest_b, self.engine.battlecode_image)}
            except (ValueError, OSError):
                raise HTTPException(409, 'Battlecode artifact unavailable or changed') from None
        job = self.reserve(job_id, payload, 'battlecode_' + operation)
        with job.lock:
            with self.lock:
                self.authorize_owner(payload.owner, payload.lease)
            if job.result is not None:
                return job.result
            if job.failure:
                raise InfrastructureError('Previous Battlecode operation failed; never retry a match implicitly')
            try:
                self.ensure_container(job_id, job)
                result = self.engine.run_battlecode(job.container, operation, request, job.cancelled)
                with self.lock:
                    self.authorize_owner(payload.owner, payload.lease)
                if job.cancelled.is_set():
                    raise InfrastructureError('Battlecode operation cancelled')
                if operation == 'compile' and result.get('status') == 'ready':
                    result.update(self.store.save_battlecode(job_id, payload.language, source, self.engine.battlecode_image))
                elif operation == 'match' and not result.get('frames'):
                    raise InfrastructureError('Official Battlecode replay is unavailable')
                job.result = result
                return result
            except Exception as error:
                job.failure = error
                raise
            finally:
                self.close(job)

    def open(self, job_id, payload):
        job = self.reserve(job_id, payload, 'runtime')
        with job.lock:
            with self.lock:
                self.authorize_owner(payload.owner, payload.lease)
            if job.cancelled.is_set():
                raise InfrastructureError('Runtime cancelled before open')
            if job.result:
                return job.result
            try:
                language, files = self.store.load(payload.artifact_id, payload.artifact_digest, self.engine.image)
                self.ensure_container(job_id, job)
                self.engine.provision(job.container, files, '/work/app')
                if job.cancelled.is_set():
                    raise InfrastructureError('Cancelled during artifact provisioning')
                job.pipe = Pipe(self.engine, job.container, language)
                job.result = {'ready': True}
                if job.cancelled.is_set():
                    raise InfrastructureError('Cancelled during process startup')
                return job.result
            except Exception:
                self.close(job)
                raise

    def request(self, job_id, payload):
        job = self.get(job_id, payload)
        with job.lock:
            with self.lock:
                self.authorize_owner(payload.owner, payload.lease)
            # Transport retries must never feed the same observation twice.
            # A completed response remains an immutable receipt after close;
            # returning it does NOT reopen the runtime or authorize a new turn.
            # Owner/lease validation above still fences expired/restarted owners.
            digest = hashlib.sha256(payload.model_dump_json().encode()).hexdigest()
            if payload.seq == job.seq and digest == job.request_hash and job.response is not None:
                return job.response
            if job.cancelled.is_set() or not job.pipe:
                raise InfrastructureError('Runtime is not available')
            if payload.seq != job.seq + 1:
                raise HTTPException(409, 'Out-of-order/ambiguous observation; no re-execution')
            job.seq, job.request_hash = payload.seq, digest
            job.response = None  # Never cache the preceding turn after an ambiguous failure.
            try:
                action = job.pipe.request(payload.observation)
                with self.lock:
                    self.authorize_owner(payload.owner, payload.lease)
                if job.cancelled.is_set():
                    raise InfrastructureError('Runtime cancelled during request')
                job.response = {'action': action}
                return job.response
            except BotError as exc:
                with self.lock:
                    self.authorize_owner(payload.owner, payload.lease)
                if job.cancelled.is_set():
                    raise InfrastructureError('Runtime cancelled; no bot fault') from exc
                job.response = {'bot_error': str(exc)}
                self.close(job)
                return job.response
            except Exception:
                self.close(job)
                raise

    def reap_once(self):
        with self.lock:
            now = time.monotonic()
            self.expire_lease(now)
            for job_id, job in list(self.jobs.items()):
                if now - job.created > 3600 or job.cancelled.is_set():
                    self.close(job)
                if (job.closed_at is not None and not job.starting and job.container is None
                        and now - job.closed_at > CLOSED_RETENTION):
                    self.jobs.pop(job_id, None)

    def reap(self):
        while not self.stopping.wait(2):
            self.reap_once()

    def shutdown(self):
        self.stopping.set()
        self.thread.join(timeout=3)
        for job in list(self.jobs.values()):
            self.close(job)


class PrivateAPI:
    """Authenticate before buffering bounded bodies. No cookies, CORS or public docs."""
    def __init__(self, app, token):
        self.app, self.token = app, token

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = dict(scope['headers'])
        health = scope['path'] == '/health' and scope['method'] == 'GET'
        authenticated = hmac.compare_digest(headers.get(b'authorization', b''), b'Bearer ' + self.token)
        status = None
        if not health and not authenticated:
            status = 401
        if status:
            await send({'type': 'http.response.start', 'status': status, 'headers': []})
            return await send({'type': 'http.response.body', 'body': b'Unauthorized'})
        messages, total = [], 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            total += len(message.get('body', b''))
            if total > 1024 * 1024:
                await send({'type': 'http.response.start', 'status': 413, 'headers': []})
                return await send({'type': 'http.response.body', 'body': b'Body exceeds limit'})
            messages.append(message)
            if not message.get('more_body'):
                break

        async def replay():
            return messages.pop(0) if messages else await receive()
        await self.app(scope, replay, send)


def create_app():
    token = os.environ.get('ARENA_RUNNER_TOKEN', '').encode()
    if len(token) < 32:
        raise RuntimeError('ARENA_RUNNER_TOKEN must have at least 32 characters')

    @asynccontextmanager
    async def lifespan(app):
        app.state.controller = Controller()
        try:
            yield
        finally:
            app.state.controller.shutdown()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(PrivateAPI, token=token)

    @app.exception_handler(Exception)
    async def infrastructure_failure(request, exc):
        from fastapi.responses import JSONResponse
        log.exception('Controller operation failed', exc_info=exc)
        return JSONResponse({'detail': 'Sandbox infrastructure unavailable; check private controller logs'}, status_code=503)

    @app.get('/health')
    def health():
        app.state.controller.engine.client.ping()
        return {'ready': True, 'epoch': app.state.controller.epoch,
                'battlecode26': bool(getattr(app.state.controller.engine, 'battlecode_image', None)),
                'toolchains': {'python': 'sandbox', 'cpp': 'sandbox', 'javac': 'sandbox', 'java': 'sandbox'}}

    @app.post('/owner')
    def claim(payload: Claim):
        return app.state.controller.claim(payload.owner, payload.epoch)

    @app.post('/heartbeat')
    def heartbeat(payload: Payload):
        app.state.controller.renew(payload)
        return {'ready': True}

    @app.post('/release')
    def release(payload: Payload):
        app.state.controller.release(payload)
        return {'released': True}

    @app.post('/compile/{job_id}')
    def compile(job_id: str, payload: Compile):
        return app.state.controller.compile(job_id, payload)

    @app.post('/runtime/{job_id}')
    def open_runtime(job_id: str, payload: Open):
        return app.state.controller.open(job_id, payload)

    @app.post('/battlecode/compile/{job_id}')
    def battlecode_compile(job_id: str, payload: BattlecodeCompile):
        return app.state.controller.battlecode(job_id, payload, 'compile')

    @app.post('/battlecode/match/{job_id}')
    def battlecode_match(job_id: str, payload: BattlecodeMatch):
        return app.state.controller.battlecode(job_id, payload, 'match')

    @app.post('/runtime/{job_id}/request')
    def request(job_id: str, payload: Observation):
        return app.state.controller.request(job_id, payload)

    @app.post('/close/{job_id}')
    def close(job_id: str, payload: Payload):
        return app.state.controller.close_id(job_id, payload)

    return app
