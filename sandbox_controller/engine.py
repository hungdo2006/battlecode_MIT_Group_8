"""All Docker parameters are fixed here, never accepted from an API caller."""
import base64
import json
import queue
import struct
import threading
import time

import docker
from docker.types import LogConfig, Ulimit

from backend.runner import (BotError, COMPILE_TIMEOUT, MAX_LINE_BYTES, MAX_STDERR_BYTES,
                            MAX_STDOUT_BYTES, STARTUP_TIMEOUT, TURN_TIMEOUT, reject_constant)
from sandbox_controller.artifacts import MAX_ARTIFACT

LABEL = 'io.neonarena.sandbox'
COMMANDS = {
    'py': ['python', '-u', '-B', '/work/app/bot.py'],
    'cpp': ['/work/app/bot'],
    'java': ['java', '-Xmx64m', '-XX:ActiveProcessorCount=1', '-XX:+UseSerialGC',
             '-XX:MaxMetaspaceSize=64m', '-cp', '/work/app', 'Main'],
}
COMPILE = {
    'py': ['python', '-m', 'py_compile', '/work/src/bot.py'],
    'cpp': ['g++', '-std=c++17', '-O2', '/work/src/bot.cpp', '-o', '/work/out/bot'],
    'java': ['javac', '-J-Xmx128m', '-J-XX:ActiveProcessorCount=1', '-encoding', 'UTF-8',
             '-d', '/work/out', '/work/src/Main.java'],
}


class InfrastructureError(RuntimeError):
    pass


