"""Account authentication boundaries for coexistence and account-only modes.

The legacy B.3.1 namespace remains available only while coexistence is enabled.
Account-only APIs use audience-scoped prefixes so the browser also scopes the
opaque cookies used by REST and WebSocket handshakes.
"""
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
ACCOUNT_PREFIXES = {"PLAYER": "/api/player", "ADMIN": "/api/admin"}
MAX_BODY = 4096
MAX_API_BODY = 64 * 1024
SAFE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache", "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer"}


def auth_path(path):
    return path == PREFIX or path.startswith(PREFIX + "/")


def account_prefix(audience):
    return ACCOUNT_PREFIXES[audience]


def account_path(path):
    return any(path == prefix or path.startswith(prefix + "/") for prefix in ACCOUNT_PREFIXES.values())


def public_account_auth_path(path):
    return path in {
        account_prefix("PLAYER") + "/auth/login",
        account_prefix("PLAYER") + "/auth/activate",
        account_prefix("ADMIN") + "/auth/login",
    }


def protected_path(path):
    return auth_path(path) or account_path(path)


def cookie_name(audience):
    return "arena_account_" + audience.lower()


def cookie_path(audience):
    return PREFIX + "/" + audience.lower()


def account_cookie_name(audience):
    return "arena_account_" + audience.lower() + "_v2"


def account_cookie_path(audience):
    return account_prefix(audience)


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


def guard_account_scope(scope, headers, settings, network, *, websocket=False):
    hosts, origins = headers.getlist("host"), headers.getlist("origin")
    if len(hosts) != 1 or not network.allows_host(hosts[0]):
        raise HTTPException(403, "Host is not allowed")
    if any(key.lower().startswith("x-forwarded-") or key.lower() in {"forwarded", "x-real-ip"}
           for key in headers):
        raise HTTPException(403, "Proxy headers are not supported for account auth")
    try:
        scheme = {"ws": "http", "wss": "https"}.get(scope["scheme"], scope["scheme"])
        target = canonical_origin(scheme + "://" + hosts[0])
        peer = ip_address(scope["client"][0])
        peer_host = f"[{peer}]" if peer.version == 6 else str(peer)
        configured = {canonical_origin(origin) for origin in settings.origins}
        if target not in configured or not demo_host(peer_host):
            raise ValueError()
        if target[0] == "http" and not settings.allow_http:
            raise ValueError()
        method = scope.get("method", "GET")
        if (len(origins) > 1 or (origins and canonical_origin(origins[0]) != target)
                or (not origins and (websocket or method not in {"GET", "HEAD", "OPTIONS"}))):
            raise ValueError()
    except (ValueError, AttributeError):
        raise HTTPException(403, "Origin or network peer is not allowed") from None


def _env_bool(name):
    value = os.environ.get(name, "0").strip().lower()
    if value not in {"0", "1", "false", "true"}:
        raise ValueError(f"{name} must be 0 or 1")
    return value in {"1", "true"}


