"""Private integration probes, run INSIDE controller on a disposable test stack.

Never imports/executes uploaded bot code here. Every fixture goes through the
controller compile API and an isolated resource-limited runtime container.
See docs/SANDBOX.md. Production namespaces are deliberately refused.
"""
import base64
import json
import os
import socket
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import docker

namespace = os.environ.get('SANDBOX_NAMESPACE', '')
assert namespace.endswith('-test') and os.environ.get('SANDBOX_TEST_ACK') == '1', 'Use a dedicated *-test namespace'
engine = docker.DockerClient(base_url='unix:///var/run/docker.sock', version='auto', timeout=10)
label = 'io.neonarena.sandbox=' + namespace
assert not engine.containers.list(all=True, filters={'label': label}), 'Test stack must have no active jobs'
owner, token = uuid.uuid4().hex, os.environ['ARENA_RUNNER_TOKEN']
stopped = threading.Event()
checks = []


def rpc(path, data=None, authenticated=True):
    headers = {'Content-Type': 'application/json'}
    if authenticated:
        headers['Authorization'] = 'Bearer ' + token
    request = Request('http://127.0.0.1:9000' + path,
                      data=json.dumps({'owner': owner, **data}).encode() if data is not None else None,
                      headers=headers)
    with build_opener(ProxyHandler({})).open(request, timeout=45) as response:
        return json.load(response)


def check(name):
    checks.append(name)
    print('PASS', name, flush=True)


def heartbeat():
    while not stopped.wait(4):
        rpc('/heartbeat', {})


def compile_bot(code, language='py'):
    job = 'c-' + uuid.uuid4().hex
    payload = {'language': language, 'source': base64.b64encode(code.encode()).decode()}
    result = rpc('/compile/' + job, payload)
    assert result['status'] == 'ready', result
    # A retried compile returns the same immutable artifact, never a new compile.
    assert rpc('/compile/' + job, payload) == result
    return {key: result[key] for key in ('artifact_id', 'artifact_digest')}


def start(artifact):
    job = 'r-' + uuid.uuid4().hex
    assert rpc('/runtime/' + job, artifact)['ready']
    assert rpc('/runtime/' + job, artifact)['ready']
    return job


def request(job, seq=0, observation=None):
    return rpc('/runtime/' + job + '/request', {'seq': seq, 'observation': observation or {}})


def close(job):
    assert rpc('/close/' + job, {})['closed']
    assert not engine.containers.list(all=True, filters={'label': [label, 'io.neonarena.job=' + job]})


def run(code, language='py'):
    job = start(compile_bot(code, language))
    try:
        return request(job)
    finally:
        close(job)


