"""Profile, Admin account controls and factual runtime monitoring."""
import asyncio
from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import Field

from .account_database import transaction
from .account_identity import display_name
from .auth_http import StrictBody, authenticate_account, runtime_for
from .auth_service import PermissionDenied, AccountConflict


class ProfileBody(StrictBody):
    display_name: str = Field(min_length=1,max_length=64)


def install_workspace_http(app):
    router=APIRouter()

    async def execute(request,audience,operation,*,mutation=False):
        actor,_=await authenticate_account(request,audience,csrf=mutation,touch=mutation)
        runtime=runtime_for(request)
        def call(auth,db):
            try:
                user=auth.require_actor(actor,admin=audience=='ADMIN',touch=mutation)
                return operation(auth,db,actor,user)
            except PermissionDenied:
                raise HTTPException(403,'Account permission denied') from None
            except AccountConflict as error:
                raise HTTPException(409,str(error)) from None
            except ValueError as error:
                raise HTTPException(422,str(error)) from None
        return await runtime.run(call)

    def install_profile(audience):
        @router.patch('/api/'+audience.lower()+'/profile')
        async def update_profile(body:ProfileBody,request:Request):
            def update(auth,db,actor,user):
                name=display_name(body.display_name)
                with transaction(db):
                    db.execute('UPDATE users SET display_name=?,updated_at=? WHERE id=?',(name,auth._now(),user['id']))
                    db.execute("""INSERT INTO audit_events(occurred_at,actor_user_id,action,target_type,target_id,details_json)
                        VALUES (?,?,'PROFILE_UPDATED','user',?,'{}')""",(auth._now(),user['id'],user['id']))
                return {'account':{**{key:user[key] for key in ('id','username','system_role','status')},'display_name':name}}
            return await execute(request,audience,update,mutation=True)
    install_profile('PLAYER')
    install_profile('ADMIN')

    @router.get('/api/admin/accounts')
    async def accounts(request:Request,search:str=Query(default='',max_length=128),offset:int=Query(default=0,ge=0),limit:int=Query(default=50,ge=1,le=200)):
        def read(auth,db,actor,user):
            query='%'+search.strip()+'%'
            rows=db.execute("""SELECT u.id,u.username,u.display_name,u.system_role,u.status,u.created_at,
                t.display_name AS team_name,t.id AS team_id,m.team_role FROM users u
                LEFT JOIN team_memberships m ON m.user_id=u.id AND m.left_at IS NULL
                LEFT JOIN teams t ON t.id=m.team_id WHERE u.username LIKE ? OR u.display_name LIKE ?
                ORDER BY u.username LIMIT ? OFFSET ?""",(query,query,limit,offset)).fetchall()
            total=db.execute('SELECT count(*) FROM users WHERE username LIKE ? OR display_name LIKE ?',(query,query)).fetchone()[0]
            return {'accounts':[dict(row) for row in rows],'total':total,'offset':offset,'limit':limit}
        return await execute(request,'ADMIN',read)

    @router.post('/api/admin/accounts/{user_id}/disable')
    async def disable(user_id:str,body:StrictBody,request:Request):
        runtime=runtime_for(request)
        def change(auth,db,actor,user):
            target=db.execute('SELECT system_role FROM users WHERE id=?',(user_id,)).fetchone()
            if not target or target['system_role']!='PLAYER':
                raise AccountConflict('This control only manages Player accounts')
            sessions=[row[0] for row in db.execute('SELECT id FROM auth_sessions WHERE user_id=? AND revoked_at IS NULL',(user_id,))]
            changed=auth.disable_account(actor,user_id)
            return changed,sessions
        changed,sessions=await execute(request,'ADMIN',change,mutation=True)
        for session in sessions:
            runtime.notify_revoked(session)
        return {'disabled':changed}

    @router.post('/api/admin/accounts/{user_id}/enable')
    async def enable(user_id:str,body:StrictBody,request:Request):
        def change(auth,db,actor,user):
            with transaction(db):
                target=db.execute('SELECT system_role,status,password_hash FROM users WHERE id=?',(user_id,)).fetchone()
                if not target or target['system_role']!='PLAYER' or target['status']!='DISABLED' or not target['password_hash']:
                    raise AccountConflict('Only a previously activated, disabled Player can be enabled')
                auth._invalidate_user(user_id,auth._now())
                db.execute("UPDATE users SET status='ACTIVE' WHERE id=?",(user_id,))
                db.execute("""INSERT INTO audit_events(occurred_at,actor_user_id,action,target_type,target_id,details_json)
                    VALUES (?,?,'ACCOUNT_ENABLED','user',?,'{}')""",(auth._now(),user['id'],user_id))
            return {'enabled':True}
        return await execute(request,'ADMIN',change,mutation=True)

    @router.get('/api/admin/system')
    async def system(request:Request):
        def snapshot(auth,db,actor,user):
            return {'scrimmages':{row['status']:row['n'] for row in db.execute('SELECT status,count(*) AS n FROM scrimmage_requests GROUP BY status')},
                    'official':{row['status']:row['n'] for row in db.execute('SELECT status,count(*) AS n FROM official_match_requests GROUP BY status')}}
        queues=await execute(request,'ADMIN',snapshot)
        health=await asyncio.to_thread(app.state.runner.health)
        from .main import safe_match
        return {**queues,'runner':{'mode':health.get('mode'),'ready':health.get('ready',False),
                    'battlecode26':health.get('battlecode26',False),'toolchains':{key:bool(value) for key,value in health.get('toolchains',{}).items()}},
                'active_matches':[safe_match(live.meta) for live in app.state.manager.live.values()],
                'capacity':2,'competition':app.state.competition.get_state()['phase'],
                'recent_interruptions':[safe_match(match) for match in app.state.store.get_matches() if match.get('status')=='interrupted'][:10]}

    @router.get('/api/admin/submissions')
    async def submissions(request:Request):
        from .bot_service import bot_public
        return await execute(request,'ADMIN',lambda auth,db,actor,user:{'bots':[bot_public(bot) for bot in app.state.store.get_bots()][:200]})

    @router.get('/api/admin/submissions/{bot_id}')
    async def diagnostics(bot_id:str,request:Request):
        def detail(auth,db,actor,user):
            from .bot_service import bot_compiler_detail
            bot=app.state.store.get_bot(bot_id)
            if not bot:raise HTTPException(404,'Submission not found')
            return {'bot':bot_compiler_detail(bot)}
        return await execute(request,'ADMIN',detail)
    app.include_router(router)
