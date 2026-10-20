"""Isolated Docker acceptance: accounts -> Team bots -> offline Scrimmage -> replay.

Builds separate QA arena/controller images and removes only its own Compose resources.
--serve retains the populated temporary server until Ctrl+C for browser inspection.
"""
import argparse
import base64
import json
import secrets
import socket
import subprocess
import time
from pathlib import Path

import httpx
from check_docker import DockerCheck, ROOT
from check_battlecode_engine import JAVA_WAIT, PY_RESIGN


def port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0))
        return listener.getsockname()[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve',action='store_true')
    args=parser.parse_args()
    qa=DockerCheck()
    password=secrets.token_urlsafe(24)
    qa.env.update(ARENA_PORT=str(port()),ARENA_ACCOUNT_AUTH='1',ARENA_ACCOUNT_ONLY='1',
        ARENA_AUTH_ALLOW_HTTP='1',ARENA_SELF_REGISTRATION='1',ARENA_PUBLIC_USERNAME_SIGNUP='0',
        ARENA_ALLOWED_HOSTS='127.0.0.1',ARENA_EMAIL_VERIFICATION='0',ARENA_ADMIN_TOTP_REQUIRED='0',QA_PASSWORD=password)
    origin='http://127.0.0.1:'+qa.env['ARENA_PORT']
    qa.env['ARENA_AUTH_ORIGINS']=origin
    qa.images={'arena':'neon-refinement-arena:local','controller':'neon-refinement-controller:local','bot-image':'neon-arena-bot:4.0'}
    override={'services':{
        'arena':{'image':qa.images['arena'],'environment':{'ARENA_BATTLECODE26':'1'}},
        'controller':{'image':qa.images['controller'],'environment':{'SANDBOX_IMAGE':qa.images['bot-image'],'BATTLECODE_IMAGE':'neon-arena-battlecode:2026'}},
        'bot-image':{'image':qa.images['bot-image']}}}
    qa.override.write_text(json.dumps(override),encoding='utf-8')
    try:
        qa.compose('build','arena','controller',capture=False)
        seed="import os; from pathlib import Path; from backend.admin_cli import bootstrap_admin; bootstrap_admin(Path('/app/data'),'qa.admin',os.environ['QA_PASSWORD'])"
        qa.compose('run','--rm','--no-deps','-e','QA_PASSWORD','--entrypoint','python','arena','-c',seed)
        qa.up()
        clients={}
        def request(client,method,path,body=None,expected=200):
            for attempt in range(2):
                response=client.request(method,path,json=body)
                if response.status_code!=429:
                    break
                time.sleep(min(60,int(response.headers.get('Retry-After','60'))))
            assert response.status_code==expected,(method,path,response.status_code,response.text[:1500])
            return response.json() if response.headers.get('content-type','').startswith('application/json') else response
        def login(username,register=False):
            client=httpx.Client(base_url=origin,headers={'Origin':origin},trust_env=False,timeout=60)
            if register:
                request(client,'POST','/api/account/auth/register',{'username':username,'password':password,
                    'display_name':username,'email':username+'@example.test'},201)
            account=request(client,'POST','/api/account/auth/login',{'username':username,'password':password})
            audience='admin' if account['account']['system_role']=='ADMIN' else 'player'
            token=request(client,'GET','/api/'+audience+'/auth/csrf')['csrf_token']
            client.headers['X-CSRF-Token']=token
            clients[username]=client
            return client
        admin=login('qa.admin')
        health=request(admin,'GET','/api/health')
        assert health['runner']['battlecode26'] and health['runner']['mode']=='sandbox'
        games=request(admin,'GET','/api/admin/games')['games']
        assert {game['game_id'] for game in games}=={'robot_battle','ott_v2','battlecode26'}
        request(admin,'PUT','/api/admin/games/selected',{'game_id':'battlecode26'})
        teams={}
        for username in ('qa.alpha','qa.beta','qa.outsider'):
            client=login(username,True)
            team=request(client,'POST','/api/player/teams',{'slug':username.replace('.','-'),'display_name':username},201)['team']
            request(client,'POST',f"/api/player/teams/{team['id']}/activate",{})
            teams[username]=team['id']
        a,b,outsider=clients['qa.alpha'],clients['qa.beta'],clients['qa.outsider']
        for client,language,source in ((a,'py',PY_RESIGN),(b,'java',JAVA_WAIT)):
            uploaded=request(client,'POST','/api/player/bots',{'game_id':'battlecode26','filename':'bot.py' if language=='py' else 'RobotPlayer.java',
                'name':'QA Battlecode '+language,'source_base64':base64.b64encode(source).decode()},201)['bot']
            assert uploaded['status']=='ready',uploaded
            request(client,'PUT','/api/player/active-bot',{'game_id':'battlecode26','bot_id':uploaded['id']})
        opponents=request(a,'GET','/api/player/scrimmage-opponents?game_id=battlecode26')['teams']
        assert [item['id'] for item in opponents]==[teams['qa.beta']]
        challenge=request(a,'POST','/api/player/scrimmages',{'game_id':'battlecode26','opponent_team_id':teams['qa.beta']},201)['request']
        request_id=challenge['id']
        # Log both participants out: execution must not depend on browser presence.
        request(a,'POST','/api/player/auth/logout',{})
        request(b,'POST','/api/player/auth/logout',{})
        end=time.monotonic()+210
        while time.monotonic()<end:
            detail=request(admin,'GET','/api/admin/scrimmages/'+request_id)['request']
            if detail['status'] in ('COMPLETED','INTERRUPTED'):
                break
            time.sleep(3)
        assert detail['status']=='COMPLETED',detail
        assert detail['result']['winner']=='B' and detail['result']['reason']=='RESIGNATION',detail
        a=login('qa.alpha')
        replay=request(a,'GET',f'/api/player/scrimmages/{request_id}/replay')
        assert replay['match']['game_id']=='battlecode26' and len(replay['frames'])>=4
        assert replay['frames'][-1]['result']['winner']=='B'
        raw=request(a,'GET',f'/api/player/scrimmages/{request_id}/replay.bc26')
        assert raw.content.startswith(b'\x1f\x8b')
        request(outsider,'GET',f'/api/player/scrimmages/{request_id}/replay',expected=404)
        # Season registration -> frozen roster -> real Official match -> publication.
        b=login('qa.beta')
        now=int(time.time())
        season=request(admin,'POST','/api/admin/seasons',{'name':'Battlecode 2026 Acceptance Cup','game_id':'battlecode26',
            'registration_opens_at':now-60,'registration_closes_at':now+600,'starts_at':now+601,'ends_at':now+86400,'max_teams':2},201)['season']
        season_id=season['id']
        request(a,'POST',f'/api/player/seasons/{season_id}/register',{})
        request(b,'POST',f'/api/player/seasons/{season_id}/register',{})
        request(admin,'POST',f'/api/admin/seasons/{season_id}/close-registration',{})
        tournament=request(admin,'POST',f'/api/admin/seasons/{season_id}/tournament',{'format':'single_elimination'},201)['tournament']
        started=request(admin,'POST',f"/api/admin/team-tournaments/{tournament['id']}/start",{})['tournament']
        fixture=started['fixtures'][0]
        now=int(time.time())
        official=request(admin,'POST',f"/api/admin/team-tournaments/{tournament['id']}/fixtures/{fixture['id']}/schedule",
                         {'bot_lock_at':now+3,'scheduled_at':now+6},201)['request']
        end=time.monotonic()+210
        while time.monotonic()<end:
            official_detail=request(admin,'GET',f"/api/admin/official-matches/{official['id']}")['request']
            if official_detail['status'] in ('COMPLETED','INTERRUPTED','BLOCKED'):
                break
            time.sleep(3)
        assert official_detail['status']=='COMPLETED',official_detail
        published=request(admin,'POST',f'/api/admin/seasons/{season_id}/publish',{})['season']
        assert published['publication']['champion']['team_id']==teams['qa.beta'],published
        official_raw=request(a,'GET',f"/api/player/official-matches/{official['id']}/replay.bc26")
        assert official_raw.content.startswith(b'\x1f\x8b')
        round_robin=request(admin,'POST','/api/admin/team-tournaments',{
            'name':'QA Round Robin','game_id':'battlecode26','team_ids':[teams['qa.alpha'],teams['qa.beta']],
            'format':'round_robin'},201)['tournament']
        round_robin=request(admin,'POST',f"/api/admin/team-tournaments/{round_robin['id']}/start",{})['tournament']
        now=int(time.time())
        ranked=request(admin,'POST',f"/api/admin/team-tournaments/{round_robin['id']}/fixtures/{round_robin['fixtures'][0]['id']}/schedule",
                       {'bot_lock_at':now+3,'scheduled_at':now+6},201)['request']
        end=time.monotonic()+210
        while time.monotonic()<end:
            detail=request(admin,'GET',f"/api/admin/official-matches/{ranked['id']}")['request']
            if detail['status'] in ('COMPLETED','INTERRUPTED','BLOCKED'):break
            time.sleep(3)
        assert detail['status']=='COMPLETED',detail
        ranking=request(a,'GET',f"/api/player/team-tournaments/{round_robin['id']}")['tournament']
        assert ranking['status']=='COMPLETED' and ranking['standings'][0]['points']==3,ranking
        practice_games=[]
        for game,first_path,second_path in (
            ('robot_battle','hunter.py','hunter.cpp'),('ott_v2','ott_v2/runner.py','ott_v2/Main.java')):
            request(admin,'PUT','/api/admin/games/selected',{'game_id':game})
            for client,source_path in ((a,first_path),(b,second_path)):
                file=ROOT/'samples'/source_path
                uploaded=request(client,'POST','/api/player/bots',{'game_id':game,'filename':file.name,'name':'QA '+game,
                    'source_base64':base64.b64encode(file.read_bytes()).decode()},201)['bot']
                assert uploaded['status']=='ready',uploaded
                request(client,'PUT','/api/player/active-bot',{'game_id':game,'bot_id':uploaded['id']})
            practice=request(a,'POST','/api/player/scrimmages',{'game_id':game,'opponent_team_id':teams['qa.beta']},201)['request']
            end=time.monotonic()+210
            while time.monotonic()<end:
                result=request(admin,'GET',f"/api/admin/scrimmages/{practice['id']}")['request']
                if result['status'] in ('COMPLETED','INTERRUPTED'):break
                time.sleep(4)
            assert result['status']=='COMPLETED',result
            assert result['result']['reason']!='bot_error',result
            practice_games.append({'game':game,'request_id':practice['id'],'result':result['result']})
        # Restore Battlecode as the visible review game after multi-game regression.
        request(admin,'PUT','/api/admin/games/selected',{'game_id':'battlecode26'})
        # Account controls, profile and monitoring operate on the actual backend.
        renamed=request(a,'PATCH','/api/player/profile',{'display_name':'Nguyen Minh Anh'})
        assert renamed['account']['display_name']=='Nguyen Minh Anh'
        accounts=request(admin,'GET','/api/admin/accounts?search=qa.outsider')['accounts']
        assert len(accounts)==1 and 'password_hash' not in json.dumps(accounts)
        outsider_id=accounts[0]['id']
        request(admin,'POST',f'/api/admin/accounts/{outsider_id}/disable',{})
        request(outsider,'GET','/api/player/auth/me',expected=401)
        request(admin,'POST',f'/api/admin/accounts/{outsider_id}/enable',{})
        request(outsider,'GET','/api/player/auth/me',expected=401)
        system=request(admin,'GET','/api/admin/system')
        assert system['runner']['ready'] and system['runner']['battlecode26']
        report={'status':'PASS','engine_commit':replay['match']['engine_commit'],'scrimmage_id':request_id,
                'frames':len(replay['frames']),'offline_execution':True,'outsider_replay_denied':True,'raw_bc26_bytes':len(raw.content),
                'season_id':season_id,'tournament_id':tournament['id'],'official_id':official['id'],
                'verified_publication':True,'profile_updated':True,'disable_enable_revokes_old_session':True,'admin_monitor':True}
        report['ranked_tournament_id']=round_robin['id']
        report['ranked_standings']=ranking['standings']
        report['practice_games']=practice_games
        output=ROOT/'design-research'/'battlecode26-engine'
        output.mkdir(parents=True,exist_ok=True)
        (output/'platform-acceptance.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print('PASS real Docker platform:',json.dumps(report),flush=True)
        if args.serve:
            # Disposable fixture credentials stay local and are never printed or committed.
            (output/'browser-session.json').write_text(json.dumps({'origin':origin,'password':password,'request_id':request_id,'project':qa.project,'override':str(qa.override),'official_id':official['id']}),encoding='utf-8')
            print('Browser review READY at '+origin,flush=True)
            stop=output/'stop-platform-review'
            if stop.exists():stop.unlink()
            while not stop.exists():
                time.sleep(1)
    except subprocess.CalledProcessError as error:
        print((error.stderr or error.stdout or '')[-6000:],flush=True)
        try:
            print(qa.compose('logs','--tail','50','arena','controller').stdout[-9000:],flush=True)
        except subprocess.CalledProcessError:
            pass
        raise
    except KeyboardInterrupt:
        pass
    finally:
        for client in locals().get('clients',{}).values():
            client.close()
        qa.cleanup()


if __name__=='__main__':
    main()
