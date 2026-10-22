"""Disposable loopback-only server for Playwright MCP feature acceptance.

No production directory or credentials are loaded. The runner is deliberately a
fixture: compile files locally, never execute a bot, never claim Docker coverage.
QA-only controls advance the injected clock and materialize a replay fixture.
They are installed ONLY by this script, never by the production application.
"""
import argparse
import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path

import uvicorn
from fastapi import Request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import backend.main as main
from backend.account_database import AccountDatabase, transaction
from backend.auth_http import HTTPAuthSettings
from backend.auth_limits import AuthRateLimiter, RateLimits
from backend.auth_service import AuthService
from backend.execution import LegacyRunner
from backend.writer_lock import WriterLock
from scripts.check_account_ui import seed, PASSWORD


class FixtureRunner(LegacyRunner):
    mode = 'sandbox'

    def health(self):
        return {'mode':'sandbox','ready':True,'toolchains':{'py':True},'qa_fixture':True}

    def prepare(self,source,filename,folder):
        result = super().prepare(source,filename,folder)
        digest = hashlib.sha256(source).hexdigest()
        return {**result,'artifact_id':'qa-fixture-'+folder.name,'artifact_digest':digest,
                'logs':result['logs']+'\nQA fixture: Docker execution is unavailable.'}

    def session(self,*args):
        raise RuntimeError('QA fixture never executes bots')


def run(port):
    with tempfile.TemporaryDirectory(prefix='neon-feature-mcp-') as folder:
        base = Path(folder)
        seed(base)
        with WriterLock(base/'data') as writer, AccountDatabase(base/'data').writer_connection(writer) as db:
            auth = AuthService(db,writer,login_limiter=AuthRateLimiter())
            admin = auth.login('qa.admin',PASSWORD,audience='ADMIN',source_key='feature-qa').principal
            for name in ('qa.member','qa.member2','qa.opponent'):
                invitation = auth.issue_invitation(admin,name,name=name)
                auth.activate(invitation.token,PASSWORD)
        offset = [0]
        clock = lambda: time.time()+offset[0]
        origin = f'http://127.0.0.1:{port}'
        settings = HTTPAuthSettings(enabled=True,account_only=True,origins=(origin,),allow_http=True,
            clock=clock,limits=RateLimits(request_source=10000,session_token=5000,login_source=100,login_account=100))
        main.configured_runner = lambda compile_fn:FixtureRunner(compile_fn)
        # Public health must allow login, while fixture dispatchers deliberately
        # avoid claiming execution. Queue, deadlines and HTTP remain real.
        from backend.official_dispatcher import OfficialDispatcher
        from backend.scrimmage_http import ScrimmageDispatcher
        async def official_tick(dispatcher):
            await dispatcher.runtime.run(lambda auth,db:dispatcher._service(auth,db).freeze_due())
            await dispatcher.runtime.run(lambda auth,db:dispatcher._service(auth,db).sync_execution())
        async def practice_tick(dispatcher):
            await dispatcher.execute(lambda service:service.maintain())
            await dispatcher.execute(lambda service:service.reconcile(dispatcher.manager))
        OfficialDispatcher.tick = official_tick
        ScrimmageDispatcher.tick = practice_tick
        app = main.create_app(base,account_http=settings)

        @app.post('/__qa__/advance')
        async def advance(request: Request):
            seconds = (await request.json())['seconds']
            if type(seconds) is not int or not 0 <= seconds <= 40000:
                raise ValueError('QA clock increment must be an integer from 0 to 40000')
            offset[0] += seconds
            return {'server_time':clock()}

        @app.post('/__qa__/complete-practice')
        async def complete_practice(request: Request):
            request_id = (await request.json())['request_id']
            runtime = app.state.account_http
            def complete(auth,db):
                row = db.execute('SELECT * FROM scrimmage_requests WHERE id=?',(request_id,)).fetchone()
                if not row or row['status'] != 'QUEUED':
                    raise ValueError('A queued fixture request is required')
                plan = json.loads(row['plan_json'])
                match_id = 's'+request_id[:15]
                initial = app.state.registry.get(row['game_id']).create_initial_state(plan['rules_snapshot'])
                final = {**initial,'turn':1,'events':[], 'result':{'winner':'A','reason':'qa_fixture'}}
                match = {'id':match_id,'game_id':row['game_id'],'status':'completed','scrimmage_request_id':request_id,
                         'rules':plan['rules_snapshot'],'result':final['result'],'turn':1,'created_at':int(clock()),
                         'bots':{side:app.state.store.get_bot(slot['bot_id']) for side,slot in plan['slots'].items()}}
                for side,slot in plan['slots'].items():
                    match['bot_'+side.lower()+'_id'] = slot['bot_id']
                    match['player_'+side.lower()+'_id'] = slot['team_id']
                    match['player_'+side.lower()+'_name_snapshot'] = slot['team_name_snapshot']
                app.state.store.save_match(match)
                app.state.store.start_replay(match_id,initial)
                app.state.store.append_replay_frame(match_id,final)
                with transaction(db):
                    db.execute("UPDATE scrimmage_requests SET status='COMPLETED',match_id=?,outcome_json=?,updated_at=? WHERE id=?",
                               (match_id,json.dumps(final['result']),int(clock()),request_id))
                return {'match_id':match_id,'qa_fixture':True}
            return await runtime.run(complete)

        @app.post('/__qa__/shutdown')
        async def shutdown():
            server.should_exit = True
            return {'stopping':True}

        print(f'QA fixture server {origin}; disposable accounts qa.admin/qa.player/qa.member/qa.member2/qa.opponent',flush=True)
        server = uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_level='error',timeout_graceful_shutdown=3))
        server.run()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8791)
    run(parser.parse_args().port)
