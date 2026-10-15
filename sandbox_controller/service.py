"""Private control plane: fixed operations, bearer auth, no Docker options API."""
import base64
import hashlib
import hmac
import logging
import os
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


class Payload(BaseModel):
    model_config = ConfigDict(extra='forbid')
    owner: str = Field(pattern=r'^[a-f0-9]{32}$')


class Compile(Payload):
    language: str = Field(pattern=r'^(py|cpp|java)$')
    source: str = Field(max_length=350000)


class Open(Payload):
    artifact_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,80}$')
    artifact_digest: str = Field(pattern=r'^[a-f0-9]{64}$')


class Observation(Payload):
    seq: int = Field(ge=0, le=100000)
    observation: dict


@dataclass
class Job:
    kind: str
    owner: str
    fingerprint: str
    created: float = field(default_factory=time.monotonic)
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
        self.owner, self.heartbeat = None, 0
        self.jobs = {}
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self.reap, daemon=True)
        self.thread.start()

    def authorize_owner(self, owner):
        if self.owner != owner:
            raise HTTPException(409, 'Backend lease is no longer current')

    def claim(self, owner):
        with self.lock:
            if self.owner != owner:
                for job in self.jobs.values():
                    self.close(job)
                self.owner = owner
            self.heartbeat = time.monotonic()

    def reserve(self, job_id, payload, kind):
        identifier(job_id)
        fingerprint = hashlib.sha256(payload.model_dump_json().encode()).hexdigest()
        with self.lock:
            self.authorize_owner(payload.owner)
            if job_id in self.jobs:
                job = self.jobs[job_id]
                if job.owner != payload.owner or job.kind != kind or job.fingerprint != fingerprint:
                    raise HTTPException(409, 'Job ID already used with different parameters')
                if job.cancelled.is_set() and not (kind == 'compile' and job.result is not None):
                    raise HTTPException(409, 'Job is closed; never restart a closed job ID')
                return job
            active = sum(j.kind == kind and (not j.cancelled.is_set() or j.container is not None)
                         for j in self.jobs.values())
            if active >= (1 if kind == 'compile' else 4) or len(self.jobs) >= 4096:
                raise HTTPException(503, 'Sandbox capacity reached')
            job = Job(kind, payload.owner, fingerprint)
            self.jobs[job_id] = job
            return job

    def get(self, job_id, owner):
        identifier(job_id)
        with self.lock:
            self.authorize_owner(owner)
            job = self.jobs.get(job_id)
            if not job or job.owner != owner:
                raise HTTPException(404, 'Unknown job')
            return job

    def ensure_container(self, job_id, job):
        if job.cancelled.is_set():
            raise InfrastructureError('Job cancelled before startup')
        job.container = self.engine.create(job_id, job.kind, job.owner)
        if job.cancelled.is_set():
            self.close(job)
            raise InfrastructureError('Job cancelled during startup')

    def close(self, job):
        # Mark before cleanup, including while another thread is creating the container.
        job.cancelled.set()
        if job.pipe:
            job.pipe.close()
        if job.container:
            try:
                job.container.remove(force=True)
                job.container = None
            except docker.errors.NotFound:
                job.container = None
            except Exception:
                # Retain handle; reaper retries when Engine recovers.
                log.exception('Sandbox cleanup pending; Engine unavailable')

    def compile(self, job_id, payload):
        try:
            source = base64.b64decode(payload.source, validate=True)
        except ValueError:
            raise HTTPException(400, 'Invalid source encoding')
        if not source or len(source) > MAX_SOURCE_BYTES:
            raise HTTPException(400, 'Source must be 1..256 KiB')
        job = self.reserve(job_id, payload, 'compile')
        with job.lock:
            if job.result is not None:
                return job.result
            if job.failure:
                raise InfrastructureError('Previous compile attempt failed; resubmit explicitly')
            try:
                self.ensure_container(job_id, job)
                success, logs, archive = self.engine.compile(job.container, payload.language, source, job.cancelled)
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

    def open(self, job_id, payload):
        job = self.reserve(job_id, payload, 'runtime')
        with job.lock:
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
        job = self.get(job_id, payload.owner)
        with job.lock:
            if job.cancelled.is_set() or not job.pipe:
                raise InfrastructureError('Runtime is not available')
            # Transport retries must never feed the same observation twice.
            digest = hashlib.sha256(payload.model_dump_json().encode()).hexdigest()
            if payload.seq == job.seq and digest == job.request_hash:
                return job.response
            if payload.seq != job.seq + 1:
                raise HTTPException(409, 'Out-of-order/ambiguous observation; no re-execution')
            job.seq, job.request_hash = payload.seq, digest
            try:
                job.response = {'action': job.pipe.request(payload.observation)}
                return job.response
            except BotError as exc:
                job.response = {'bot_error': str(exc)}
                self.close(job)
                return job.response
            except Exception:
                self.close(job)
                raise

    def reap(self):
        while not self.stopping.wait(2):
            with self.lock:
                now = time.monotonic()
                for job_id, job in list(self.jobs.items()):
                    if now - self.heartbeat > 20 or now - job.created > 3600 or job.cancelled.is_set():
                        self.close(job)
                    # Tombstones outlive client HTTP timeouts; bounded memory.
                    if job.cancelled.is_set() and job.container is None and now - job.created > 120:
                        self.jobs.pop(job_id, None)

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
        yield
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
        return {'ready': True, 'toolchains': {'python': 'sandbox', 'cpp': 'sandbox', 'javac': 'sandbox', 'java': 'sandbox'}}

    @app.post('/owner')
    def claim(payload: Payload):
        app.state.controller.claim(payload.owner)
        return {'ready': True}

    @app.post('/heartbeat')
    def heartbeat(payload: Payload):
        control = app.state.controller
        with control.lock:
            # A restarted controller has already swept its namespace. Reconnect the
            # existing backend lease, but never let an old backend replace a new one.
            if control.owner is None:
                control.owner = payload.owner
            control.authorize_owner(payload.owner)
            control.heartbeat = time.monotonic()
        return {'ready': True}

    @app.post('/compile/{job_id}')
    def compile(job_id: str, payload: Compile):
        return app.state.controller.compile(job_id, payload)

    @app.post('/runtime/{job_id}')
    def open_runtime(job_id: str, payload: Open):
        return app.state.controller.open(job_id, payload)

    @app.post('/runtime/{job_id}/request')
    def request(job_id: str, payload: Observation):
        return app.state.controller.request(job_id, payload)

    @app.post('/close/{job_id}')
    def close(job_id: str, payload: Payload):
        control = app.state.controller
        with control.lock:
            control.authorize_owner(payload.owner)
            job = control.jobs.get(identifier(job_id))
            if not job:
                if len(control.jobs) >= 4096:
                    raise HTTPException(503, 'Tombstone capacity reached')
                # Tombstone precedes a delayed startup request after cancellation.
                job = Job('closed', payload.owner, '')
                control.jobs[job_id] = job
        control.close(job)
        return {'closed': job.container is None}

    return app
