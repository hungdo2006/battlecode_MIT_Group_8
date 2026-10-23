"""Account-only Team tournament HTTP endpoints."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import Field

from .auth_http import StrictBody, authenticate_account, runtime_for
from .official_service import OfficialConflict, OfficialNotFound, OfficialSchedule
from .offline_results import (OfflineResultsError, export_package, preview,
                              publish_import, imported_results)
from .account_database import require_writer
from .team_tournament_service import (
    TeamTournamentService, TournamentConflict, TournamentNotFound,
)


class CreateTournamentBody(StrictBody):
    name: str = Field(min_length=1, max_length=64)
    game_id: str = Field(min_length=1, max_length=64)
    team_ids: list[str] = Field(min_length=2)
    format: str = Field(default="round_robin", pattern="^(round_robin|single_elimination|group_knockout|double_elimination|swiss_single_elimination)$")
    qualifier_target: int | None = Field(default=None, ge=16, le=64)


class ScheduleFixtureBody(StrictBody):
    bot_lock_at: int = Field(ge=0)
    scheduled_at: int = Field(ge=0)


class ResolveTieBody(StrictBody):
    winner_team_id: str = Field(min_length=1, max_length=128)


class RoundRulesBody(StrictBody):
    rules: dict
    editing_minutes: int = Field(default=20)


class VisibilityBody(StrictBody):
    visibility: str = Field(pattern=r"^(PRIVATE|SIGNED_IN|PUBLIC)$")


class OfflinePackageBody(StrictBody):
    package: dict


class OfflineImportBody(OfflinePackageBody):
    confirm_publish: bool = False


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
            except OfflineResultsError as exc:
                raise HTTPException(422, str(exc)) from None
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
                           team_ids=body.team_ids, format=body.format,
                           qualifier_target=body.qualifier_target), mutation=True)}

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

    @router.post("/api/admin/team-tournaments/{tournament_id}/fixtures/{fixture_id}/resolve-tie")
    async def resolve_tie(tournament_id: str, fixture_id: str, body: ResolveTieBody,
                          request: Request):
        return {"tournament": await execute(request, "ADMIN", lambda service, auth, connection, actor, runtime:
            service.resolve_tie(actor, tournament_id, fixture_id, body.winner_team_id), mutation=True)}

    @router.put("/api/admin/team-tournaments/{tournament_id}/rounds/{stage}/{round_number}/rules")
    async def set_round_rules(tournament_id: str, stage: str, round_number: int,
                              body: RoundRulesBody, request: Request):
        return {"tournament": await execute(request,"ADMIN",
            lambda service, auth, connection, actor, runtime:
                service.save_round_draft(actor,tournament_id,stage,round_number,
                                         body.rules,body.editing_minutes), mutation=True)}

    @router.post("/api/admin/team-tournaments/{tournament_id}/rounds/{stage}/{round_number}/publish")
    async def publish_round(tournament_id: str, stage: str, round_number: int, request: Request):
        return {"tournament": await execute(request,"ADMIN",
            lambda service, auth, connection, actor, runtime:
                service.publish_round(actor,tournament_id,stage,round_number), mutation=True)}

    @router.put("/api/admin/team-tournaments/{tournament_id}/visibility")
    async def set_visibility(tournament_id: str,body:VisibilityBody,request:Request):
        return {"tournament": await execute(request,"ADMIN",
            lambda service, auth, connection, actor, runtime:
                service.set_visibility(actor,tournament_id,body.visibility), mutation=True)}

    @router.get("/api/admin/team-tournaments/{tournament_id}/offline-export")
    async def offline_export(tournament_id: str, request: Request):
        # Export only confirmed results, projected to a public allowlist.
        return {"package": await execute(request, "ADMIN",
            lambda service, auth, connection, actor, runtime:
                export_package(service.detail(actor, tournament_id, admin=True)))}

    @router.post("/api/admin/offline-results/preview")
    async def offline_preview(body: OfflinePackageBody, request: Request):
        return {"preview": await execute(request, "ADMIN",
            lambda service, auth, connection, actor, runtime:
                (auth.require_actor(actor, auth._now(), admin=True), preview(body.package))[1],
            mutation=True)}

    @router.post("/api/admin/offline-results/import")
    async def offline_import(body: OfflineImportBody, request: Request):
        if not body.confirm_publish:
            raise HTTPException(422, "Admin cần xác nhận công bố giải offline.")
        def write(service, auth, connection, actor, runtime):
            auth.require_actor(actor, auth._now(), admin=True)
            require_writer(runtime.writer, runtime.writer.path.parent)
            return publish_import(app.state.store, body.package)
        return {"publication": await execute(request, "ADMIN", write, mutation=True)}

    @router.get("/api/public/standings")
    async def public_standings(request: Request):
        # Allowlist: only tournament metadata and score, never source/replay.
        runtime = runtime_for(request)
        return await runtime.run(
            lambda auth, connection: {
                "tournaments": TeamTournamentService(
                    connection,runtime.writer,auth,app.state.registry).public_standings(),
                "offline_tournaments": imported_results(app.state.store)
            })

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
