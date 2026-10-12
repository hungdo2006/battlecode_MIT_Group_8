import asyncio
import hashlib
import hmac
import os
from copy import deepcopy
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.matches import MatchManager, timestamp
from pydantic import ValidationError
from backend.engine import create_registry
from backend.engine.registry import GameRegistry
from backend.models import GameSelection, MatchRequest, OrganizerCode, SessionUpdate
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
        app.state.manager = MatchManager(app.state.store, tick_seconds)
        app.state.upload_lock = asyncio.Lock()
        yield
        await app.state.manager.shutdown()

    app = FastAPI(title="NEON ARENA", version="2.2.0", lifespan=lifespan)

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
        return {"status": "ok", "toolchains": toolchains(), "protocol": 1,
                "read_only": settings.read_only}

    def session_payload(request: Request):
        return {"participant": request.state.participant, "read_only": settings.read_only,
                "role": app.state.sessions.role(request.state.session_key),
                "organizer_available": admin_digest is not None and not settings.read_only}

    def require_organizer(request: Request):
        if request.state.role != "organizer":
            raise HTTPException(403, "Chỉ Organizer được chỉnh luật và game mặc định.")

    @app.get("/api/session")
    async def session(request: Request):
        return session_payload(request)

    @app.put("/api/session")
    async def rename_session(update: SessionUpdate, request: Request):
        participant = await asyncio.to_thread(app.state.sessions.rename, request.state.session_key, update.name)
        request.state.participant = participant
        return session_payload(request)

    @app.post("/api/session/organizer")
    async def unlock_organizer(unlock: OrganizerCode, request: Request):
        if admin_digest is None:
            raise HTTPException(503, "Máy chủ chưa cấu hình ARENA_ADMIN_CODE.")
        supplied = hashlib.sha256(unlock.code.encode("utf-8")).digest()
        if not hmac.compare_digest(supplied, admin_digest):
            raise HTTPException(403, "Mã Organizer không đúng.")
        app.state.sessions.grant_organizer(request.state.session_key)
        return session_payload(request)

    @app.delete("/api/session/organizer")
    async def leave_organizer(request: Request):
        app.state.sessions.revoke_organizer(request.state.session_key)
        return session_payload(request)

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

    @app.put("/api/games/selected", dependencies=[Depends(require_organizer)])
    async def select_game(selection: GameSelection):
        game_or_404(selection.game_id)
        await asyncio.to_thread(app.state.store.select_game, selection.game_id)
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
        try:
            values = adapter.validate_rules(rules)
        except ValidationError as exc:
            raise HTTPException(422, exc.errors(include_context=False)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return await asyncio.to_thread(app.state.store.set_rules, game_id, values)

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

    async def submit(source: bytes, filename: str, name: str, game_id: str, owner: dict,
                     sample_key: str | None = None):
        game_or_404(game_id)
        async with app.state.upload_lock:
            store = app.state.store
            if sample_key:
                sample_key = f"{owner['id']}:{sample_key}"
                existing = next((bot for bot in store.get_bots() if bot.get("sample_key") == sample_key and bot["status"] == "ready"), None)
                if existing:
                    return public_bot(existing)
            bot_id = store.new_id()
            folder = store.uploads / bot_id
            try:
                status, logs, command = await asyncio.to_thread(prepare_submission, source, filename, folder)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            bot = {"id": bot_id, "name": name.strip()[:48] or Path(filename).stem[:48],
                   "filename": filename, "language": Path(filename).suffix.lower()[1:],
                   "status": status, "logs": logs, "command": command, "folder": str(folder),
                   "created_at": timestamp(), "sample_key": sample_key}
            bot.update(game_id=game_id, owner=deepcopy(owner))
            await asyncio.to_thread(store.save_bot, bot)
            return public_bot(bot)

    @app.post("/api/bots", status_code=201)
    async def upload_bot(request: Request, file: UploadFile = File(...), name: str = Form("", max_length=48),
                         game_id: str = Form(...)):
        filename = (file.filename or "bot.py").replace("\\", "/").split("/")[-1][:128]
        try:
            source = await file.read(MAX_SOURCE_BYTES + 1)
        finally:
            await file.close()
        return await submit(source, filename, name, game_id, request.state.participant)

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

    @app.post("/api/games/{game_id}/samples/{language}/submit", status_code=201)
    async def submit_game_sample(game_id: str, language: str, request: Request):
        sample = sample_info(game_id, language)
        path = PROJECT / "samples" / sample["path"]
        source = path.read_bytes()
        # Updating a sample source creates a new submission instead of silently
        # reusing an older executable. The same source still compiles only once.
        digest = hashlib.sha256(source).hexdigest()[:16]
        return await submit(source, path.name, sample["name"], game_id, request.state.participant,
                            f"{game_id}:{language}:{digest}")

    @app.get("/api/samples/{language}")
    async def download_sample(language: str):
        return await download_game_sample(app.state.store.selected_game_id, language)

    @app.post("/api/samples/{language}/submit", status_code=201)
    async def submit_sample(language: str, request: Request):
        return await submit_game_sample(app.state.store.selected_game_id, language, request)

    @app.get("/api/matches")
    async def matches():
        return app.state.manager.get_matches()

    @app.post("/api/matches", status_code=201)
    async def start_match(request: MatchRequest, http_request: Request):
        # Protect the per-match override too, otherwise /api/matches bypasses Rules permissions.
        if request.rules is not None and http_request.state.role != "organizer":
            raise HTTPException(403, "Player dùng luật đã lưu; chỉ Organizer được gửi rules riêng cho trận.")
        try:
            return await app.state.manager.start(request, created_by=http_request.state.participant)
        except ValidationError as exc:
            raise HTTPException(422, exc.errors(include_context=False)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

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

    app.mount("/static", StaticFiles(directory=PROJECT / "frontend"), name="static")

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(PROJECT / "frontend" / "index.html")

    @app.get("/lan", include_in_schema=False)
    async def lan_guide():
        return FileResponse(PROJECT / "frontend" / "lan.html")

    return app


def public_bot(bot: dict) -> dict:
    return {key: value for key, value in bot.items() if key not in {"command", "folder", "sample_key"}}


app = create_app()
