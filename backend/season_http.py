"""Competition dates, Captain registration, atomic tournament roster and publication."""
import json
import uuid
from fastapi import APIRouter,HTTPException,Request
from pydantic import Field

from .account_database import transaction
from .auth_http import StrictBody,authenticate_account,runtime_for
from .auth_service import PermissionDenied
from .team_tournament_service import TeamTournamentService,TournamentConflict,TournamentNotFound


class SeasonBody(StrictBody):
    name:str=Field(min_length=1,max_length=64)
    game_id:str=Field(min_length=1,max_length=64)
    registration_opens_at:int=Field(ge=0)
    registration_closes_at:int=Field(ge=0)
    starts_at:int=Field(ge=0)
    ends_at:int=Field(ge=0)
    max_teams:int=Field(default=64,ge=2,le=256)


class SeasonTournamentBody(StrictBody):
    format:str=Field(default='round_robin',pattern='^(round_robin|single_elimination|double_elimination|group_knockout|swiss_single_elimination)$')
    qualifier_target:int|None=Field(default=None)


def install_season_http(app):
    router=APIRouter()

    async def execute(request,audience,operation,*,mutation=False):
        actor,_=await authenticate_account(request,audience,csrf=mutation,touch=mutation)
        runtime=runtime_for(request)
        def call(auth,db):
            try:
                user=auth.require_actor(actor,admin=audience=='ADMIN',touch=mutation)
                return operation(auth,db,actor,user,runtime)
            except PermissionDenied:
                raise HTTPException(403,'Season permission denied') from None
            except TournamentNotFound:
                raise HTTPException(404,'Season or tournament not found') from None
            except TournamentConflict as error:
                raise HTTPException(409,str(error)) from None
            except ValueError as error:
                raise HTTPException(422,str(error)) from None
        return await runtime.run(call)

    def season(db,season_id):
        row=db.execute('SELECT * FROM competition_seasons WHERE id=?',(season_id,)).fetchone()
        if not row:raise TournamentNotFound()
        return row

    def member(db,user):
        return db.execute("""SELECT t.id,t.status,m.team_role FROM team_memberships m JOIN teams t ON t.id=m.team_id
            WHERE m.user_id=? AND m.left_at IS NULL""",(user['id'],)).fetchone()

    def public(auth,db,row,user):
        result={key:row[key] for key in ('id','name','game_id','registration_opens_at','registration_closes_at','starts_at','ends_at','max_teams','tournament_id','published_at')}
        result['registration_open']=row['registration_closed_at'] is None and row['registration_opens_at']<=auth._now()<row['registration_closes_at']
        result['registration_closed']=row['registration_closed_at'] is not None or auth._now()>=row['registration_closes_at']
        result['registered_teams']=db.execute("SELECT count(*) FROM competition_season_entries WHERE season_id=? AND status='REGISTERED'",(row['id'],)).fetchone()[0]
        mine=member(db,user) if user['system_role']=='PLAYER' else None
        result['my_registration']=bool(mine and db.execute("SELECT 1 FROM competition_season_entries WHERE season_id=? AND team_id=? AND status='REGISTERED'",(row['id'],mine['id'])).fetchone())
        result['publication']=json.loads(row['publication_json']) if row['publication_json'] else None
        return result

    def audit(db,auth,user,action,season_id):
        db.execute("""INSERT INTO audit_events(occurred_at,actor_user_id,action,target_type,target_id,details_json)
            VALUES (?,?,?,'season',?,'{}')""",(auth._now(),user['id'],action,season_id))

    @router.post('/api/admin/seasons',status_code=201)
    async def create(body:SeasonBody,request:Request):
        def operation(auth,db,actor,user,runtime):
            if body.game_id not in app.state.registry.ids():raise ValueError('Game is not installed')
            if not body.registration_opens_at<body.registration_closes_at<=body.starts_at<body.ends_at:
                raise ValueError('Registration and competition times must be in chronological order')
            name=body.name.strip()
            if not name:raise ValueError('Season name is required')
            season_id=uuid.uuid4().hex
            with transaction(db):
                db.execute("""INSERT INTO competition_seasons
                    (id,name,game_id,registration_opens_at,registration_closes_at,starts_at,ends_at,max_teams,created_by,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",(season_id,name,body.game_id,body.registration_opens_at,body.registration_closes_at,body.starts_at,body.ends_at,body.max_teams,user['id'],auth._now()))
                audit(db,auth,user,'SEASON_CREATED',season_id)
            return {'season':public(auth,db,season(db,season_id),user)}
        return await execute(request,'ADMIN',operation,mutation=True)

    def install(audience):
        prefix='/api/'+audience.lower()+'/seasons'
        @router.get(prefix)
        async def listing(request:Request):
            return await execute(request,audience,lambda auth,db,actor,user,runtime:{'seasons':[public(auth,db,row,user) for row in db.execute('SELECT * FROM competition_seasons ORDER BY created_at DESC,id DESC LIMIT 200')]})
    install('ADMIN');install('PLAYER')

    def registration(action):
        @router.post('/api/player/seasons/{season_id}/'+action)
        async def register(season_id:str,body:StrictBody,request:Request):
            def operation(auth,db,actor,user,runtime):
                with transaction(db):
                    row=season(db,season_id);mine=member(db,user)
                    if not mine or mine['status']!='ACTIVE' or mine['team_role']!='CAPTAIN':raise PermissionDenied()
                    if not public(auth,db,row,user)['registration_open']:raise TournamentConflict('Registration is closed')
                    existing=db.execute('SELECT status FROM competition_season_entries WHERE season_id=? AND team_id=?',(season_id,mine['id'])).fetchone()
                    if action=='register':
                        if existing and existing['status']=='REGISTERED':raise TournamentConflict('Team is already registered')
                        count=db.execute("SELECT count(*) FROM competition_season_entries WHERE season_id=? AND status='REGISTERED'",(season_id,)).fetchone()[0]
                        if count>=row['max_teams']:raise TournamentConflict('Season capacity reached')
                        db.execute("""INSERT INTO competition_season_entries VALUES (?,?,?,?,'REGISTERED')
                            ON CONFLICT(season_id,team_id) DO UPDATE SET registered_by=excluded.registered_by,registered_at=excluded.registered_at,status='REGISTERED'""",(season_id,mine['id'],user['id'],auth._now()))
                    else:
                        if not existing or existing['status']!='REGISTERED':raise TournamentConflict('Team is not registered')
                        db.execute("UPDATE competition_season_entries SET status='WITHDRAWN' WHERE season_id=? AND team_id=?",(season_id,mine['id']))
                    audit(db,auth,user,'SEASON_'+action.upper(),season_id)
                return {'season':public(auth,db,season(db,season_id),user)}
            return await execute(request,'PLAYER',operation,mutation=True)
    registration('register');registration('withdraw')

    @router.get('/api/admin/seasons/{season_id}/entries')
    async def entries(season_id:str,request:Request):
        def operation(auth,db,actor,user,runtime):
            season(db,season_id)
            return {'teams':[dict(row) for row in db.execute("""SELECT t.id,t.display_name,t.status,e.registered_at,
                (SELECT count(*) FROM team_memberships m WHERE m.team_id=t.id AND m.left_at IS NULL) AS member_count
                FROM competition_season_entries e JOIN teams t ON t.id=e.team_id
                WHERE e.season_id=? AND e.status='REGISTERED' ORDER BY e.registered_at,t.id""",(season_id,))]}
        return await execute(request,'ADMIN',operation)

    @router.post('/api/admin/seasons/{season_id}/close-registration')
    async def close(season_id:str,body:StrictBody,request:Request):
        def operation(auth,db,actor,user,runtime):
            with transaction(db):
                row=season(db,season_id)
                if row['tournament_id']:raise TournamentConflict('Tournament roster is already frozen')
                db.execute('UPDATE competition_seasons SET registration_closed_at=? WHERE id=?',(auth._now(),season_id))
                audit(db,auth,user,'SEASON_REGISTRATION_CLOSED',season_id)
            return {'season':public(auth,db,season(db,season_id),user)}
        return await execute(request,'ADMIN',operation,mutation=True)

    @router.post('/api/admin/seasons/{season_id}/tournament',status_code=201)
    async def tournament(season_id:str,body:SeasonTournamentBody,request:Request):
        def operation(auth,db,actor,user,runtime):
            row=season(db,season_id)
            if row['tournament_id'] or (row['registration_closed_at'] is None and auth._now()<row['registration_closes_at']):
                raise TournamentConflict('Close registration before freezing the tournament roster')
            team_ids=[entry[0] for entry in db.execute("SELECT team_id FROM competition_season_entries WHERE season_id=? AND status='REGISTERED' ORDER BY registered_at,team_id",(season_id,))]
            created=TeamTournamentService(db,runtime.writer,auth,app.state.registry).create(actor,name=row['name'],game_id=row['game_id'],team_ids=team_ids,format=body.format,qualifier_target=body.qualifier_target,season_id=season_id)
            return {'tournament':created,'season':public(auth,db,season(db,season_id),user)}
        return await execute(request,'ADMIN',operation,mutation=True)

    @router.post('/api/admin/seasons/{season_id}/publish')
    async def publish(season_id:str,body:StrictBody,request:Request):
        def operation(auth,db,actor,user,runtime):
            with transaction(db):
                row=season(db,season_id)
                if not row['tournament_id'] or row['published_at']:raise TournamentConflict('Season has no unpublished tournament result')
                detail=TeamTournamentService(db,runtime.writer,auth,app.state.registry).detail(actor,row['tournament_id'],admin=True)
                if detail['status']!='COMPLETED':raise TournamentConflict('All tournament matches must be verified before publication')
                if detail['format']=='round_robin':
                    winner=detail['standings'][0]['team_id'] if detail['standings'] else None
                else:
                    finals=[slot for slot in detail['bracket'] if slot.get('winner_team_id') and slot['status'] in ('COMPLETED','BYE')]
                    winner=max(finals,key=lambda slot:slot['round_number'])['winner_team_id'] if finals else None
                champion=next((team for team in detail['teams'] if team['team_id']==winner),None)
                if not champion:raise TournamentConflict('Verified champion is unavailable')
                publication={'champion':champion,'standings':detail['standings'],'format':detail['format']}
                db.execute('UPDATE competition_seasons SET published_at=?,publication_json=? WHERE id=?',(auth._now(),json.dumps(publication),season_id))
                audit(db,auth,user,'SEASON_RESULTS_PUBLISHED',season_id)
            return {'season':public(auth,db,season(db,season_id),user)}
        return await execute(request,'ADMIN',operation,mutation=True)
    app.include_router(router)
