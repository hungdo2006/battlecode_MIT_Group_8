"""Account-scoped asynchronous Scrimmage endpoints and queue dispatcher."""
import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import Field

from .auth_http import StrictBody, authenticate_account, runtime_for
from .auth_service import PermissionDenied
from .models import MatchRequest
from .scrimmage_service import Scrimmages
from .team_service import TeamConflict, TeamNotFound

log = logging.getLogger(__name__)


class ChallengeBody(StrictBody):
    game_id: str = Field(min_length=1,max_length=64)
    opponent_team_id: str = Field(min_length=1,max_length=128)


class ScrimmageDispatcher:
    def __init__(self, runtime, store, registry, manager):
        self.runtime, self.store, self.registry, self.manager = runtime, store, registry, manager

    async def execute(self, operation):
        return await self.runtime.run(lambda auth,db: operation(Scrimmages(auth,db,self.runtime.writer,self.store,self.registry)))

    async def recover(self):
        await self.execute(lambda service: service.reconcile(self.manager,recover=True))

    async def tick(self):
        await self.execute(lambda service: service.reconcile(self.manager))
        if getattr(self.manager.runner,'mode',None) != 'sandbox' or len(self.manager.live) >= 2:
            return
        if not (await asyncio.to_thread(self.manager.runner.health)).get('ready'):
            return
        plan = await self.execute(lambda service:service.claim())
        if not plan:
            return
        try:
            await self.manager.start(MatchRequest(game_id=plan['game_id'],bot_a=plan['slots']['A']['bot_id'],bot_b=plan['slots']['B']['bot_id']),
                                     created_by={'kind':'SCRIMMAGE','request_id':plan['id']},scrimmage=plan)
        except Exception:
            log.exception('Scrimmage dispatch failed for %s',plan['id'])
            await self.execute(lambda service:service.fail(plan['id']))
        else:
            await self.execute(lambda service:service.reconcile(self.manager))


def install_scrimmage_http(app):
    router = APIRouter()

    async def execute(request, audience, operation, *, mutation=False):
        actor,_ = await authenticate_account(request,audience,csrf=mutation,touch=mutation)
        runtime = runtime_for(request)
        def call(auth,db):
            service = Scrimmages(auth,db,runtime.writer,app.state.store,app.state.registry)
            try:
                return operation(service,actor)
            except PermissionDenied:
                raise HTTPException(403,'Team permission denied') from None
            except TeamNotFound:
                raise HTTPException(404,'Scrimmage not found') from None
            except TeamConflict as error:
                raise HTTPException(409,str(error)) from None
            except ValueError as error:
                raise HTTPException(422,str(error)) from None
        return await runtime.run(call)

    @router.get('/api/player/scrimmage-opponents')
    async def opponents(request:Request,game_id:str):
        return {'teams':await execute(request,'PLAYER',lambda service,actor:service.opponents(actor,game_id))}

    @router.post('/api/player/scrimmages',status_code=201)
    async def challenge(body:ChallengeBody,request:Request):
        if getattr(app.state.runner,'mode',None) != 'sandbox':
            # Authenticate before advertising runtime capabilities.
            await authenticate_account(request,'PLAYER',csrf=True)
            raise HTTPException(503,'Asynchronous Scrimmage requires Docker Sandbox')
        return {'request':await execute(request,'PLAYER',lambda service,actor:service.create(actor,body.game_id,body.opponent_team_id),mutation=True)}

    def install(audience):
        prefix = '/api/' + audience.lower() + '/scrimmages'
        admin = audience == 'ADMIN'

        @router.get(prefix)
        async def list_requests(request:Request):
            return {'requests':await execute(request,audience,lambda service,actor:service.list(actor,admin=admin))}

        @router.get(prefix+'/{request_id}')
        async def detail(request_id:str,request:Request):
            return {'request':await execute(request,audience,lambda service,actor:service.public(service.detail(actor,request_id,admin=admin)))}

        @router.post(prefix+'/{request_id}/cancel')
        async def cancel(request_id:str,body:StrictBody,request:Request):
            return {'request':await execute(request,audience,lambda service,actor:service.cancel(actor,request_id,admin=admin),mutation=True)}

        async def authorized_replay(request_id,request):
            row = await execute(request,audience,lambda service,actor:dict(service.detail(actor,request_id,admin=admin)))
            if not row['match_id'] or row['status'] not in ('RUNNING','COMPLETED','INTERRUPTED'):
                raise HTTPException(409,'Scrimmage replay is not available yet')
            payload = app.state.manager.get_replay(row['match_id'])
            if not payload or payload['match'].get('scrimmage_request_id') != row['id']:
                raise HTTPException(409,'Scrimmage replay identity mismatch')
            from .main import safe_match
            match = safe_match(payload['match'])
            match['result_correctable'] = False
            if row['status'] == 'COMPLETED':
                match.update(status='completed',result=json.loads(row['outcome_json']))
            elif row['status'] == 'INTERRUPTED':
                match.update(status='interrupted',result={'winner':None,'reason':row['status_reason'],'faults':{}})
            else:
                match.update(status='running',result=None,winner=None)
                for frame in payload['frames']:
                    frame['result'] = None
            return {**payload,'match':match}

        @router.get(prefix+'/{request_id}/replay')
        async def replay(request_id:str,request:Request):
            return await authorized_replay(request_id,request)

        @router.get(prefix+'/{request_id}/replay.bc26')
        async def raw_replay(request_id:str,request:Request):
            payload = await authorized_replay(request_id,request)
            match = payload['match']
            path = app.state.store.replays / (match['id']+'.bc26')
            if match.get('game_id') != 'battlecode26' or not match.get('raw_replay_available') or not path.is_file():
                raise HTTPException(404,'Raw Battlecode replay not available')
            return FileResponse(path,filename='scrimmage-'+request_id+'.bc26',media_type='application/octet-stream',headers={'Cache-Control':'no-store'})

    install('PLAYER')
    install('ADMIN')
    app.include_router(router)