@dataclass(frozen=True)
class HTTPAuthSettings:
    enabled: bool = False
    account_only: bool = False
    origins: tuple[str, ...] = ()
    allow_http: bool = False  # Explicit local/LAN QA exception, never HTTPS override.
    policy: AuthPolicy = field(default_factory=AuthPolicy)
    limits: RateLimits = field(default_factory=RateLimits)
    clock: object = field(default=time.time, repr=False)
    rate_clock: object = field(default=time.monotonic, repr=False)

    def __post_init__(self):
        if self.account_only and not self.enabled:
            raise ValueError("ARENA_ACCOUNT_ONLY requires ARENA_ACCOUNT_AUTH=1")
        if self.enabled:
            if not self.origins:
                raise ValueError("ARENA_AUTH_ORIGINS is required when account HTTP auth is enabled")
            for value in self.origins:
                scheme, host, _ = canonical_origin(value)
                if not demo_host(f"[{host}]" if ":" in host else host) or (scheme == "http" and not self.allow_http):
                    raise ValueError("Account auth supports local/LAN origins; HTTP requires explicit QA opt-in")

    @classmethod
    def from_environment(cls):
        enabled, account_only = _env_bool("ARENA_ACCOUNT_AUTH"), _env_bool("ARENA_ACCOUNT_ONLY")
        if not enabled:
            return cls(account_only=account_only)  # Validates the impossible ON/OFF combination.
        return cls(enabled=True, account_only=account_only,
                   origins=tuple(value.strip() for value in os.environ.get("ARENA_AUTH_ORIGINS", "").split(",") if value.strip()),
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
        self._websockets: dict[str, set[asyncio.Event]] = {}
        self._websocket_count = 0

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
        for listeners in tuple(self._websockets.values()):
            for event in tuple(listeners):
                event.set()
        await self._idle.wait()
        await asyncio.to_thread(self._pool.shutdown, wait=True)

    def csrf(self, audience, token):
        return hmac.digest(self._csrf_key, ("csrf\0" + audience + "\0" + token).encode(), "sha256").hex()

    def register_websocket(self, session_id):
        if self._closing or self._websocket_count >= 128 or len(self._websockets.get(session_id, ())) >= 8:
            raise HTTPException(429, "Too many WebSocket connections")
        event = asyncio.Event()
        self._websockets.setdefault(session_id, set()).add(event)
        self._websocket_count += 1
        return event

    def unregister_websocket(self, session_id, event):
        listeners = self._websockets.get(session_id)
        if listeners and event in listeners:
            listeners.remove(event)
            self._websocket_count -= 1
            if not listeners:
                self._websockets.pop(session_id, None)

    def notify_revoked(self, session_id):
        for event in tuple(self._websockets.get(session_id, ())):
            event.set()


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


def strict_cookie(headers, name):
    """Return one unambiguous cookie value; reject duplicate header/name forms."""
    values = headers.getlist("cookie")
    if len(values) > 1:
        raise HTTPException(400, "Ambiguous Cookie header")
    found = []
    for item in values[0].split(";") if values else ():
        key, separator, value = item.strip().partition("=")
        if separator and key == name:
            found.append(value)
    if len(found) != 1 or not found[0] or len(found[0]) > 128:
        raise HTTPException(401 if not found else 400, "Invalid credentials or session")
    return found[0]


def session_token(request, audience):
    return strict_cookie(request.headers, cookie_name(audience))


def account_session_token(request, audience):
    return strict_cookie(request.headers, account_cookie_name(audience))


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
        if scope["type"] != "http" or not protected_path(scope["path"]):
            return await self.app(scope, receive, send)
        if self.settings.account_only and auth_path(scope["path"]):
            # Let the inner account-only gate return 410 without buffering an
            # obsolete B.3.1 credential body.
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
            audience = next((value for value in ("PLAYER", "ADMIN")
                             if scope["path"] == account_prefix(value)
                             or scope["path"].startswith(account_prefix(value) + "/")), None)
            if audience is None:
                audience = next((value for value in ("PLAYER", "ADMIN")
                                 if scope["path"].startswith(cookie_path(value) + "/")), None)
            token_name = account_cookie_name(audience) if audience and account_path(scope["path"]) else cookie_name(audience) if audience else None
            cookie_headers = request.headers.getlist("cookie")
            if len(cookie_headers) > 1:
                raise HTTPException(400, "Ambiguous Cookie header")
            token = request.cookies.get(token_name) if token_name else None
            if token and len(token) > 128:
                raise HTTPException(400, "Invalid authentication request")
            runtime.limiter.request(scope["client"][0], audience, token)
            if scope["query_string"] and (auth_path(scope["path"]) or "/auth/" in scope["path"]):
                raise HTTPException(400, "Authentication query parameters are not supported")
            mutation = request.method not in {"GET", "HEAD", "OPTIONS"}
            if audience and account_path(scope["path"]) and not public_account_auth_path(scope["path"]):
                # Enforce the namespace/audience policy before body buffering or
                # FastAPI routing. Unknown methods and paths cannot bypass auth.
                token = strict_cookie(request.headers, account_cookie_name(audience))
                if mutation:
                    require_csrf(request, runtime, audience, token)
                touch = mutation or scope["path"].endswith(("/auth/me", "/auth/csrf"))
                principal = await runtime.run(
                    lambda auth, _: auth.validate_session(token, audience=audience, touch=touch))
                scope.setdefault("state", {})["account_auth"] = {
                    "audience": audience,
                    "principal": principal,
                    "token": token,
                    "csrf": mutation,
                }
            if mutation:
                if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise HTTPException(415, "Use application/json")
            maximum = MAX_BODY if auth_path(scope["path"]) or "/auth/" in scope["path"] else MAX_API_BODY
            lengths = request.headers.getlist("content-length")
            if lengths and (len(lengths) != 1 or not lengths[0].isdigit() or int(lengths[0]) > maximum):
                raise HTTPException(413, "Authentication request too large")
            body = bytearray()
            more = True
            while more:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body.extend(message.get("body", b""))
                if len(body) > maximum:
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

    def guard(self, request, *, websocket=False):
        guard_account_scope(request.scope, request.headers, self.settings, self.network, websocket=websocket)


async def authenticate_account(request, audience, *, csrf=False, touch=True):
    cached = getattr(request.state, "account_auth", None)
    if cached and cached["audience"] == audience and (not csrf or cached["csrf"]):
        return cached["principal"], cached["token"]
    runtime = runtime_for(request)
    token = account_session_token(request, audience)
    if csrf:
        require_csrf(request, runtime, audience, token)
    principal = await runtime.run(lambda auth, _: auth.validate_session(token, audience=audience, touch=touch))
    return principal, token


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

    player = APIRouter(prefix=account_prefix("PLAYER") + "/auth", tags=["Player Account Auth"])
    admin = APIRouter(prefix=account_prefix("ADMIN") + "/auth", tags=["Admin Account Auth"])

    @player.post("/activate")
    async def account_activate(body: ActivateBody, request: Request):
        runtime = runtime_for(request)
        token = body.token.get_secret_value()
        try:
            runtime.limiter.activation(request.client.host, token)
        except AuthRateLimited as exc:
            raise HTTPException(429, "Too many authentication requests", headers={"Retry-After": str(exc.retry_after)}) from None
        account = await runtime.run(lambda auth, _: auth.activate(token, body.password.get_secret_value()))
        return account_response(account, account_only=settings.account_only)

    def account_audience_routes(audience, target):
        @target.post("/login")
        async def account_login(body: LoginBody, request: Request):
            runtime = runtime_for(request)
            grant = await runtime.run(lambda auth, _: auth.login(
                body.username, body.password.get_secret_value(), audience=audience,
                source_key=request.client.host))
            response = JSONResponse(account_response(
                grant.principal.account, expires_at=grant.expires_at, account_only=settings.account_only))
            response.set_cookie(account_cookie_name(audience), grant.token,
                max_age=max(0, grant.expires_at - int(settings.clock())), httponly=True,
                secure=request.scope["scheme"] == "https", samesite="strict",
                path=account_cookie_path(audience))
            # A namespace change never promotes or transports an old B.3.1 cookie.
            response.delete_cookie(cookie_name(audience), path=cookie_path(audience), httponly=True,
                                   secure=request.scope["scheme"] == "https", samesite="strict")
            return response

        @target.get("/me")
        async def account_me(request: Request):
            principal, _ = await authenticate_account(request, audience)
            return account_response(principal.account, account_only=settings.account_only)

        @target.get("/csrf")
        async def account_csrf(request: Request):
            principal, token = await authenticate_account(request, audience)
            return {"csrf_token": runtime_for(request).csrf(audience, token),
                    "expires_for": principal.audience}

        @target.post("/logout")
        async def account_logout(body: StrictBody, request: Request):
            principal, token = await authenticate_account(request, audience, csrf=True)
            runtime = runtime_for(request)
            await runtime.run(lambda auth, _: auth.logout(token, audience=audience))
            runtime.notify_revoked(principal.session_id)
            response = JSONResponse({"logged_out": True})
            response.delete_cookie(account_cookie_name(audience), path=account_cookie_path(audience),
                                   httponly=True, secure=request.scope["scheme"] == "https", samesite="strict")
            return response

    account_audience_routes("PLAYER", player)
    account_audience_routes("ADMIN", admin)

    async def account_admin_operation(request, operation):
        actor, _ = await authenticate_account(request, "ADMIN", csrf=True)
        return await runtime_for(request).run(lambda auth, connection: operation(auth, connection, actor))

    @admin.post("/invitations", status_code=201)
    async def account_invite(body: InviteBody, request: Request):
        return invitation_json(await account_admin_operation(
            request, lambda auth, _, actor: auth.issue_invitation(actor, body.username, name=body.name)))

    @admin.post("/invitations/{invitation_id}/reissue", status_code=201)
    async def account_reissue(invitation_id: str, body: StrictBody, request: Request):
        def operation(auth, connection, actor):
            row = connection.execute(
                "SELECT user_id FROM account_tokens WHERE id=? AND purpose='ACCOUNT_INVITE'",
                (invitation_id,)).fetchone()
            if not row:
                raise InvalidInvitation()
            return auth.reissue_invitation(actor, row[0])
        return invitation_json(await account_admin_operation(request, operation))

    @admin.post("/invitations/{invitation_id}/revoke")
    async def account_revoke(invitation_id: str, body: StrictBody, request: Request):
        result = await account_admin_operation(
            request, lambda auth, _, actor: auth.revoke_invitation(actor, invitation_id))
        return {"revoked": result}

    async def validation_error(request, exc):
        if auth_path(request.url.path) or "/auth/" in request.url.path:
            # FastAPI's default validation response includes input values, which
            # can contain passwords/tokens. Never echo these even on HTTP 422.
            return JSONResponse({"detail": "Invalid authentication request"}, status_code=422)
        return await request_validation_exception_handler(request, exc)

    app.add_exception_handler(RequestValidationError, validation_error)
    if not settings.account_only:
        app.include_router(router)
    app.include_router(player)
    app.include_router(admin)
    app.add_middleware(AccountAuthBoundary, owner=app, settings=settings, network=network)