rpc('/owner', {})
thread = threading.Thread(target=heartbeat, daemon=True)
thread.start()
stage = sys.argv[1] if len(sys.argv) > 1 else 'all'
try:
    python = "import sys,json,os\nn=0\nfor line in sys.stdin:\n n+=1\n open('counter','w').write(str(n))\n print(json.dumps({'n':n,'pid':os.getpid(),'file':open('counter').read()}),flush=True)\n"
    artifact = compile_bot(python)
    job = start(artifact)
    try:
        first = request(job)
        duplicate = request(job)
        second = request(job, 1)
        assert first == duplicate
        assert first['action']['n'] == 1 and second['action']['n'] == 2
        assert first['action']['pid'] == second['action']['pid'] and second['action']['file'] == '2'
        container = engine.containers.list(filters={'label': [label, 'io.neonarena.job=' + job]})[0]
        host, config = container.attrs['HostConfig'], container.attrs['Config']
        assert config['User'] == '10001:10001' and host['ReadonlyRootfs']
        assert host['NetworkMode'] == 'none' and not host['Privileged']
        assert host['Memory'] == 256 * 1024**2 and host['MemorySwap'] == host['Memory']
        assert host['PidsLimit'] == 64 and host['NanoCpus'] == 10**9
        assert host['CapDrop'] == ['ALL'] and 'no-new-privileges:true' in host['SecurityOpt']
        assert host['LogConfig']['Type'] == 'none' and not host['Binds']
        assert not container.attrs['Mounts'], 'No persistent/host mounts in bots'
        check('Python persistent process/files + observation deduplication + actual Docker limits')
    finally:
        close(job)

    # Close before create: a delayed create cannot escape cancellation.
    job = 'r-' + uuid.uuid4().hex
    close(job)
    try:
        rpc('/runtime/' + job, artifact)
        raise AssertionError('Closed job restarted')
    except HTTPError as exc:
        assert exc.code == 409
    check('cancel-before-start tombstone')

    if stage in ('languages', 'all'):
        programs = {
            'cpp': '#include <iostream>\n#include <string>\nint main(){std::string s;int n=0;while(std::getline(std::cin,s)){std::cout<<"{\\\"n\\\":"<<++n<<"}"<<std::endl;}}',
            'java': 'import java.io.*; public class Main {public static void main(String[] a)throws Exception{BufferedReader r=new BufferedReader(new InputStreamReader(System.in));int n=0;while(r.readLine()!=null)System.out.println("{\\\"n\\\":"+(++n)+"}");}}',
        }
        # Fixtures contain Java/C++ string escapes, not shell interpolation.
        for language, code in programs.items():
            code = code.replace('\\\\\\"', '\\"')
            job = start(compile_bot(code, language))
            try:
                assert request(job)['action']['n'] == 1
                assert request(job, 1)['action']['n'] == 2
            finally:
                close(job)
            check(language + ' compile + persistent runtime')

    if stage == 'all':
        for language, code in [('py', 'def broken(:'), ('cpp', 'int main('),
                               ('java', 'public class Main {')]:
            compile_id = 'c-' + uuid.uuid4().hex
            payload = {'language': language, 'source': base64.b64encode(code.encode()).decode()}
            result = rpc('/compile/' + compile_id, payload)
            assert result['status'] == 'error' and result['logs'], result
            assert rpc('/compile/' + compile_id, payload) == result
            assert not engine.containers.list(all=True, filters={'label': [label, 'io.neonarena.job=' + compile_id]})
        check('syntax errors in all three languages + compile cleanup/deduplication')
        for code, name in [
            ("import sys\nfor line in sys.stdin: print('not-json',flush=True)", 'invalid JSON'),
            ("while True: pass", 'infinite loop timeout'),
            ("raise RuntimeError('crash')", 'crash'),
            ("import sys,time\nfor line in sys.stdin:\n sys.stdout.write('x'*1000000);sys.stdout.flush();time.sleep(5)", 'stdout cap'),
            ("import sys,time\nfor line in sys.stdin:\n sys.stderr.write('x'*1000000);sys.stderr.flush();time.sleep(5)", 'stderr cap'),
            ("import sys\nfor line in sys.stdin: x=bytearray(400*1024*1024)", 'RAM over-limit'),
        ]:
            result = run(code)
            assert 'bot_error' in result, (name, result)
            check(name + ' + cleanup')

        # Positive control: the target really is listening. An unroutable Internet
        # test address alone would not prove sandbox isolation.
        controller_ip = socket.gethostbyname(socket.gethostname())
        with build_opener(ProxyHandler({})).open(f'http://{controller_ip}:9000/health', timeout=3) as response:
            assert response.status == 200
        policy = '''import sys,json,os,socket
for line in sys.stdin:
 blocked=False
 try:
  socket.create_connection((CONTROLLER_IP,9000),timeout=.3)
 except OSError: blocked=True
 forbidden=['/var/run/docker.sock','/artifacts','/app/data/sessions.json','/app/backend/main.py']
 readonly=False
 try: open('/etc/arena-test','w').write('x')
 except OSError: readonly=True
 status=open('/proc/self/status').read()
 print(json.dumps({'blocked':blocked,'files_absent':all(not os.path.exists(p) for p in forbidden),'secret_absent':not any(k in os.environ for k in ['ARENA_RUNNER_TOKEN','ARENA_ADMIN_CODE']),'readonly':readonly,'uid':os.getuid(),'seccomp':'Seccomp:\\t2' in status,'nnp':'NoNewPrivs:\\t1' in status}),flush=True)
'''
        result = run(policy.replace('CONTROLLER_IP', repr(controller_ip)))['action']
        assert all(result[k] for k in ('blocked', 'files_absent', 'secret_absent', 'readonly', 'seccomp', 'nnp')), result
        assert result['uid'] == 10001
        check('network blocked, private files/secrets absent, rootfs RO, seccomp, no-new-privileges')

        fork = '''import os,time,sys,json
for line in sys.stdin:
 n=0
 try:
  for i in range(256):
   pid=os.fork()
   if pid==0: time.sleep(10);os._exit(0)
   n+=1
 except OSError: pass
 print(json.dumps({'children':n}),flush=True)
'''
        result = run(fork)['action']
        assert 0 < result['children'] < 64, result
        check('PID cap enforced + all descendants removed')

        disk = '''import sys,json,os
for line in sys.stdin:
 written=0;limited=False
 try:
  for n in range(10):
   with open('large'+str(n),'wb',buffering=0) as f:
    for i in range(16): written+=f.write(b'x'*1024*1024)
 except OSError: limited=True
 print(json.dumps({'limited':limited,'written':written}),flush=True)
'''
        result = run(disk)['action']
        assert result['limited'] and result['written'] <= 32*1024**2, result
        check('file size/tmpfs cap')

        jobs = [start(artifact), start(artifact)]
        try:
            with ThreadPoolExecutor(2) as pool:
                results = list(pool.map(lambda j: request(j), jobs))
            assert all(r['action']['n'] == 1 for r in results)
        finally:
            for job in jobs:
                close(job)
        check('two isolated runtime bots concurrently')

        try:
            rpc('/owner', {}, authenticated=False)
            raise AssertionError('Missing auth accepted')
        except HTTPError as exc:
            assert exc.code == 401
        try:
            rpc('/runtime/r-forbidden', {**artifact, 'image': 'arbitrary', 'privileged': True})
            raise AssertionError('Arbitrary Docker arguments accepted')
        except HTTPError as exc:
            assert exc.code == 422
        check('auth + Docker option injection rejected')
finally:
    stopped.set()
    thread.join(timeout=5)
    remaining = engine.containers.list(all=True, filters={'label': label})
    assert not remaining, 'Leaked sandbox containers'
print(json.dumps({'passed': len(checks), 'stage': stage, 'jobs_remaining': 0}), flush=True)