class Engine:
    def __init__(self, image, namespace):
        # Deliberately ignore DOCKER_HOST: only the private Unix socket is allowed.
        self.client = docker.DockerClient(base_url='unix:///var/run/docker.sock', version='auto', timeout=10)
        self.namespace = namespace
        info = self.client.info()
        if info['OSType'] != 'linux' or 'name=seccomp,profile=builtin' not in info.get('SecurityOptions', []):
            raise RuntimeError('Linux Engine with default seccomp is required')
        if not all(info.get(key) for key in ('MemoryLimit', 'SwapLimit', 'CpuCfsQuota', 'PidsLimit')):
            raise RuntimeError('Engine must enforce memory, swap, CPU quota and PID cgroups; refusing weak isolation')
        self.image = self.client.images.get(image).id  # Pin the image ID until controller restart.
        self.sweep()

    def sweep(self):
        for container in self.client.containers.list(all=True, filters={'label': f'{LABEL}={self.namespace}'}):
            container.remove(force=True)

    def create(self, job_id, kind, owner):
        compile_job = kind == 'compile'
        memory = (512 if compile_job else 256) * 1024 * 1024
        work = 128 if compile_job else 32
        return self.client.containers.create(
            self.image, ['python', '-c', 'import time; time.sleep(86400)'],
            name=f'neon-{self.namespace}-{job_id}', user='10001:10001', working_dir='/work',
            environment={'HOME': '/tmp', 'TMPDIR': '/tmp', 'PYTHONIOENCODING': 'utf-8',
                         'PYTHONDONTWRITEBYTECODE': '1'},
            network_mode='none', read_only=True, cap_drop=['ALL'],
            ipc_mode='private', shm_size=1024 * 1024,
            security_opt=['no-new-privileges:true'], init=True,
            mem_limit=memory, memswap_limit=memory, nano_cpus=1_000_000_000,
            pids_limit=128 if compile_job else 64,
            tmpfs={'/work': f'rw,exec,nosuid,nodev,size={work}m,uid=10001,gid=10001,mode=700',
                   '/tmp': 'rw,noexec,nosuid,nodev,size=16m,uid=10001,gid=10001,mode=700'},
            ulimits=[Ulimit(name='nofile', soft=128, hard=128),
                     Ulimit(name='fsize', soft=MAX_ARTIFACT, hard=MAX_ARTIFACT),
                     Ulimit(name='core', soft=0, hard=0)],
            log_config=LogConfig(type='none'),
            labels={LABEL: self.namespace, 'io.neonarena.job': job_id,
                    'io.neonarena.kind': kind, 'io.neonarena.owner': owner},
            detach=True)

    def provision(self, container, files, target):
        container.start()
        # Fixed server-owned directories. No shell and no user-controlled command.
        result = container.exec_run(['mkdir', '-p', '/work/src', '/work/out', '/work/app'])
        if result.exit_code:
            raise InfrastructureError('Cannot initialize sandbox workspace')
        self.transfer(container, 'upload', target, files)

    def transfer(self, container, operation, target, files=None):
        execution = self.client.api.exec_create(container.id,
            ['python', '-B', '/opt/arena-transfer.py', operation, target],
            stdin=files is not None, stdout=True, stderr=True, tty=False)
        connection = self.client.api.exec_start(execution['Id'], socket=True, tty=False)
        stream = connection._sock
        stream.settimeout(10)
        output, errors = bytearray(), bytearray()

        def exact(count):
            data = bytearray()
            while len(data) < count:
                chunk = stream.recv(count - len(data))
                if not chunk:
                    raise EOFError()
                data.extend(chunk)
            return data

        try:
            if files is not None:
                stream.sendall((json.dumps({name: base64.b64encode(data).decode()
                                           for name, data in files.items()}) + '\n').encode())
            while True:
                try:
                    header = exact(8)
                except EOFError:
                    break
                size = struct.unpack('>I', header[4:])[0]
                buffer = errors if header[0] == 2 else output
                cap = 32768 if header[0] == 2 else MAX_ARTIFACT + 512 * 1024
                if len(buffer) + size > cap:
                    raise BotError('Artifact transfer exceeds limit')
                buffer.extend(exact(size))
        finally:
            connection.close()
        status = self.client.api.exec_inspect(execution['Id'])
        if status['ExitCode'] != 0:
            raise BotError('Artifact transfer rejected: ' + errors.decode('utf-8', errors='replace')[:2048])
        return bytes(output)

    def compile(self, container, language, source, cancelled):
        filename = {'py': 'bot.py', 'cpp': 'bot.cpp', 'java': 'Main.java'}[language]
        self.provision(container, {filename: source}, '/work/src')
        execution = self.client.api.exec_create(container.id, COMPILE[language], stdout=True, stderr=True)
        output, failure = bytearray(), []

        def read():
            try:
                for chunk in self.client.api.exec_start(execution['Id'], stream=True):
                    room = 32 * 1024 - len(output)
                    output.extend(chunk[:max(0, room)])
                    if len(chunk) > room:
                        failure.append('Compiler output exceeds 32 KiB')
                        return
            except Exception as exc:
                failure.append(exc)

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        deadline = time.monotonic() + COMPILE_TIMEOUT
        while reader.is_alive() and not failure and not cancelled.is_set() and time.monotonic() < deadline:
            reader.join(.05)
        if reader.is_alive() or failure or cancelled.is_set():
            if failure and isinstance(failure[0], Exception):
                raise InfrastructureError('Docker compile stream failed') from failure[0]
            return False, str(failure[0]) if failure else 'Compile timeout/cancelled (30 seconds)', None
        status = self.client.api.exec_inspect(execution['Id'])
        logs = output.decode('utf-8', errors='replace')
        if status['ExitCode'] != 0:
            return False, logs or f"Compiler exited {status['ExitCode']}", None
        if language == 'py':
            # Syntax checking never executes uploaded Python; artifact remains source.
            self.transfer(container, 'upload', '/work/out', {'bot.py': source})
        try:
            blob = self.transfer(container, 'export', '/work/out')
        except BotError as exc:
            return False, str(exc), None
        return True, logs, blob


