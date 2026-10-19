"""Account-only Team tournament HTTP endpoints."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from .auth_http import StrictBody, authenticate_account, runtime_for
from .official_service import OfficialConflict, OfficialNotFound, OfficialSchedule
from .team_tournament_service import (
    TeamTournamentService, TournamentConflict, TournamentNotFound,
)


class CreateTournamentBody(StrictBody):
    name: str = Field(min_length=1, max_length=64)
    game_id: str = Field(min_length=1, max_length=64)
    team_ids: list[str] = Field(min_length=2, max_length=16)


class ScheduleFixtureBody(StrictBody):
    bot_lock_at: int = Field(ge=0)
    scheduled_at: int = Field(ge=0)


def install_team_tournament_http(app):
    router = APIRouter()

    async def execute(request, audience, operation, *, mutation=False):
        actor, _ = await authenticate_account(request, audience, csrf=mutation, touch=mutation)
        runtime = runtime_for(request)

        def work(auth, connection):
            service = TeamTournamentService(connection, runtime.writer, auth, app.state.registry)
            try:
                return operation(service, auth, connection, actor, runtime)
            except TournamentNotFound:
                raise HTTPException(404, "Tournament or Team not found") from None
            except (TournamentConflict, OfficialConflict):
                raise HTTPException(409, "Tournament operation conflicts with current state") from None
            except OfficialNotFound:
                raise HTTPException(404, "Tournament fixture or Team not found") from None
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None

        return await runtime.run(work)

    @router.get("/api/admin/team-tournaments")
    async def admin_list(request: Request):
        return {"tournaments": await execute(request, "ADMIN",
            lambda service, auth, connection, actor, runtime: service.list(actor, admin=True))}

    @router.post("/api/admin/team-tournaments", status_code=201)
    async def create(body: CreateTournamentBody, request: Request):
        return {"tournament": await execute(request, "ADMIN", lambda service, auth, connection, actor, runtime:
            service.create(actor, name=body.name, game_id=body.game_id,
                           team_ids=body.team_ids), mutation=True)}

    @router.post("/api/admin/team-tournaments/{tournament_id}/start")
    async def start(tournament_id: str, request: Request):
        return {"tournament": await execute(request, "ADMIN", lambda service, auth, connection, actor, runtime:
            service.start(actor, tournament_id), mutation=True)}

    @router.post("/api/admin/team-tournaments/{tournament_id}/fixtures/{fixture_id}/schedule", status_code=201)
    async def schedule_fixture(tournament_id: str, fixture_id: str, body: ScheduleFixtureBody,
                               request: Request):
        def operation(service, auth, connection, actor, runtime):
            tournament = service.detail(actor, tournament_id, admin=True)
            fixture = next((item for item in tournament["fixtures"] if item["id"] == fixture_id), None)
            if not fixture:
                raise TournamentNotFound("Tournament fixture not found")
            scheduled = OfficialSchedule(connection, runtime.writer, auth,
                app.state.store, app.state.registry).create(actor,
                    team_a_id=fixture["team_a_id"], team_b_id=fixture["team_b_id"],
                    game_id=tournament["game_id"], bot_lock_at=body.bot_lock_at,
                    scheduled_at=body.scheduled_at,
                    team_tournament_fixture_id=fixture_id)
            return {"request": scheduled}

        return await execute(request, "ADMIN", operation, mutation=True)

    @router.get("/api/admin/team-tournaments/{tournament_id}")
    async def admin_detail(tournament_id: str, request: Request):
        return {"tournament": await execute(request, "ADMIN", lambda service, auth, connection, actor, runtime:
            service.detail(actor, tournament_id, admin=True))}

    @router.get("/api/player/team-tournaments")
    async def player_list(request: Request):
        return {"tournaments": await execute(request, "PLAYER", lambda service, auth, connection, actor, runtime:
            service.list(actor))}

    @router.get("/api/player/team-tournaments/{tournament_id}")
    async def player_detail(tournament_id: str, request: Request):
        return {"tournament": await execute(request, "PLAYER", lambda service, auth, connection, actor, runtime:
            service.detail(actor, tournament_id))}

    app.include_router(router)
