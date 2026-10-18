"""Team bot APIs: bounded JSON/base64 upload, no multipart bypass of account boundary."""
import asyncio
import base64
import binascii
import hashlib
from pathlib import Path
import shutil

from fastapi import APIRouter, Request, HTTPException
from pydantic import Field

from .auth_http import StrictBody, authenticate_account, runtime_for
from .bot_service import TeamBots, bot_compiler_detail
from .runner import MAX_SOURCE_BYTES
from .team_service import TeamConflict, TeamNotFound, TeamPermissionDenied, TeamValidationError


class BotUpload(StrictBody):
    filename: str = Field(min_length=1, max_length=128)
    name: str = Field(default="", max_length=48)
    game_id: str = Field(min_length=1, max_length=64)
    source_base64: str = Field(min_length=1, max_length=350000)


class SelectBot(StrictBody):
    game_id: str = Field(min_length=1, max_length=64)
    bot_id: str = Field(min_length=1, max_length=128)


def install_bot_http(app):
    router = APIRouter()

    async def work(request, operation, *, mutation=False):
        principal, _ = await authenticate_account(request, "PLAYER", csrf=mutation)
        runtime = runtime_for(request)
        def call(auth, db):
            try:
                return operation(TeamBots(auth, db, runtime.writer, app.state.store, app.state.registry), principal)
            except TeamNotFound:
                raise HTTPException(404, "Team bot not found") from None
            except TeamPermissionDenied:
                raise HTTPException(403, "Team permission denied") from None
            except TeamConflict:
                raise HTTPException(409, "Team bot operation conflicts with current state") from None
            except TeamValidationError:
                raise HTTPException(422, "Invalid Team bot request") from None
        return await runtime.run(call)

    @router.get("/api/player/bots")
    async def list_bots(request: Request, game_id: str | None = None):
        return {"bots":await work(request,lambda b,p:b.list_owned(p,game_id=game_id))}

    @router.get("/api/player/bots/{bot_id}")
    async def detail(bot_id: str, request: Request):
        return {"bot":await work(request,lambda b,p:b.bot_detail(p,bot_id))}

    @router.get("/api/player/bots/{bot_id}/source")
    async def source(bot_id: str, request: Request):
        return await work(request, lambda b,p:b.source(p,bot_id))

    @router.post("/api/player/bots", status_code=201)
    async def upload(body: BotUpload, request: Request):
        # Account-only boundary intentionally only accepts JSON mutations.
        try:
            source = base64.b64decode(body.source_base64, validate=True)
        except (ValueError, binascii.Error):
            raise HTTPException(422, "Invalid encoded bot source") from None
        if not source or len(source)>MAX_SOURCE_BYTES or Path(body.filename).name != body.filename or body.filename in (".", ".."):
            raise HTTPException(422, "Invalid bot source length or filename")
        if Path(body.filename).suffix.lower() not in (".py",".cpp",".java"):
            raise HTTPException(422, "Unsupported bot language")
        # Keep a single in-flight account submission per backend. JSON publication
        # precedes SQLite ownership, and the journal is committed before compile.
        async with app.state.upload_lock:
            async with app.state.competition.lock:
                app.state.store.require_submission_game(body.game_id)
                ticket = await work(request,lambda b,p:b.begin(p,body.game_id),mutation=True)
            bot_id=ticket["bot_id"]
            folder=app.state.store.uploads / bot_id
            try:
                prepared=await asyncio.to_thread(app.state.runner.prepare, source, body.filename, folder)
                bot={"id":bot_id,"team_id":ticket["team_id"],"name":body.name.strip() or Path(body.filename).stem[:48],
                     "filename":body.filename,"language":Path(body.filename).suffix.lower()[1:],
                     "game_id":body.game_id,"created_at":ticket["created_at"],**prepared,
                     "source_sha256":hashlib.sha256(source).hexdigest(),"folder":str(folder)}
                async with app.state.competition.lock:
                    app.state.store.require_submission_game(body.game_id)
                    # Revalidate uploader/team/session immediately before publication.
                    await work(request,lambda b,p:b.check_upload(p,ticket),mutation=True)
                    await asyncio.to_thread(app.state.store.save_bot,bot)
                    await work(request,lambda b,p:b.finish(p,bot_id,saved=app.state.store.get_bot(bot_id)),mutation=True)
                return {"bot":bot_compiler_detail(bot)}
            except BaseException:
                # Never delete a published/maybe-committed JSON bot here: retain
                # cross-store artifacts for operator reconciliation, fail closed.
                try:
                    await work(request,lambda b,p:b.abort(bot_id),mutation=True)
                except Exception:
                    pass
                raise

    @router.get("/api/player/active-bot")
    async def active(request:Request, game_id:str):
        return {"active":await work(request,lambda b,p:b.active(p,game_id))}

    @router.put("/api/player/active-bot")
    async def select(body:SelectBot,request:Request):
        return {"active":await work(request,lambda b,p:b.select(p,body.game_id,body.bot_id),mutation=True)}

    app.include_router(router)