class Pipe:
    """One long-lived exec, Docker's multiplexed frames, bounded JSON lines."""
    def __init__(self, engine, container, language):
        self.container, self.engine = container, engine
        execution = engine.client.api.exec_create(container.id, COMMANDS[language],
            stdin=True, stdout=True, stderr=True, tty=False, workdir='/work/app')
        self.exec_id = execution['Id']
        self.connection = engine.client.api.exec_start(self.exec_id, socket=True, tty=False)
        self.socket = self.connection._sock
        self.socket.settimeout(None)
        self.outputs, self.inputs = queue.Queue(maxsize=8), queue.Queue(maxsize=1)
        self.error, self.closed, self.requests = None, False, 0
        self.threads = [threading.Thread(target=f, daemon=True) for f in (self._read, self._write)]
        for thread in self.threads:
            thread.start()

    def fail(self, error):
        if self.error is None:
            self.error = error
        try:
            self.outputs.put_nowait(None)
        except queue.Full:
            pass

    def exact(self, count):
        data = bytearray()
        while len(data) < count:
            chunk = self.socket.recv(count - len(data))
            if not chunk:
                raise EOFError()
            data.extend(chunk)
        return bytes(data)

    def _read(self):
        total, errors, pending = 0, 0, bytearray()
        try:
            while not self.closed:
                header = self.exact(8)
                channel, size = header[0], struct.unpack('>I', header[4:])[0]
                # Bound even a frame before allocating its complete payload.
                if size > MAX_STDOUT_BYTES:
                    raise BotError('Output exceeds limit')
                data = self.exact(size)
                if channel == 2:
                    errors += len(data)
                    if errors > MAX_STDERR_BYTES:
                        raise BotError('stderr exceeds 64 KiB/match')
                elif channel == 1:
                    total += len(data)
                    pending.extend(data)
                    if total > MAX_STDOUT_BYTES:
                        raise BotError('stdout exceeds 256 KiB/match')
                    while b'\n' in pending:
                        line, _, rest = pending.partition(b'\n')
                        pending = bytearray(rest)
                        if len(line) + 1 > MAX_LINE_BYTES:
                            raise BotError('Output exceeds 4 KiB/line')
                        try:
                            self.outputs.put_nowait(line)
                        except queue.Full:
                            raise BotError('Too many actions; one JSON line per observation')
                    if len(pending) > MAX_LINE_BYTES:
                        raise BotError('Output exceeds 4 KiB/line')
        except BotError as exc:
            self.fail(exc)
        except (EOFError, OSError) as exc:
            if not self.closed:
                # EOF can mean bot exit OR lost Engine stream. Inspect before attributing fault.
                try:
                    state = self.engine.client.api.exec_inspect(self.exec_id)
                    self.container.reload()
                    if self.container.attrs['State'].get('OOMKilled'):
                        self.fail(BotError('Bot exceeded container RAM limit'))
                        return
                    if not self.container.attrs['State']['Running'] or state['Running']:
                        raise InfrastructureError('Container/Engine stream stopped unexpectedly')
                    self.fail(BotError('Bot crash/EOF (possibly memory/PID limit)'))
                except Exception as inspect_error:
                    self.fail(InfrastructureError('Cannot verify bot process after stream loss'))
        except Exception as exc:
            self.fail(InfrastructureError('Invalid/lost Docker stream'))

    def _write(self):
        try:
            while not self.closed:
                payload = self.inputs.get()
                if payload is None:
                    return
                self.socket.sendall(payload)
        except OSError:
            self.fail(InfrastructureError('Docker stdin stream failed'))

    def request(self, observation):
        if self.error:
            raise self.error
        limit = STARTUP_TIMEOUT if self.requests == 0 else TURN_TIMEOUT
        self.requests += 1
        deadline = time.monotonic() + limit
        try:
            self.inputs.put((json.dumps(observation, separators=(',', ':')) + '\n').encode(), timeout=limit)
            line = self.outputs.get(timeout=max(0, deadline - time.monotonic()))
        except (queue.Empty, queue.Full):
            # A daemon outage must not be treated as a bot timeout.
            try:
                self.engine.client.ping()
                self.container.reload()
            except Exception as exc:
                raise InfrastructureError('Docker unavailable during bot request') from exc
            if not self.container.attrs['State']['Running']:
                if self.container.attrs['State'].get('OOMKilled'):
                    raise BotError('Bot exceeded container RAM limit')
                raise InfrastructureError('Runtime container unexpectedly stopped')
            raise BotError(f'Bot timeout after {limit:g} seconds')
        if self.error or line is None:
            raise self.error or BotError('Bot stopped')
        try:
            return json.loads(line.decode('utf-8'), parse_constant=reject_constant)
        except (ValueError, UnicodeDecodeError, RecursionError) as exc:
            raise BotError('Bot returned invalid JSON Lines') from exc

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.socket.shutdown(2)
        except OSError:
            pass
        self.connection.close()
        try:
            self.inputs.put_nowait(None)
        except queue.Full:
            pass
        for thread in self.threads:
            thread.join(timeout=.2)
