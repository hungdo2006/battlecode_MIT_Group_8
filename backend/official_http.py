"""Account-Only Official Match scheduling, Team visibility and replay APIs."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import Field
from fastapi.responses import FileResponse

from .auth_http import StrictBody,authenticate_account,runtime_for
from .official_service import OfficialSchedule,OfficialConflict,OfficialNotFound


class ScheduleBody(StrictBody):
    team_a_id: str=Field(min_length=1,max_length=128)
    team_b_id: str=Field(min_length=1,max_length=128)
    game_id: str=Field(min_length=1,max_length=64)
    bot_lock_at: int=Field(ge=0)
    scheduled_at: int=Field(ge=0)


def install_official_http(app):
    router=APIRouter()
    async def execute(request,audience,op,*,mutation=False):
        actor,_=await authenticate_account(request,audience,csrf=mutation,touch=mutation)
        rt=runtime_for(request)
        def call(auth,db):
            service=OfficialSchedule(auth=auth,connection=db,writer=rt.writer,
                store=app.state.store,registry=app.state.registry)
            try:
                return op(service,actor)
            except OfficialNotFound:
                raise HTTPException(404,"Official Match or Team not found") from None
            except OfficialConflict:
                raise HTTPException(409,"Official Match conflicts with current state") from None
        return await rt.run(call)

    @router.get("/api/admin/official-matches")
    async def admin_list(request:Request):
        return {"requests":await execute(request,"ADMIN",lambda s,a:s.list_admin(a))}

    @router.get("/api/admin/official-matches/{request_id}")
    async def admin_detail(request_id:str,request:Request):
        return {"request":await execute(request,"ADMIN",lambda s,a:s.detail_admin(a,request_id))}

    @router.post("/api/admin/official-matches",status_code=201)
    async def schedule(body:ScheduleBody,request:Request):
        result=await execute(request,"ADMIN",lambda s,a:s.create(a,
            team_a_id=body.team_a_id,team_b_id=body.team_b_id,game_id=body.game_id,
            bot_lock_at=body.bot_lock_at,scheduled_at=body.scheduled_at),mutation=True)
        return {"request":result}

    @router.post("/api/admin/official-matches/{request_id}/cancel")
    async def cancel(request_id:str,request:Request):
        return {"request":await execute(request,"ADMIN",lambda s,a:s.cancel(a,request_id),mutation=True)}

    @router.get("/api/player/official-matches")
    async def my_matches(request:Request):
        return {"requests":await execute(request,"PLAYER",lambda s,a:s.list_player(a))}

    @router.get("/api/player/official-matches/{request_id}")
    async def player_detail(request_id:str,request:Request):
        return {"request":await execute(request,"PLAYER",lambda s,a:s.detail_player(a,request_id))}

    @router.get("/api/admin/official-matches/{request_id}/replay")
    async def admin_replay(request_id:str,request:Request):
        return await execute(request,"ADMIN",
            lambda s,a:s.replay(a,request_id,audience="ADMIN",manager=app.state.manager))

    @router.get("/api/player/official-matches/{request_id}/replay")
    async def player_replay(request_id:str,request:Request):
        return await execute(request,"PLAYER",
            lambda s,a:s.replay(a,request_id,audience="PLAYER",manager=app.state.manager))

    def install_raw(audience):
        @router.get('/api/'+audience.lower()+'/official-matches/{request_id}/replay.bc26')
        async def raw(request_id:str,request:Request):
            payload=await execute(request,audience,lambda service,actor:service.replay(actor,request_id,audience=audience,manager=app.state.manager))
            match=payload['match']
            path=app.state.store.replays/(match['id']+'.bc26')
            if match.get('game_id')!='battlecode26' or not match.get('raw_replay_available') or not path.is_file():
                from fastapi import HTTPException
                raise HTTPException(404,'Raw Battlecode replay not available')
            return FileResponse(path,filename='official-'+request_id+'.bc26',media_type='application/octet-stream',headers={'Cache-Control':'no-store'})
    install_raw('PLAYER')
    install_raw('ADMIN')

    app.include_router(router)
