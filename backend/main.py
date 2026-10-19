import asyncio
import anyio
import hashlib
import hmac
import json
import os
import shutil
from copy import deepcopy
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.execution import RunnerUnavailable, configured_runner
from backend.matches import MatchManager, timestamp
from backend.competition import Competition, CompetitionConflict
from backend.lobby import Lobby
from pydantic import ValidationError
from backend.engine import create_registry
from backend.engine.registry import GameRegistry
from backend.models import (
    ActiveBotSelection,
    InvitationRequest,
    GameSelection,
    OrganizerCode,
    SessionUpdate,
    MatchResultCorrection,
    TournamentCreateRequest,
)
from backend.network import NetworkSettings, lan_addresses, same_origin
from backend.runner import MAX_SOURCE_BYTES, prepare_submission, toolchains
from backend.sessions import COOKIE_NAME, SESSION_SECONDS, Sessions
from backend.storage import Store
from backend.tournament_draws import generate_tournament_draw, tournament_standings
from backend.writer_lock import WriterLock
from backend.account_database import AccountDatabase
from backend.auth_limits import AuthRateLimited
from backend.auth_http import (HTTPAuthSettings, HTTPAuthRuntime, account_path,
    account_prefix, account_cookie_name, authenticate_account, guard_account_scope,
    install_auth_http, strict_cookie)

PROJECT = Path(__file__).resolve().parent.parent
TERMINAL = {"completed", "interrupted"}
MODE_FILE = "access_mode.json"
PENDING_INVITATIONS = {"PENDING", "PARTIALLY_ACCEPTED", "ACCEPTED"}


def _read_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def validate_account_only_cutover(root: Path):
    """Refuse a first authority cutover while legacy work is still active."""
    data = root / "data"
    marker = _read_json(data / MODE_FILE, {})
    rules = _read_json(data / "rules.json", {})
    matches = _read_json(data / "matches.json", {})
    invitations = _read_json(data / "invitations.json", {})
    active_matches = [(item.get("id", key), item) for key, item in matches.items()
                      if item.get("status") in {"queued", "running"}]
    pending = [item.get("id", key) for key, item in invitations.items()
               if item.get("status") in PENDING_INVITATIONS]
    transitioning = marker.get("mode") != "account_only"
    unsafe_matches = active_matches
    if not transitioning and active_matches:
        # Existing Account-Only authority is NOT a first Legacy cutover.
        # An Official match may be persisted as queued/running when the process
        # is killed before Store can mark it interrupted. Fence only matches
        # backed by an already-claimed SQLite Official request; do not let a
        # forged official_request_id bypass the legacy admission guard.
        unsafe_matches = []
        with AccountDatabase(data).read() as connection:
            for match_id, item in active_matches:
                request_id = item.get("official_request_id")
                row = (connection.execute("""SELECT match_id, status
                    FROM official_match_requests WHERE id=?""", (request_id,)).fetchone()
                    if isinstance(request_id, str) else None)
                if (not row or row["match_id"] != match_id or
                    row["status"] not in {"DISPATCHING", "RUNNING", "COMPLETED", "INTERRUPTED"}):
                    unsafe_matches.append((match_id, item))
    if unsafe_matches or pending or (transitioning and rules.get("competition_locked") is True):
        details = []
        if transitioning and rules.get("competition_locked") is True:
            details.append("competition is still open")
        if pending:
            details.append(f"{len(pending)} legacy invitation(s) are pending")
        if unsafe_matches:
            details.append(f"{len(unsafe_matches)} match/job(s) are queued or running")
        raise RuntimeError("Account-only cutover refused: " + "; ".join(details)
                           + ". Close/drain these items in legacy mode, then restart.")


