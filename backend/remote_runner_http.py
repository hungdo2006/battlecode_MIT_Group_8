"""Restricted machine-only HTTP endpoints for one outbound Remote Runner PC.

No user session, Docker token or Controller address is accepted here. Distinct
high-entropy worker secret is checked BEFORE request bodies are buffered.
"""
import asyncio
import hmac
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from backend.remote_runner import RemoteSandboxRunner

MAX_BODY = 17 * 1024 * 1024
PREFIX = "/api/remote-runner"


class RemoteRunnerBoundary:
    def __init__(self, app, secret):
        self.app = app
        self.expected = b"Bearer " + secret.encode("utf-8")

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith(PREFIX + "/"):
            return await self.app(scope, receive, send)
        headers = scope.get("headers", [])
        auth = [value for key, value in headers if key.lower() == b"authorization"]
        if len(auth) != 1 or not hmac.compare_digest(auth[0], self.expected):
            return await self._error(send, 401)
        lengths = [value for key, value in headers if key.lower() == b"content-length"]
        if (len(lengths) > 1 or
                (lengths and (not lengths[0].isdigit() or int(lengths[0]) > MAX_BODY))):
            return await self._error(send, 413)
        if scope["method"] in ("POST", "PUT"):
            types = [value.split(b";", 1)[0].strip().lower() for key, value in headers
                     if key.lower() == b"content-type"]
            if len(types) != 1 or types[0] != b"application/json":
                return await self._error(send, 415)
        total = 0

        async def limited_receive():
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > MAX_BODY:
                    raise BodyTooLarge()
            return message

        async def secured_send(message):
            if message["type"] == "http.response.start":
                message["headers"] = [(k, v) for k, v in message.get("headers", [])
                                      if k.lower() not in (b"cache-control", b"referrer-policy")]
                message["headers"].extend([(b"cache-control", b"no-store"),
                                            (b"referrer-policy", b"no-referrer"),
                                            (b"x-content-type-options", b"nosniff")])
            await send(message)

        try:
            await self.app(scope, limited_receive, secured_send)
        except BodyTooLarge:
            await self._error(send, 413)

    @staticmethod
    async def _error(send, status):
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": b""})


class BodyTooLarge(Exception):
    pass


class RemoteReply(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    status: int
    result: dict


def install_remote_runner_http(app):
    key = os.environ.get("ARENA_REMOTE_RUNNER_KEY", "")
    if len(key.encode("utf-8")) < 32:
        raise ValueError("Remote Runner requires a private 32+ byte ARENA_REMOTE_RUNNER_KEY")
    app.add_middleware(RemoteRunnerBoundary, secret=key)
    router = APIRouter(prefix=PREFIX, include_in_schema=False)

    def bridge():
        runner = getattr(app.state, "runner", None)
        if not isinstance(runner, RemoteSandboxRunner):
            raise HTTPException(503, "Remote Runner not initialized")
        return runner.relay

    def session(request):
        values = request.headers.getlist("x-arena-runner-session")
        if len(values) != 1 or not values[0]:
            raise HTTPException(409, "Missing remote session")
        return values[0]

    @router.post("/connect")
    async def connect():
        try:
            return {"session": bridge().connect(), "protocol": 1}
        except ValueError:
            raise HTTPException(409, "Another remote worker is active") from None

    @router.get("/poll")
    async def poll(request: Request):
        try:
            task = await asyncio.to_thread(bridge().poll, session(request))
        except ValueError:
            raise HTTPException(409, "Remote session expired") from None
        return task if task is not None else Response(status_code=204)

    @router.post("/respond")
    async def respond(body: RemoteReply, request: Request):
        try:
            await asyncio.to_thread(bridge().respond, session(request),
                                    body.id, body.status, body.result)
        except ValueError:
            raise HTTPException(409, "Remote response rejected") from None
        return {"accepted": True}

    @router.post("/disconnect")
    async def disconnect(request: Request):
        try:
            bridge().disconnect(session(request))
        except ValueError:
            raise HTTPException(409, "Remote session expired") from None
        return {"disconnected": True}

    app.include_router(router)
