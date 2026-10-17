"""Gated HTTP account foundation; legacy REST/WS permissions remain separate."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import hmac
from ipaddress import ip_address
import os
import re
import secrets
import sqlite3
import time
from urllib.parse import urlsplit

from argon2.exceptions import HashingError
from fastapi import APIRouter, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from starlette.responses import JSONResponse

from .account_database import AccountDatabase, SchemaError
from .auth_limits import AuthRateLimited, AuthRateLimiter, RateLimits
from .auth_service import (AccountConflict, AuthenticationBusy, AuthenticationFailed, AuthPolicy,
                           AuthService, InvalidInvitation, InvalidSession, PermissionDenied)
from .network import demo_host


PREFIX = "/api/auth"
MAX_BODY = 4096
SAFE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache", "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer"}


def auth_path(path):
    return path == PREFIX or path.startswith(PREFIX + "/")


def cookie_name(audience):
    return "arena_account_" + audience.lower()


def cookie_path(audience):
    return PREFIX + "/" + audience.lower()


def canonical_origin(value):
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.path or parsed.query or parsed.fragment or any(c.isspace() for c in value)
                or "\\" in value or parsed.netloc.endswith(":")):
            raise ValueError()
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if not 1 <= port <= 65535:
            raise ValueError()
        return parsed.scheme, parsed.hostname.lower(), port
    except ValueError:
        raise ValueError("Exact HTTP(S) origins without paths are required") from None


def _env_bool(name):
    value = os.environ.get(name, "0").strip().lower()
    if value not in {"0", "1", "false", "true"}:
        raise ValueError(f"{name} must be 0 or 1")
    return value in {"1", "true"}


@dataclass(frozen=True)
class HTTPAuthSettings:
    enabled: bool = False
    origins: tuple[str, ...] = ()
    allow_http: bool = False  # Explicit local/LAN QA exception, never HTTPS override.
    policy: AuthPolicy = field(default_factory=AuthPolicy)
    limits: RateLimits = field(default_factory=RateLimits)
    clock: object = field(default=time.time, repr=False)
    rate_clock: object = field(default=time.monotonic, repr=False)

    def __post_init__(self):
        if self.enabled:
            if not self.origins:
                raise ValueError("ARENA_AUTH_ORIGINS is required when account HTTP auth is enabled")
            for value in self.origins:
                scheme, host, _ = canonical_origin(value)
                if not demo_host(f"[{host}]" if ":" in host else host) or (scheme == "http" and not self.allow_http):
                    raise ValueError("Account auth supports local/LAN origins; HTTP requires explicit QA opt-in")

    @classmethod
    def from_environment(cls):
        if not _env_bool("ARENA_ACCOUNT_AUTH"):
            return cls()  # OFF does not inspect auth-only configuration or SQLite.
        return cls(enabled=True, origins=tuple(value.strip() for value in os.environ.get("ARENA_AUTH_ORIGINS", "").split(",") if value.strip()),
                   allow_http=_env_bool("ARENA_AUTH_ALLOW_HTTP"))


class HTTPAuthRuntime:
    def __init__(self, database, writer, settings):
        self.database, self.writer, self.settings = database, writer, settings
        self.limiter = AuthRateLimiter(settings.limits, clock=settings.rate_clock)
        self._csrf_key = secrets.token_bytes(32)
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="arena-auth")
        self._jobs = set()
        self._active, self._closing, self._idle = 0, False, asyncio.Event()
        self._idle.set()

    def _service(self, connection):
        return AuthService(connection, self.writer, login_limiter=self.limiter,
                           policy=self.settings.policy, clock=self.settings.clock)

    def startup(self):
        # Exactly once, before legacy Store or Controller starts. No migration.
        with self.database.writer_connection(self.writer) as connection:
            self._service(connection)

    def _work(self, operation):
        # Open/use/close in one worker thread; schema/PRAGMAs still checked.
        with self.database.writer_connection(self.writer, integrity=False) as connection:
            return operation(self._service(connection), connection)

    async def run(self, operation):
        if self._closing or self._active >= 8:
            raise HTTPException(503, "Authentication capacity unavailable", headers={"Retry-After": "1"})
        self._active += 1
        self._idle.clear()
        try:
            job = asyncio.wrap_future(self._pool.submit(self._work, operation))
        except RuntimeError:
            self._active -= 1
            if self._active == 0:
                self._idle.set()
            raise HTTPException(503, "Authentication capacity unavailable") from None
        self._jobs.add(job)

        def finished(future):
            self._jobs.discard(future)
            if not future.cancelled():
                future.exception()  # consume errors even if HTTP caller was cancelled
            self._active -= 1
            if self._active == 0:
                self._idle.set()

        job.add_done_callback(finished)
        try:
            # The request may die, but worker completion owns the active counter.
            # Shield keeps the Future alive under direct asyncio Task.cancel too.
            return await asyncio.shield(job)
        except AuthRateLimited as exc:
            raise HTTPException(429, "Too many authentication requests", headers={"Retry-After": str(exc.retry_after)}) from None
        except AuthenticationBusy:
            raise HTTPException(503, "Authentication capacity unavailable", headers={"Retry-After": "1"}) from None
        except (AuthenticationFailed, InvalidSession):
            raise HTTPException(401, "Invalid credentials or session") from None
        except PermissionDenied:
            raise HTTPException(403, "Not authorized") from None
        except InvalidInvitation:
            raise HTTPException(400, "Invalid or unavailable invitation") from None
        except AccountConflict:
            raise HTTPException(409, "Account operation conflicts with current state") from None
        except (SchemaError, sqlite3.Error, HashingError, RuntimeError):
            raise HTTPException(503, "Authentication service unavailable") from None
        except ValueError:
            raise HTTPException(422, "Invalid authentication request") from None

    async def close(self):
        self._closing = True
        await self._idle.wait()
        await asyncio.to_thread(self._pool.shutdown, wait=True)

    def csrf(self, audience, token):
        return hmac.digest(self._csrf_key, ("csrf\0" + audience + "\0" + token).encode(), "sha256").hex()


def account_json(account):
    return {key: getattr(account, key) for key in ("id", "username", "display_name", "system_role", "status")}


def account_response(account, **extra):
    return {"account": account_json(account), "scope": "account_auth_only", "legacy_api_account_rbac": False, **extra}


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class LoginBody(StrictBody):
    username: str = Field(min_length=1, max_length=64)
    password: SecretStr = Field(min_length=1, max_length=1024)


class ActivateBody(StrictBody):
    token: SecretStr = Field(min_length=43, max_length=43)
    password: SecretStr = Field(min_length=15, max_length=1024)


class InviteBody(StrictBody):
    username: str = Field(min_length=3, max_length=32)
    name: str | None = Field(default=None, min_length=1, max_length=64)


def runtime_for(request):
    return request.app.state.account_http


def session_token(request, audience):
    token = request.cookies.get(cookie_name(audience))
    if not token:
        raise HTTPException(401, "Invalid credentials or session")
    return token


def require_csrf(request, runtime, audience, token):
    values = request.headers.getlist("x-csrf-token")
    if (len(values) != 1 or not re.fullmatch(r"[0-9a-f]{64}", values[0])
            or not hmac.compare_digest(values[0], runtime.csrf(audience, token))):
        raise HTTPException(403, "CSRF verification failed")


class AccountAuthBoundary:
    """Bound the body before parsing; reject spoofed hosts/proxies before SQLite."""
    def __init__(self, app, *, owner, settings, network):
        self.app, self.owner, self.settings, self.network = app, owner, settings, network
        self.origins = {canonical_origin(origin) for origin in settings.origins}

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not auth_path(scope["path"]):
            return await self.app(scope, receive, send)

        async def secured_send(message):
            if message["type"] == "http.response.start":
                names = {key.lower().encode() for key in SAFE_HEADERS}
                message["headers"] = [(key, value) for key, value in message.get("headers", []) if key.lower() not in names]
                message["headers"] += [(key.lower().encode(), value.encode()) for key, value in SAFE_HEADERS.items()]
            await send(message)

        try:
            request = Request(scope)
            runtime = getattr(self.owner.state, "account_http", None)
            if runtime is None:
                raise HTTPException(503, "Authentication service unavailable")
            self.guard(request)
            audience = next((value for value in ("PLAYER", "ADMIN") if scope["path"].startswith(cookie_path(value) + "/")), None)
            token = request.cookies.get(cookie_name(audience)) if audience else None
            if token and len(token) > 128:
                raise HTTPException(400, "Invalid authentication request")
            runtime.limiter.request(scope["client"][0], audience, token)
            if scope["query_string"]:
                raise HTTPException(400, "Authentication query parameters are not supported")
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise HTTPException(415, "Use application/json")
            lengths = request.headers.getlist("content-length")
            if lengths and (len(lengths) != 1 or not lengths[0].isdigit() or int(lengths[0]) > MAX_BODY):
                raise HTTPException(413, "Authentication request too large")
            body = bytearray()
            more = True
            while more:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body.extend(message.get("body", b""))
                if len(body) > MAX_BODY:
                    raise HTTPException(413, "Authentication request too large")
                more = message.get("more_body", False)
            consumed = False

            async def replay_receive():
                nonlocal consumed
                if not consumed:
                    consumed = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            await self.app(scope, replay_receive, secured_send)
        except AuthRateLimited as exc:
            await JSONResponse({"detail": "Too many authentication requests"}, status_code=429,
                               headers={"Retry-After": str(exc.retry_after)})(scope, receive, secured_send)
        except HTTPException as exc:
            await JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)(scope, receive, secured_send)

    def guard(self, request):
        hosts = request.headers.getlist("host")
        origins = request.headers.getlist("origin")
        if len(hosts) != 1 or not self.network.allows_host(hosts[0]):
            raise HTTPException(403, "Host is not allowed")
        if any(key.lower().startswith("x-forwarded-") or key.lower() in {"forwarded", "x-real-ip"} for key in request.headers):
            raise HTTPException(403, "Proxy headers are not supported for account auth in B.3.1")
        try:
            target = canonical_origin(request.scope["scheme"] + "://" + hosts[0])
            peer = ip_address(request.client.host)
            peer_host = f"[{peer}]" if peer.version == 6 else str(peer)
            if target not in self.origins or not demo_host(peer_host):
                raise ValueError()
            if target[0] == "http" and not self.settings.allow_http:
                raise ValueError()
            if (len(origins) > 1 or (origins and canonical_origin(origins[0]) != target)
                    or (not origins and request.method not in {"GET", "HEAD", "OPTIONS"})):
                raise ValueError()
        except (ValueError, AttributeError):
            raise HTTPException(403, "Origin or network peer is not allowed") from None


def install_auth_http(app, settings, network):
    if not settings.enabled:
        return
    if network.read_only:
        raise ValueError("Account HTTP auth requires trusted local/LAN mode, not public read-only mode")
    router = APIRouter(prefix=PREFIX, tags=["Account Auth — legacy APIs are NOT protected"])

    @router.post("/activate")
    async def activate(body: ActivateBody, request: Request):
        runtime = runtime_for(request)
        token = body.token.get_secret_value()
        try:
            runtime.limiter.activation(request.client.host, token)
        except AuthRateLimited as exc:
            raise HTTPException(429, "Too many authentication requests", headers={"Retry-After": str(exc.retry_after)}) from None
        account = await runtime.run(lambda auth, _: auth.activate(token, body.password.get_secret_value()))
        return account_response(account)

    # Separate literal routes prevent the client supplying role/audience fields.
    def audience_routes(audience):
        base = "/" + audience.lower()

        @router.post(base + "/login")
        async def login(body: LoginBody, request: Request):
            runtime = runtime_for(request)
            grant = await runtime.run(lambda auth, _: auth.login(body.username, body.password.get_secret_value(),
                audience=audience, source_key=request.client.host))
            response = JSONResponse(account_response(grant.principal.account, expires_at=grant.expires_at))
            response.set_cookie(cookie_name(audience), grant.token,
                max_age=max(0, grant.expires_at - int(settings.clock())), httponly=True,
                secure=request.scope["scheme"] == "https", samesite="strict", path=cookie_path(audience))
            return response

        @router.get(base + "/me")
        async def me(request: Request):
            token, runtime = session_token(request, audience), runtime_for(request)
            principal = await runtime.run(lambda auth, _: auth.validate_session(token, audience=audience))
            return account_response(principal.account)

        @router.get(base + "/csrf")
        async def csrf(request: Request):
            token, runtime = session_token(request, audience), runtime_for(request)
            await runtime.run(lambda auth, _: auth.validate_session(token, audience=audience))
            return {"csrf_token": runtime.csrf(audience, token)}

        @router.post(base + "/logout")
        async def logout(body: StrictBody, request: Request):
            token, runtime = session_token(request, audience), runtime_for(request)
            require_csrf(request, runtime, audience, token)
            def operation(auth, _):
                auth.validate_session(token, audience=audience)
                return auth.logout(token, audience=audience)
            await runtime.run(operation)
            response = JSONResponse({"logged_out": True})
            response.delete_cookie(cookie_name(audience), path=cookie_path(audience), httponly=True,
                                   secure=request.scope["scheme"] == "https", samesite="strict")
            return response

    audience_routes("PLAYER")
    audience_routes("ADMIN")

    async def admin_operation(request, operation):
        token, runtime = session_token(request, "ADMIN"), runtime_for(request)
        require_csrf(request, runtime, "ADMIN", token)
        return await runtime.run(lambda auth, connection: operation(auth, connection,
                                    auth.validate_session(token, audience="ADMIN")))

    def invitation_json(grant):
        # Raw invitation token only in this authenticated Admin response, never URL.
        return {"invitation_id": grant.invitation_id, "token": grant.token, "expires_at": grant.expires_at,
                "account": account_json(grant.account)}

    @router.post("/admin/invitations", status_code=201)
    async def invite(body: InviteBody, request: Request):
        grant = await admin_operation(request, lambda auth, _, actor: auth.issue_invitation(actor, body.username, name=body.name))
        return invitation_json(grant)

    @router.post("/admin/invitations/{invitation_id}/reissue", status_code=201)
    async def reissue(invitation_id: str, body: StrictBody, request: Request):
        def operation(auth, connection, actor):
            row = connection.execute("SELECT user_id FROM account_tokens WHERE id=? AND purpose='ACCOUNT_INVITE'", (invitation_id,)).fetchone()
            if not row:
                raise InvalidInvitation()
            return auth.reissue_invitation(actor, row[0])
        return invitation_json(await admin_operation(request, operation))

    @router.post("/admin/invitations/{invitation_id}/revoke")
    async def revoke(invitation_id: str, body: StrictBody, request: Request):
        result = await admin_operation(request, lambda auth, _, actor: auth.revoke_invitation(actor, invitation_id))
        return {"revoked": result}

    async def validation_error(request, exc):
        if auth_path(request.url.path):
            # FastAPI's default validation response includes input values, which
            # can contain passwords/tokens. Never echo these even on HTTP 422.
            return JSONResponse({"detail": "Invalid authentication request"}, status_code=422)
        return await request_validation_exception_handler(request, exc)

    app.add_exception_handler(RequestValidationError, validation_error)
    app.include_router(router)
    app.add_middleware(AccountAuthBoundary, owner=app, settings=settings, network=network)