def create_app(base_dir: Path | None = None, tick_seconds: float = 0.18,
               registry: GameRegistry | None = None, network: NetworkSettings | None = None,
               account_http: HTTPAuthSettings | None = None) -> FastAPI:
    installed = registry or create_registry()
    settings = network or NetworkSettings.from_environment()
    account_settings = HTTPAuthSettings.from_environment() if account_http is None else account_http
    if settings.public_gateway != account_settings.public_https:
        raise ValueError("Network Public Gateway and authenticated HTTPS Gateway settings must agree")
    if settings.public_gateway:
        from backend.auth_http import canonical_origin
        required_hosts = {canonical_origin(o)[1] for o in account_settings.origins}
        if set(settings.allowed_hosts) != required_hosts:
            raise ValueError("Public Gateway allowed hosts must exactly match HTTPS origins")
    # The shared Organizer secret has no authority in account-only mode and is
    # deliberately not even loaded into the application process in that mode.
    admin_code = "" if account_settings.account_only else os.environ.get("ARENA_ADMIN_CODE", "")
    admin_digest = hashlib.sha256(admin_code.encode("utf-8")).digest() if admin_code else None
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Must precede Store (startup writes JSON) AND the controller lease claim.
        # /app/data is a shared named volume in both sandbox and legacy Compose.
        with WriterLock((base_dir or PROJECT).resolve() / "data") as writer:
            runner = manager = lobby = auth_runtime = None
            try:
                root = (base_dir or PROJECT).resolve()
                if account_settings.account_only:
                    validate_account_only_cutover(root)
                if account_settings.enabled:
                    auth_runtime = HTTPAuthRuntime(AccountDatabase(writer.path.parent), writer, account_settings)
                    await asyncio.to_thread(auth_runtime.startup)
                    app.state.account_http = auth_runtime
                app.state.registry = installed
                app.state.store = Store(root, installed)
                app.state.sessions = None if account_settings.account_only else Sessions(app.state.store.data / "sessions.json")
                runner = app.state.runner = configured_runner(lambda *args: prepare_submission(*args))
                await asyncio.to_thread(runner.startup)
                manager = app.state.manager = MatchManager(app.state.store, tick_seconds, runner)
                app.state.competition = Competition(app.state.store, manager)
                if account_settings.account_only:
                    app.state.lobby = None
                    manager.on_activity = app.state.competition.publish
                else:
                    lobby = app.state.lobby = Lobby(app.state.store, app.state.sessions, manager, app.state.competition)
                    app.state.competition.lobby = lobby
                    manager.on_activity = lobby.activity
                app.state.upload_lock = asyncio.Lock()
                if account_settings.account_only:
                    from backend.bot_service import TeamBots
                    from backend.official_dispatcher import OfficialDispatcher
                    await auth_runtime.run(lambda auth, conn: TeamBots(
                        auth, conn, writer, app.state.store, installed).reconcile())
                    dispatcher = app.state.official_dispatcher = OfficialDispatcher(
                        auth_runtime, writer, app.state.store, installed, manager)
                    await dispatcher.recover()
                    async def official_deadline_worker():
                        while True:
                            try:
                                await dispatcher.tick()
                            except Exception:
                                import logging
                                logging.getLogger(__name__).exception("Official dispatcher tick failed")
                            await asyncio.sleep(1)
                    app.state.official_deadline_task = asyncio.create_task(
                        official_deadline_worker(), name="official-deadlines")
                await asyncio.to_thread(Store._write, app.state.store.data / MODE_FILE,
                                        {"version": 1, "mode": "account_only" if account_settings.account_only else "legacy"})
                yield
            finally:
                if account_settings.account_only and getattr(app.state, "official_deadline_task", None):
                    app.state.official_deadline_task.cancel()
                    await asyncio.gather(app.state.official_deadline_task, return_exceptions=True)
                # Keep ownership until every cleanup has been attempted, including
                # failed startup. A failed cleanup must not skip runner shutdown.
                try:
                    if lobby is not None:
                        await lobby.shutdown()
                finally:
                    try:
                        if manager is not None:
                            await manager.shutdown()
                    finally:
                        try:
                            if runner is not None:
                                await asyncio.to_thread(runner.shutdown)
                        finally:
                            if auth_runtime is not None:
                                with anyio.CancelScope(shield=True):
                                    await auth_runtime.close()

    app = FastAPI(title="NEON ARENA", version="4.2.0", lifespan=lifespan,
                  docs_url=None if account_settings.account_only else "/docs",
                  redoc_url=None if account_settings.account_only else "/redoc",
                  openapi_url=None if account_settings.account_only else "/openapi.json")

    @app.exception_handler(RunnerUnavailable)
    async def runner_unavailable(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.exception_handler(CompetitionConflict)
    async def competition_conflict(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.middleware("http")
    async def trusted_demo_network(request, call_next):
        if account_settings.enabled and account_path(request.url.path):
            # AccountAuthBoundary enforces stricter LAN/Host/Origin policy here.
            # Do not resolve/create legacy browser identities on account routes.
            return await call_next(request)
        if account_settings.enabled and not account_settings.account_only and (
                request.url.path == "/api/auth" or request.url.path.startswith("/api/auth/")):
            return await call_next(request)
        host = request.headers.get("host", "")
        if not settings.allows_host(host):
            return JSONResponse({"detail": "Hostname không được phép. Demo mặc định chỉ hỗ trợ local/LAN."}, status_code=403)
        if not same_origin(request.headers.get("origin"), host, request.url.scheme):
            return JSONResponse({"detail": "Origin không được phép."}, status_code=403)
        mutation = request.method not in {"GET", "HEAD", "OPTIONS"}
        if account_settings.account_only:
            if request.url.path.startswith("/api/") and request.url.path != "/api/health":
                return JSONResponse({"detail": "Legacy API disabled in account-only mode"}, status_code=410)
            response = await call_next(request)
            if request.url.path.startswith("/api/"):
                response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            return response
        if settings.read_only and mutation and request.url.path != "/api/session":
            return JSONResponse({"detail": "Server ở chế độ chỉ xem; nộp bot, chạy trận và chỉnh luật đã tắt."}, status_code=403)
        identity = await asyncio.to_thread(app.state.sessions.resolve, request.cookies.get(COOKIE_NAME))
        token = None
        if not identity and (request.url.path == "/api/session" or mutation):
            participant, token, key = await asyncio.to_thread(app.state.sessions.create)
            identity = participant, key
        request.state.participant = identity[0] if identity else None
        request.state.session_key = identity[1] if identity else None
        request.state.role = app.state.sessions.role(request.state.session_key)
        response = await call_next(request)
        if token:
            response.set_cookie(COOKIE_NAME, token, max_age=SESSION_SECONDS, httponly=True,
                                samesite="lax", secure=request.url.scheme == "https", path="/")
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.get("/api/health")
    async def health():
        runner = await asyncio.to_thread(app.state.runner.health)
        if not runner["ready"]:
            raise RunnerUnavailable("Sandbox controller is unavailable")
        return {"status": "ok", "runner": runner, "toolchains": runner["toolchains"], "protocol": 1,
                "read_only": settings.read_only, "account_auth": account_settings.enabled,
                "account_only": account_settings.account_only,
                 "self_registration": account_settings.self_registration,
                 "email_verification": account_settings.require_email_verification,
                 "username_only_signup": account_settings.allow_public_username_signup,
                 "admin_totp_required": account_settings.require_admin_totp}

    def session_payload(request: Request):
        return {"participant": request.state.participant, "read_only": settings.read_only,
                "role": app.state.sessions.role(request.state.session_key),
                "organizer_available": admin_digest is not None and not settings.read_only}

    def require_organizer(request: Request):
        if app.state.sessions.role(request.state.session_key) != "organizer":
            raise HTTPException(403, "Chỉ Organizer được thực hiện thao tác quản trị.")

    def require_player(request: Request):
        if app.state.sessions.role(request.state.session_key) != "player":
            raise HTTPException(403, "Organizer không được nộp/chọn bot hoặc tham gia trận với tư cách Player.")

    @app.get("/api/session")
    async def session(request: Request):
        async with app.state.competition.lock:
            app.state.lobby.remember(request.state.participant)
        return session_payload(request)

    @app.put("/api/session")
    async def rename_session(update: SessionUpdate, request: Request):
        async with app.state.competition.lock:
            participant = await asyncio.to_thread(app.state.sessions.rename, request.state.session_key, update.name)
            request.state.participant = participant
            await app.state.competition.publish()
        return session_payload(request)

    @app.post("/api/session/organizer")
    async def unlock_organizer(unlock: OrganizerCode, request: Request):
        if admin_digest is None:
            raise HTTPException(503, "Máy chủ chưa cấu hình ARENA_ADMIN_CODE.")
        supplied = hashlib.sha256(unlock.code.encode("utf-8")).digest()
        if not hmac.compare_digest(supplied, admin_digest):
            raise HTTPException(403, "Mã Organizer không đúng.")
        async with app.state.competition.lock:
            if app.state.lobby.reservation(request.state.participant["id"]):
                raise HTTPException(409, "Hoàn tất lời mời/trận trước khi chuyển sang Organizer.")
            app.state.sessions.grant_organizer(request.state.session_key)
            await app.state.competition.publish()
        return session_payload(request)

    @app.delete("/api/session/organizer")
    async def leave_organizer(request: Request):
        async with app.state.competition.lock:
            app.state.sessions.revoke_organizer(request.state.session_key)
            await app.state.competition.publish()
        return session_payload(request)

    @app.get("/api/players")
    async def players(request: Request):
        return app.state.lobby.snapshot(request.state.participant, request.state.role)["players"]

    @app.delete(
        "/api/players/{player_id}",
        dependencies=[Depends(require_organizer)],
    )
    async def delete_player(player_id: str, request: Request):
        async with app.state.competition.lock:
            require_organizer(request)
            deleted = await asyncio.to_thread(app.state.lobby.delete_player, player_id)
            if not deleted:
                raise HTTPException(404, "Không tìm thấy Player trong danh sách.")
            await app.state.competition.publish()
            return {"player_id": player_id, "deleted": True}

    @app.get("/api/tournaments")
    async def tournaments():
        items = app.state.store.get_tournaments()
        for tournament in items:
            if tournament.get("format") == "round_robin":
                tournament["standings"] = tournament_standings(tournament)
        return items

    @app.post(
        "/api/tournaments",
        status_code=201,
        dependencies=[Depends(require_organizer)],
    )
    async def create_tournament(payload: TournamentCreateRequest, request: Request):
        async with app.state.competition.lock:
            require_organizer(request)

            participants = []
            for player_id in payload.player_ids:
                participant = app.state.lobby.identity(player_id)
                if (
                    not participant
                    or app.state.lobby.role(player_id) != "player"
                ):
                    raise HTTPException(422, f"Không tìm thấy Player hợp lệ: {player_id}")

                participants.append({
                    "player_id": participant["id"],
                    "nickname": participant["name"],
                })

            tournament = {
                "id": app.state.store.new_id(),
                "name": payload.name,
                "format": payload.format,
                "status": "registration",
                "created_at": timestamp(),
                "participants": participants,
                "rounds": [],
            }

            await asyncio.to_thread(
                app.state.store.save_tournament,
                tournament,
            )
            await app.state.competition.publish()
            return tournament

    @app.post(
        "/api/tournaments/{tournament_id}/start",
        dependencies=[Depends(require_organizer)],
    )
    async def start_tournament(tournament_id: str, request: Request):
        async with app.state.competition.lock:
            require_organizer(request)
            tournament = app.state.store.get_tournament(tournament_id)
            if not tournament:
                raise HTTPException(404, "Không tìm thấy giải đấu.")
            if tournament.get("status") != "registration":
                raise HTTPException(409, "Giải đấu đã được bắt đầu hoặc kết thúc.")
            if len(tournament.get("participants", [])) < 2:
                raise HTTPException(409, "Giải đấu cần ít nhất hai người chơi.")
            if not app.state.store.competition_locked:
                raise HTTPException(409, "Hãy mở cuộc thi và khóa game trước khi bắt đầu giải.")

            tournament["rounds"] = generate_tournament_draw(
                tournament,
                app.state.store.new_id,
            )
            tournament["status"] = "active"
            tournament["started_at"] = timestamp()
            tournament["organizer"] = deepcopy(request.state.participant)
            await asyncio.to_thread(app.state.store.save_tournament, tournament)
            await app.state.lobby._schedule_tournament_matches()
            await app.state.competition.publish()
            return app.state.store.get_tournament(tournament_id)

    @app.post(
        "/api/tournaments/{tournament_id}/matches/{tournament_match_id}/retry",
        dependencies=[Depends(require_organizer)],
    )
    async def retry_tournament_match(tournament_id: str, tournament_match_id: str, request: Request):
        async with app.state.competition.lock:
            require_organizer(request)
            tournament = app.state.store.get_tournament(tournament_id)
            if not tournament or tournament.get("status") != "active":
                raise HTTPException(404, "Không tìm thấy giải đang diễn ra.")
            match = next((m for r in tournament.get("rounds", []) for m in r.get("matches", [])
                          if m["id"] == tournament_match_id), None)
            if not match or match.get("status") != "needs_attention":
                raise HTTPException(409, "Trận này không cần gửi lại lời mời.")
            match.update(status="pending", invitation_id=None, match_id=None, result=None,
                         match_status=None, attention_reason=None)
            await asyncio.to_thread(app.state.store.save_tournament, tournament)
            await app.state.lobby._schedule_tournament_matches()
            await app.state.competition.publish()
            return app.state.store.get_tournament(tournament_id)

    @app.delete(
        "/api/tournaments/{tournament_id}",
        dependencies=[Depends(require_organizer)],
    )
    async def delete_tournament(tournament_id: str, request: Request):
        async with app.state.competition.lock:
            require_organizer(request)
            if not app.state.store.get_tournament(tournament_id):
                raise HTTPException(404, "Không tìm thấy giải đấu.")
            active_invitation = any(
                inv.get("tournament_id") == tournament_id
                and (inv.get("status") in {"PENDING", "PARTIALLY_ACCEPTED"}
                     or (inv.get("status") == "STARTED" and inv.get("match_id") in app.state.manager.live))
                for inv in app.state.lobby.invitations.values()
            )
            if active_invitation:
                raise HTTPException(409, "Không thể xóa giải khi còn lời mời hoặc trận giải đang chạy.")
            deleted = await asyncio.to_thread(
                app.state.store.delete_tournament,
                tournament_id,
            )
            if not deleted:
                raise HTTPException(404, "Không tìm thấy giải đấu.")
            await app.state.competition.publish()
            return {"id": tournament_id, "deleted": True}

    @app.get("/api/players/me")
    async def player_me(request: Request):
        if not request.state.participant:
            raise HTTPException(401, "Mở /api/session trước để nhận cookie phiên.")
        async with app.state.competition.lock:
            app.state.lobby.remember(request.state.participant)
            return app.state.lobby.player(request.state.participant["id"])

    @app.put("/api/players/active-bot", dependencies=[Depends(require_player)])
    async def active_bot(selection: ActiveBotSelection, request: Request):
        async with app.state.competition.lock:
            require_player(request)
            result = app.state.lobby.set_active(request.state.participant, selection.bot_id)
            await app.state.competition.publish()
            return result

    @app.get("/api/invitations")
    async def invitations(request: Request):
        return app.state.lobby.snapshot(request.state.participant, request.state.role)["invitations"]

    @app.post("/api/invitations", status_code=201, dependencies=[Depends(require_organizer)])
    async def invite(selection: InvitationRequest, request: Request):
        async with app.state.competition.lock:
            require_organizer(request)
            app.state.lobby.expire()
            result = app.state.lobby.create_invitation(
                request.state.participant, selection.player_a_id, selection.player_b_id)
            await app.state.competition.publish()
            return result

    async def reply(invitation_id, request, accept):
        async with app.state.competition.lock:
            require_player(request)
            try:
                return await app.state.lobby.respond(invitation_id, request.state.participant, accept)
            finally:
                await app.state.competition.publish()

    @app.post("/api/invitations/{invitation_id}/accept", dependencies=[Depends(require_player)])
    async def accept_invitation(invitation_id: str, request: Request, body: dict = Body(default={})):
        if body:
            raise HTTPException(422, "Không nhận player_id hoặc dữ liệu khác; danh tính lấy từ cookie.")
        return await asyncio.shield(reply(invitation_id, request, True))

    @app.post("/api/invitations/{invitation_id}/decline", dependencies=[Depends(require_player)])
    async def decline_invitation(invitation_id: str, request: Request, body: dict = Body(default={})):
        if body:
            raise HTTPException(422, "Không nhận player_id; danh tính lấy từ cookie.")
        return await reply(invitation_id, request, False)

    @app.post("/api/invitations/{invitation_id}/cancel", dependencies=[Depends(require_organizer)])
    async def cancel_invitation(invitation_id: str, request: Request):
        async with app.state.competition.lock:
            require_organizer(request)
            result = app.state.lobby.cancel(invitation_id)
            await app.state.competition.publish()
            return result

    @app.get("/api/network")
    async def network_info(request: Request):
        port = request.url.port or (443 if request.url.scheme == "https" else 80)
        addresses = [] if settings.read_only else await asyncio.to_thread(lan_addresses)
        return {"origin": str(request.base_url).rstrip("/"), "read_only": settings.read_only,
                "lan_urls": [f"{request.url.scheme}://{address}:{port}" for address in addresses]}

    def game_or_404(game_id: str):
        try:
            return installed.get(game_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    def describe_game(game_id):
        return {**installed.describe(game_id), "rules": app.state.store.get_rules(game_id),
                "preview_state": game_or_404(game_id).create_initial_state(app.state.store.get_rules(game_id))}

    @app.get("/api/games")
    async def games():
        return {"selected_game_id": app.state.store.selected_game_id,
                "games": [describe_game(game_id) for game_id in installed.ids()]}

    @app.get("/api/competition")
    async def competition_state():
        return app.state.competition.get_state()

    @app.post("/api/competition/open", dependencies=[Depends(require_organizer)])
    async def open_competition():
        return await app.state.competition.open()

    @app.post("/api/competition/close", dependencies=[Depends(require_organizer)])
    async def close_competition():
        return await app.state.competition.close()

    @app.put("/api/games/selected", dependencies=[Depends(require_organizer)])
    async def select_game(selection: GameSelection):
        game_or_404(selection.game_id)
        control = app.state.competition
        async with control.lock:
            control.require_editable()
            await asyncio.to_thread(app.state.store.select_game, selection.game_id)
            await control.publish()
        return {"selected_game_id": selection.game_id}

    @app.get("/api/games/{game_id}")
    async def game_info(game_id: str):
        game_or_404(game_id)
        return describe_game(game_id)

    @app.get("/api/games/{game_id}/rules")
    async def game_rules(game_id: str):
        game_or_404(game_id)
        return app.state.store.get_rules(game_id)

    async def persist_rules(game_id, rules):
        adapter = game_or_404(game_id)
        control = app.state.competition
        async with control.lock:
            control.require_editable()
            try:
                values = adapter.validate_rules(rules)
            except ValidationError as exc:
                raise HTTPException(422, exc.errors(include_context=False)) from exc
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            saved = await asyncio.to_thread(app.state.store.set_rules, game_id, values)
            await control.publish()
            return saved

    @app.put("/api/games/{game_id}/rules", dependencies=[Depends(require_organizer)])
    async def update_game_rules(game_id: str, rules: dict = Body(...)):
        return await persist_rules(game_id, rules)

    @app.post("/api/games/{game_id}/rules/reset", dependencies=[Depends(require_organizer)])
    async def reset_game_rules(game_id: str):
        return await persist_rules(game_id, game_or_404(game_id).validate_rules())

    @app.get("/api/rules")
    async def get_rules():
        return app.state.store.get_rules(app.state.store.selected_game_id)

    @app.put("/api/rules", dependencies=[Depends(require_organizer)])
    async def save_rules(rules: dict = Body(...)):
        return await persist_rules(app.state.store.selected_game_id, rules)

    @app.get("/api/bots")
    async def bots(game_id: str | None = None):
        if game_id:
            game_or_404(game_id)
        return [public_bot(bot) for bot in app.state.store.get_bots() if not game_id or bot["game_id"] == game_id]

    async def submit(source: bytes, filename: str, name: str, game_id: str, owner: dict, session_key: str,
                     sample_key: str | None = None):
        game_or_404(game_id)
        async with app.state.upload_lock:
            store = app.state.store
            control = app.state.competition
            async with control.lock:
                if app.state.sessions.role(session_key) != "player":
                    raise HTTPException(403, "Organizer không được nộp bot.")
                store.require_submission_game(game_id)
            if sample_key:
                sample_key = f"{owner['id']}:{sample_key}"
                existing = next((bot for bot in store.get_bots() if bot.get("sample_key") == sample_key and bot["status"] == "ready" and bot.get("execution_backend", "legacy") == app.state.runner.mode), None)
                if existing:
                    return public_bot(existing)
            bot_id = store.new_id()
            folder = store.uploads / bot_id
            try:
                prepared = await asyncio.to_thread(app.state.runner.prepare, source, filename, folder)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            bot = {"id": bot_id, "name": name.strip()[:48] or Path(filename).stem[:48],
                   "filename": filename, "language": Path(filename).suffix.lower()[1:],
                   **prepared, "folder": str(folder),
                   "created_at": timestamp(), "sample_key": sample_key}
            bot.update(game_id=game_id, owner=deepcopy(owner))
            try:
                async with control.lock:
                    if app.state.sessions.role(session_key) != "player":
                        raise HTTPException(403, "Phiên đã chuyển sang Organizer; submission bị từ chối.")
                    # Re-check after compilation: the organizer may have switched games.
                    store.require_submission_game(game_id)
                    await asyncio.to_thread(store.save_bot, bot)
            except (CompetitionConflict, HTTPException):
                # Only delete the newly generated submission folder under uploads.
                if folder.resolve().parent == store.uploads.resolve():
                    await asyncio.to_thread(shutil.rmtree, folder)
                raise
            return public_bot(bot)

    @app.post("/api/bots", status_code=201, dependencies=[Depends(require_player)])
    async def upload_bot(request: Request, file: UploadFile = File(...), name: str = Form("", max_length=48),
                         game_id: str = Form(...)):
        filename = (file.filename or "bot.py").replace("\\", "/").split("/")[-1][:128]
        try:
            source = await file.read(MAX_SOURCE_BYTES + 1)
        finally:
            await file.close()
        return await submit(source, filename, name, game_id, request.state.participant, request.state.session_key)

    def sample_info(game_id, language):
        sample = game_or_404(game_id).samples.get(language)
        if not sample:
            raise HTTPException(404, "Không có bot mẫu này cho game đã chọn.")
        return sample

    @app.get("/api/games/{game_id}/samples/{language}")
    async def download_game_sample(game_id: str, language: str):
        sample = sample_info(game_id, language)
        path = PROJECT / "samples" / sample["path"]
        return FileResponse(path, filename=path.name, media_type="text/plain")

    @app.post("/api/games/{game_id}/samples/{language}/submit", status_code=201, dependencies=[Depends(require_player)])
    async def submit_game_sample(game_id: str, language: str, request: Request):
        sample = sample_info(game_id, language)
        path = PROJECT / "samples" / sample["path"]
        source = path.read_bytes()
        # Updating a sample source creates a new submission instead of silently
        # reusing an older executable. The same source still compiles only once.
        digest = hashlib.sha256(source).hexdigest()[:16]
        return await submit(source, path.name, sample["name"], game_id, request.state.participant, request.state.session_key,
                            f"{game_id}:{language}:{digest}")

    @app.get("/api/samples/{language}")
    async def download_sample(language: str):
        return await download_game_sample(app.state.store.selected_game_id, language)

    @app.post("/api/samples/{language}/submit", status_code=201, dependencies=[Depends(require_player)])
    async def submit_sample(language: str, request: Request):
        return await submit_game_sample(app.state.store.selected_game_id, language, request)

    @app.get("/api/standings")
    async def standings(game_id: str | None = Query(default=None)):
        if game_id is not None and game_id not in app.state.store.registry.ids():
            raise HTTPException(404, "Game không tồn tại.")
        return app.state.store.get_standings(game_id)
    
    @app.get("/api/matches")
    async def matches():
        return app.state.manager.get_matches()

    @app.post("/api/matches", status_code=201)
    async def start_match():
        # Retain the route to give older clients an explicit migration response.
        raise HTTPException(403, "Trận chính thức chỉ được tạo từ lời mời Organizer sau khi hai Player Accept.")

    @app.post("/api/matches/{match_id}/cancel", dependencies=[Depends(require_organizer)])
    async def cancel_match(match_id: str):
        if not app.state.manager.get_match(match_id):
            raise HTTPException(404, "Không tìm thấy trận đấu.")
        async with app.state.competition.lock:
            try:
                return await app.state.manager.cancel(match_id)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc

    @app.post("/api/matches/{match_id}/correct-result", dependencies=[Depends(require_organizer)])
    async def correct_match_result(match_id: str, payload: MatchResultCorrection, request: Request):
        require_organizer(request)
        async with app.state.competition.lock:
            match = app.state.manager.get_match(match_id)
            if not match:
                raise HTTPException(404, "Không tìm thấy trận đấu.")
            if match.get("status") != "completed":
                raise HTTPException(409, "Chỉ có thể điều chỉnh kết quả trận đã hoàn tất.")
            if match.get("tournament_id") or match.get("tournament_match_id") or match.get("official_request_id"):
                raise HTTPException(409, "Luồng điều chỉnh này chỉ áp dụng cho trận tự do, không thuộc giải hoặc Team.")
            winner = None if payload.winner == "DRAW" else payload.winner
            if (match.get("result") or {}).get("winner") == winner:
                raise HTTPException(409, "Kết quả mới giống kết quả hiện tại.")
            updated = await asyncio.to_thread(
                app.state.store.correct_match_result,
                match_id, winner, payload.reason, request.state.participant, timestamp(),
            )
            if updated is None:
                raise HTTPException(404, "Không tìm thấy trận đấu.")
            await app.state.competition.publish()
            return updated

    @app.get("/api/matches/{match_id}")
    async def match_info(match_id: str):
        match = app.state.manager.get_match(match_id)
        if not match:
            raise HTTPException(404, "Không tìm thấy trận đấu.")
        return match

    @app.get("/api/matches/{match_id}/replay")
    async def replay(match_id: str):
        payload = app.state.manager.get_replay(match_id)
        if not payload:
            raise HTTPException(404, "Không tìm thấy replay.")
        return payload

    @app.websocket("/ws/matches/{match_id}")
    async def watch(websocket: WebSocket, match_id: str, after: int = Query(-1, ge=-1, le=100000)):
        if account_settings.account_only:
            await websocket.close(code=1008, reason="Legacy WebSocket disabled")
            return
        host = websocket.headers.get("host", "")
        if not settings.allows_host(host) or not same_origin(websocket.headers.get("origin"), host, websocket.scope["scheme"]):
            await websocket.close(code=1008)
            return
        manager = app.state.manager
        match = manager.get_match(match_id)
        if not match:
            await websocket.close(code=1008, reason="Match not found")
            return
        await websocket.accept()
        cursor = after + 1
        live = manager.live.get(match_id)
        try:
            await websocket.send_json({"type": "hello", "match": match})
            if not live:
                payload = manager.get_replay(match_id)
                for seq, frame in enumerate(payload["frames"]):
                    if seq >= cursor:
                        await websocket.send_json({"type": "state", "seq": seq, "state": frame})
                await websocket.send_json({"type": "complete", "match": match})
                await websocket.close(code=1000)
                return
            while True:
                heartbeat = False
                # Snapshot under a condition; send outside the lock so a slow spectator
                # never blocks the simulation. Cursor also allows reconnect without gaps.
                async with live.changed:
                    if cursor >= len(live.frames) and live.meta["status"] not in TERMINAL:
                        try:
                            await asyncio.wait_for(live.changed.wait(), timeout=10)
                        except asyncio.TimeoutError:
                            heartbeat = True
                    frames = [(seq, live.frames[seq]) for seq in range(cursor, len(live.frames))]
                    meta = deepcopy(live.meta)
                for seq, frame in frames:
                    await asyncio.wait_for(websocket.send_json({"type": "state", "seq": seq, "state": frame}), timeout=3)
                    cursor = seq + 1
                if meta["status"] in TERMINAL:
                    await websocket.send_json({"type": "complete", "match": meta})
                    await websocket.close(code=1000)
                    return
                if heartbeat:
                    await websocket.send_json({"type": "ping"})
        except (WebSocketDisconnect, RuntimeError, asyncio.TimeoutError):
            return

    @app.websocket("/ws/competition")
    async def competition_socket(websocket: WebSocket):
        if account_settings.account_only:
            await websocket.close(code=1008, reason="Legacy WebSocket disabled")
            return
        host = websocket.headers.get("host", "")
        if not settings.allows_host(host) or not same_origin(websocket.headers.get("origin"), host, websocket.scope["scheme"]):
            await websocket.close(code=1008)
            return
        identity = app.state.sessions.resolve(websocket.cookies.get(COOKIE_NAME))
        participant, session_key = identity if identity else (None, None)
        await websocket.accept()
        control = app.state.competition
        lobby = app.state.lobby
        connection_id = await lobby.connect(participant) if participant else None
        cursor = -1

        async def receive_heartbeats():
            while True:
                message = await asyncio.wait_for(websocket.receive_json(), timeout=lobby.heartbeat_seconds)
                if message.get("type") == "heartbeat" and participant:
                    await lobby.heartbeat(participant["id"], connection_id)

        async def send_updates():
            nonlocal cursor
            while True:
                heartbeat = False
                async with control.changed:
                    if cursor == control.revision:
                        try:
                            await asyncio.wait_for(control.changed.wait(), timeout=10)
                        except asyncio.TimeoutError:
                            heartbeat = True
                    state = control.get_state()
                if heartbeat:
                    await websocket.send_json({"type": "ping"})
                else:
                    role = app.state.sessions.role(session_key)
                    await asyncio.wait_for(websocket.send_json({"type": "competition", "state": state,
                        "role": role, "lobby": lobby.snapshot(participant, role)}), timeout=3)
                    cursor = state["revision"]
        tasks = [asyncio.create_task(send_updates()), asyncio.create_task(receive_heartbeats())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError:
            pass
        finally:
            # ASGI cancellation must still remove presence and own receive/send tasks.
            with anyio.CancelScope(shield=True):
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                if participant:
                    await lobby.disconnect(participant["id"], connection_id)
                try:
                    await websocket.close()
                except (WebSocketDisconnect, RuntimeError):
                    pass

    if account_settings.enabled:
        async def account_principal(request, audience, *, mutation=False):
            principal, _ = await authenticate_account(request, audience, csrf=mutation, touch=mutation)
            return principal

        def require_empty(body):
            if body:
                raise HTTPException(422, "Request body must be an empty JSON object")

        @app.get("/api/player/games")
        async def account_player_games(request: Request):
            await account_principal(request, "PLAYER")
            return {"selected_game_id": app.state.store.selected_game_id,
                    "games": [describe_game(game_id) for game_id in installed.ids()]}

        @app.get("/api/player/games/{game_id}")
        async def account_player_game(game_id: str, request: Request):
            await account_principal(request, "PLAYER")
            game_or_404(game_id)
            return describe_game(game_id)

        @app.get("/api/player/games/{game_id}/rules")
        async def account_player_rules(game_id: str, request: Request):
            await account_principal(request, "PLAYER")
            game_or_404(game_id)
            return app.state.store.get_rules(game_id)

        @app.get("/api/player/rules")
        async def account_player_selected_rules(request: Request):
            await account_principal(request, "PLAYER")
            return app.state.store.get_rules(app.state.store.selected_game_id)

        @app.get("/api/player/competition")
        async def account_player_competition(request: Request):
            await account_principal(request, "PLAYER")
            return safe_competition(app.state.competition.get_state())

        @app.get("/api/player/games/{game_id}/samples/{language}")
        async def account_player_sample(game_id: str, language: str, request: Request):
            await account_principal(request, "PLAYER")
            sample = sample_info(game_id, language)
            path = PROJECT / "samples" / sample["path"]
            return FileResponse(path, filename=path.name, media_type="text/plain")

        @app.get("/api/player/matches")
        async def account_player_private_resources(request: Request):
            await account_principal(request, "PLAYER")
            raise HTTPException(403, "Player match publication policy is not available yet")

        @app.get("/api/player/matches/{match_id}")
        @app.get("/api/player/matches/{match_id}/replay")
        async def account_player_private_match(match_id: str, request: Request):
            await account_principal(request, "PLAYER")
            raise HTTPException(403, "This match has no verified Player publication policy")

        @app.get("/api/admin/network")
        async def account_admin_network(request: Request):
            await account_principal(request, "ADMIN")
            port = request.url.port or (443 if request.url.scheme == "https" else 80)
            addresses = [] if settings.read_only else await asyncio.to_thread(lan_addresses)
            return {"origin": str(request.base_url).rstrip("/"), "read_only": settings.read_only,
                    "lan_urls": [f"{request.url.scheme}://{address}:{port}" for address in addresses]}

        @app.get("/api/admin/games")
        async def account_admin_games(request: Request):
            await account_principal(request, "ADMIN")
            return {"selected_game_id": app.state.store.selected_game_id,
                    "games": [describe_game(game_id) for game_id in installed.ids()]}

        @app.get("/api/admin/games/{game_id}")
        async def account_admin_game(game_id: str, request: Request):
            await account_principal(request, "ADMIN")
            game_or_404(game_id)
            return describe_game(game_id)

        @app.get("/api/admin/games/{game_id}/rules")
        async def account_admin_rules(game_id: str, request: Request):
            await account_principal(request, "ADMIN")
            game_or_404(game_id)
            return app.state.store.get_rules(game_id)

        @app.get("/api/admin/games/{game_id}/samples/{language}")
        async def account_admin_sample(game_id: str, language: str, request: Request):
            await account_principal(request, "ADMIN")
            sample = sample_info(game_id, language)
            path = PROJECT / "samples" / sample["path"]
            return FileResponse(path, filename=path.name, media_type="text/plain")

        @app.get("/api/admin/rules")
        async def account_admin_selected_rules(request: Request):
            await account_principal(request, "ADMIN")
            return app.state.store.get_rules(app.state.store.selected_game_id)

        @app.get("/api/admin/competition")
        async def account_admin_competition(request: Request):
            await account_principal(request, "ADMIN")
            return safe_competition(app.state.competition.get_state())

        @app.put("/api/admin/games/selected")
        async def account_admin_select(selection: GameSelection, request: Request):
            await account_principal(request, "ADMIN", mutation=True)
            game_or_404(selection.game_id)
            async with app.state.competition.lock:
                app.state.competition.require_editable()
                await asyncio.to_thread(app.state.store.select_game, selection.game_id)
                await app.state.competition.publish()
            return {"selected_game_id": selection.game_id}

        @app.put("/api/admin/games/{game_id}/rules")
        async def account_admin_update_rules(game_id: str, request: Request, rules: dict = Body(...)):
            await account_principal(request, "ADMIN", mutation=True)
            return await persist_rules(game_id, rules)

        @app.post("/api/admin/games/{game_id}/rules/reset")
        async def account_admin_reset_rules(game_id: str, request: Request, body: dict = Body(default={})):
            require_empty(body)
            await account_principal(request, "ADMIN", mutation=True)
            return await persist_rules(game_id, game_or_404(game_id).validate_rules())

        @app.put("/api/admin/rules")
        async def account_admin_save_selected_rules(request: Request, rules: dict = Body(...)):
            await account_principal(request, "ADMIN", mutation=True)
            return await persist_rules(app.state.store.selected_game_id, rules)

        @app.post("/api/admin/competition/open")
        async def account_admin_open(request: Request, body: dict = Body(default={})):
            require_empty(body)
            await account_principal(request, "ADMIN", mutation=True)
            return safe_competition(await app.state.competition.open())

        @app.post("/api/admin/competition/close")
        async def account_admin_close(request: Request, body: dict = Body(default={})):
            require_empty(body)
            await account_principal(request, "ADMIN", mutation=True)
            return safe_competition(await app.state.competition.close())

        @app.get("/api/admin/bots")
        async def account_admin_bots(request: Request):
            await account_principal(request, "ADMIN")
            return [safe_bot(bot) for bot in app.state.store.get_bots()]

        @app.get("/api/admin/matches")
        async def account_admin_matches(request: Request):
            await account_principal(request, "ADMIN")
            from backend.official_service import official_publication
            matches = app.state.manager.get_matches()
            # One SQLite read for the whole history, not one new connection
            # per match. Official results always defer to their durable state.
            published = await app.state.account_http.run(
                lambda _auth, db: [official_publication(db, match) for match in matches])
            return [safe_match(match) for match in published]

        @app.get("/api/admin/matches/{match_id}")
        async def account_admin_match(match_id: str, request: Request):
            await account_principal(request, "ADMIN")
            match = app.state.manager.get_match(match_id)
            if not match:
                raise HTTPException(404, "Không tìm thấy trận đấu.")
            from backend.official_service import official_publication
            published = await app.state.account_http.run(
                lambda _auth, db: official_publication(db, match))
            return safe_match(published)

        @app.get("/api/admin/matches/{match_id}/replay")
        async def account_admin_replay(match_id: str, request: Request):
            actor = await account_principal(request, "ADMIN")
            payload = app.state.manager.get_replay(match_id)
            if not payload:
                raise HTTPException(404, "Không tìm thấy replay.")
            official_id = payload["match"].get("official_request_id")
            if official_id:
                from backend.official_service import (
                    OfficialSchedule, OfficialNotFound, OfficialConflict)
                runtime = app.state.account_http
                def official_replay(auth, db):
                    service = OfficialSchedule(db, runtime.writer, auth,
                                               app.state.store, app.state.registry)
                    return service.replay(actor, official_id, audience="ADMIN",
                                          manager=app.state.manager)
                try:
                    verified = await runtime.run(official_replay)
                except OfficialNotFound:
                    raise HTTPException(404, "Official Match not found") from None
                except OfficialConflict:
                    raise HTTPException(409, "Official replay unavailable") from None
                # Reuse the scoped Official endpoint's status and frame policy.
                verified["match"]["result_correctable"] = False
                return verified
            return {"match": safe_match(payload["match"]), "version": payload.get("version", 1),
                    "frames": payload.get("frames", [])}

        @app.post("/api/admin/matches/{match_id}/cancel")
        async def account_admin_cancel(match_id: str, request: Request, body: dict = Body(default={})):
            require_empty(body)
            await account_principal(request, "ADMIN", mutation=True)
            if not app.state.manager.get_match(match_id):
                raise HTTPException(404, "Không tìm thấy trận đấu.")
            async with app.state.competition.lock:
                try:
                    return safe_match(await app.state.manager.cancel(match_id))
                except ValueError as exc:
                    raise HTTPException(409, str(exc)) from exc

        @app.post("/api/admin/matches/{match_id}/correct-result")
        async def account_admin_correct_match_result(match_id: str, request: Request,
                                                     payload: MatchResultCorrection):
            principal = await account_principal(request, "ADMIN", mutation=True)
            async with app.state.competition.lock:
                match = app.state.manager.get_match(match_id)
                if not match:
                    raise HTTPException(404, "Không tìm thấy trận đấu.")
                if match.get("status") != "completed":
                    raise HTTPException(409, "Chỉ có thể điều chỉnh kết quả trận đã hoàn tất.")
                if match.get("tournament_id") or match.get("tournament_match_id") or match.get("official_request_id"):
                    raise HTTPException(409, "Luồng điều chỉnh này chỉ áp dụng cho trận tự do, không thuộc giải hoặc Team.")
                winner = None if payload.winner == "DRAW" else payload.winner
                if (match.get("result") or {}).get("winner") == winner:
                    raise HTTPException(409, "Kết quả mới giống kết quả hiện tại.")
                updated = await asyncio.to_thread(
                    app.state.store.correct_match_result,
                    match_id, winner, payload.reason,
                    {"id": principal.account.id, "name": principal.account.username}, timestamp(),
                )
                if updated is None:
                    raise HTTPException(404, "Không tìm thấy trận đấu.")
                return safe_match(updated)

        async def account_ws_identity(websocket, audience, *, allowed_query=()):
            try:
                guard_account_scope(websocket.scope, websocket.headers, account_settings, settings, websocket=True)
                if websocket.headers.getlist("sec-websocket-protocol"):
                    raise HTTPException(403, "WebSocket subprotocol credentials are not supported")
                from urllib.parse import parse_qs
                try:
                    query = parse_qs(
                        websocket.scope.get("query_string", b"").decode("ascii"),
                        keep_blank_values=True,
                        strict_parsing=True,
                    )
                except (UnicodeDecodeError, ValueError):
                    raise HTTPException(403, "Unsupported WebSocket query parameter") from None
                if any(key not in allowed_query
                       or key.lower() in {"token", "session", "authorization"}
                       or len(values) != 1
                       for key, values in query.items()):
                    raise HTTPException(403, "Unsupported WebSocket query parameter")
                if "after" in query:
                    try:
                        after = int(query["after"][0])
                    except (TypeError, ValueError):
                        raise HTTPException(403, "Invalid WebSocket cursor") from None
                    if after < -1 or after > 100000:
                        raise HTTPException(403, "Invalid WebSocket cursor")
                token = strict_cookie(websocket.headers, account_cookie_name(audience))
                runtime = app.state.account_http
                from backend.auth_http import trusted_client_address
                runtime.limiter.request(trusted_client_address(
                    websocket.scope, websocket.headers, account_settings), audience, token)
                principal = await runtime.run(
                    lambda auth, _: auth.validate_session(token, audience=audience, touch=False))
                revoked = runtime.register_websocket(principal.session_id)
                return principal, token, revoked, query
            except (HTTPException, AuthRateLimited):
                await websocket.close(code=1008, reason="WebSocket authorization failed")
                return None

        async def revalidate_ws(runtime, token, audience):
            return await runtime.run(lambda auth, _: auth.validate_session(token, audience=audience, touch=False))

        async def account_competition_ws(websocket: WebSocket, audience: str):
            identity = await account_ws_identity(websocket, audience)
            if not identity:
                return
            principal, token, revoked, _ = identity
            runtime, cursor, last_ping = app.state.account_http, -1, 0.0
            await websocket.accept()
            try:
                while True:
                    await revalidate_ws(runtime, token, audience)
                    state = safe_competition(app.state.competition.get_state())
                    if cursor != state["revision"]:
                        await asyncio.wait_for(websocket.send_json({
                            "type": "competition", "state": state, "role": audience.lower(),
                            "account": {"id": principal.account.id, "display_name": principal.account.display_name},
                            "lobby": None}), timeout=3)
                        cursor = state["revision"]
                    now = asyncio.get_running_loop().time()
                    if now - last_ping >= 10:
                        await asyncio.wait_for(websocket.send_json({"type": "ping"}), timeout=3)
                        last_ping = now
                    try:
                        await asyncio.wait_for(revoked.wait(), timeout=2)
                    except asyncio.TimeoutError:
                        continue
                    await revalidate_ws(runtime, token, audience)
            except (WebSocketDisconnect, RuntimeError, asyncio.TimeoutError, HTTPException):
                try:
                    await websocket.close(code=4401, reason="Account session expired or revoked")
                except (WebSocketDisconnect, RuntimeError):
                    pass
            finally:
                runtime.unregister_websocket(principal.session_id, revoked)

        @app.websocket("/api/player/ws/competition")
        async def account_player_competition_ws(websocket: WebSocket):
            await account_competition_ws(websocket, "PLAYER")

        @app.websocket("/api/admin/ws/competition")
        async def account_admin_competition_ws(websocket: WebSocket):
            await account_competition_ws(websocket, "ADMIN")

        @app.websocket("/api/admin/ws/matches/{match_id}")
        async def account_admin_match_ws(websocket: WebSocket, match_id: str):
            identity = await account_ws_identity(websocket, "ADMIN", allowed_query=("after",))
            if not identity:
                return
            principal, token, revoked, query = identity
            after = int(query.get("after", ["-1"])[0])
            runtime = app.state.account_http
            match = app.state.manager.get_match(match_id)
            if not match:
                runtime.unregister_websocket(principal.session_id, revoked)
                await websocket.close(code=1008, reason="Match not found")
                return
            if match.get("official_request_id"):
                # Live Official replay uses its scoped, SQLite-authorized HTTP
                # route. Legacy WS frames have no terminal-evidence gate and
                # must never bypass the Official outcome publication policy.
                runtime.unregister_websocket(principal.session_id, revoked)
                await websocket.close(code=1008, reason="Use Official replay endpoint")
                return
            await websocket.accept()
            cursor = after + 1
            last_auth_check = asyncio.get_running_loop().time()
            try:
                await asyncio.wait_for(
                    websocket.send_json({"type": "hello", "match": safe_match(match)}), timeout=3)
                while True:
                    await revalidate_ws(runtime, token, "ADMIN")
                    last_auth_check = asyncio.get_running_loop().time()
                    live = app.state.manager.live.get(match_id)
                    if live:
                        frames = list(enumerate(live.frames[cursor:], start=cursor))
                        meta = deepcopy(live.meta)
                    else:
                        payload = app.state.manager.get_replay(match_id)
                        frames = list(enumerate((payload or {}).get("frames", [])[cursor:], start=cursor))
                        meta = app.state.manager.get_match(match_id)
                    for seq, frame in frames:
                        if asyncio.get_running_loop().time() - last_auth_check >= 2:
                            await revalidate_ws(runtime, token, "ADMIN")
                            last_auth_check = asyncio.get_running_loop().time()
                        await asyncio.wait_for(websocket.send_json({"type": "state", "seq": seq, "state": frame}), timeout=3)
                        cursor = seq + 1
                    if not live or meta["status"] in TERMINAL:
                        await asyncio.wait_for(websocket.send_json(
                            {"type": "complete", "match": safe_match(meta)}), timeout=3)
                        await websocket.close(code=1000)
                        return
                    try:
                        await asyncio.wait_for(revoked.wait(), timeout=2)
                    except asyncio.TimeoutError:
                        await asyncio.wait_for(websocket.send_json({"type": "ping"}), timeout=3)
                        continue
                    await revalidate_ws(runtime, token, "ADMIN")
            except (WebSocketDisconnect, RuntimeError, asyncio.TimeoutError, HTTPException):
                try:
                    await websocket.close(code=4401, reason="Account session expired or revoked")
                except (WebSocketDisconnect, RuntimeError):
                    pass
            finally:
                runtime.unregister_websocket(principal.session_id, revoked)

    app.mount("/static", StaticFiles(directory=PROJECT / "frontend"), name="static")

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(PROJECT / "frontend" / "index.html")

    @app.get("/lan", include_in_schema=False)
    async def lan_guide():
        return FileResponse(PROJECT / "frontend" / "lan.html")

    install_auth_http(app, account_settings, settings)
    if account_settings.account_only:
        from backend.team_http import install_team_http
        from backend.bot_http import install_bot_http
        from backend.official_http import install_official_http
        from backend.team_tournament_http import install_team_tournament_http
        install_team_http(app)
        install_bot_http(app)
        install_official_http(app)
        install_team_tournament_http(app)
    return app


def public_bot(bot: dict) -> dict:
    return {key: value for key, value in bot.items() if key not in {"command", "folder", "sample_key", "artifact_id", "artifact_digest"}}


def safe_bot(bot: dict) -> dict:
    fields = ("id", "name", "filename", "language", "game_id", "status", "created_at", "execution_backend")
    return {key: deepcopy(bot[key]) for key in fields if key in bot}


def safe_match(match: dict) -> dict:
    fields = ("id", "game_id", "game", "game_name", "game_version", "status", "created_at",
              "started_at", "finished_at", "rules", "rules_snapshot", "turn", "result", "winner",
              "result_corrections",
              "player_a_name_snapshot", "player_b_name_snapshot", "bot_a_id", "bot_b_id",
              "bot_a_name_snapshot", "bot_b_name_snapshot", "bot_a_language", "bot_b_language")
    result = {key: deepcopy(match[key]) for key in fields if key in match}
    result["result_correctable"] = (match.get("status") == "completed"
                                    and not match.get("tournament_id")
                                    and not match.get("tournament_match_id")
                                    and not match.get("official_request_id"))
    result["bots"] = {side: {key: deepcopy(bot[key]) for key in ("id", "name", "language") if key in bot}
                      for side, bot in match.get("bots", {}).items()}
    return result


def safe_competition(state: dict) -> dict:
    fields = ("selected_game_id", "competition_locked", "active_rules_snapshot", "phase",
              "pending_matches", "pending_invitations", "can_edit", "rules", "revision", "server_id")
    return {key: deepcopy(state[key]) for key in fields if key in state}


app = create_app()
