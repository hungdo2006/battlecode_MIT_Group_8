import asyncio
import anyio
import hashlib
import hmac
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
from backend.models import ActiveBotSelection, InvitationRequest, GameSelection, OrganizerCode, SessionUpdate
from backend.network import NetworkSettings, lan_addresses, same_origin
from backend.runner import MAX_SOURCE_BYTES, prepare_submission, toolchains
from backend.sessions import COOKIE_NAME, SESSION_SECONDS, Sessions
from backend.storage import Store

PROJECT = Path(__file__).resolve().parent.parent
TERMINAL = {"completed", "interrupted"}


def create_app(base_dir: Path | None = None, tick_seconds: float = 0.18,
               registry: GameRegistry | None = None, network: NetworkSettings | None = None) -> FastAPI:
    installed = registry or create_registry()
    settings = network or NetworkSettings.from_environment()
    admin_code = os.environ.get("ARENA_ADMIN_CODE", "")
    admin_digest = hashlib.sha256(admin_code.encode("utf-8")).digest() if admin_code else None
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.registry = installed
        app.state.store = Store((base_dir or PROJECT).resolve(), installed)
        app.state.sessions = Sessions(app.state.store.data / "sessions.json")
        app.state.runner = configured_runner(lambda *args: prepare_submission(*args))
        await asyncio.to_thread(app.state.runner.startup)
        app.state.manager = MatchManager(app.state.store, tick_seconds, app.state.runner)
        app.state.competition = Competition(app.state.store, app.state.manager)
        app.state.lobby = Lobby(app.state.store, app.state.sessions, app.state.manager, app.state.competition)
        app.state.competition.lobby = app.state.lobby
        app.state.manager.on_activity = app.state.lobby.activity
        app.state.upload_lock = asyncio.Lock()
        try:
            yield
        finally:
            await app.state.lobby.shutdown()
            await app.state.manager.shutdown()
            await asyncio.to_thread(app.state.runner.shutdown)

    app = FastAPI(title="NEON ARENA", version="3.0.0", lifespan=lifespan)

    @app.exception_handler(RunnerUnavailable)
    async def runner_unavailable(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.exception_handler(CompetitionConflict)
    async def competition_conflict(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.middleware("http")
    async def trusted_demo_network(request, call_next):
        host = request.headers.get("host", "")
        if not settings.allows_host(host):
            return JSONResponse({"detail": "Hostname không được phép. Demo mặc định chỉ hỗ trợ local/LAN."}, status_code=403)
        if not same_origin(request.headers.get("origin"), host, request.url.scheme):
            return JSONResponse({"detail": "Origin không được phép."}, status_code=403)
        mutation = request.method not in {"GET", "HEAD", "OPTIONS"}
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
                "read_only": settings.read_only}

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
            result = app.state.lobby.create_invitation(request.state.participant, selection.player_a_id, selection.player_b_id)
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

    app.mount("/static", StaticFiles(directory=PROJECT / "frontend"), name="static")

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(PROJECT / "frontend" / "index.html")

    @app.get("/lan", include_in_schema=False)
    async def lan_guide():
        return FileResponse(PROJECT / "frontend" / "lan.html")

    return app


def public_bot(bot: dict) -> dict:
    return {key: value for key, value in bot.items() if key not in {"command", "folder", "sample_key", "artifact_id", "artifact_digest"}}


app = create_app()
