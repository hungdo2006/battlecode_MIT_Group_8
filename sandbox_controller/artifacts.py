"""Treat compiler-produced archives as hostile; never call extractall()."""
import hashlib
import base64
import io
import json
import os
import re
import tarfile
from uuid import uuid4
from pathlib import Path, PurePosixPath

MAX_ARTIFACT = 16 * 1024 * 1024
MAX_FILES = 256
IDENTIFIER = re.compile(r'^[a-zA-Z0-9_-]{1,80}$')


def identifier(value):
    if not IDENTIFIER.fullmatch(value):
        raise ValueError('Invalid server-generated identifier')
    return value


def unpack(blob, language):
    if len(blob) > MAX_ARTIFACT + 512 * 1024:
        raise ValueError('Artifact archive exceeds limit')
    result, size = {}, 0
    with tarfile.open(fileobj=io.BytesIO(blob), mode='r:') as archive:
        count = 0
        for entry in archive:
            count += 1
            if count > MAX_FILES + 4:
                raise ValueError('Too many artifact entries')
            path = PurePosixPath(entry.name)
            if path.is_absolute() or '..' in path.parts or '\\' in entry.name:
                raise ValueError('Unsafe artifact path')
            # Docker get_archive('/work/out') wraps entries in out/.
            if path.parts == ('out',) and entry.isdir():
                continue
            if len(path.parts) != 2 or path.parts[0] != 'out' or not entry.isfile():
                raise ValueError('Only regular artifact files are accepted')
            name = path.parts[1]
            valid = (name == 'bot.py' if language == 'py' else name == 'bot' if language == 'cpp'
                     else bool(re.fullmatch(r'[A-Za-z_$][A-Za-z0-9_$]*\.class', name)))
            if not valid or name in result or entry.size < 0:
                raise ValueError('Unexpected or duplicate artifact')
            size += entry.size
            if size > MAX_ARTIFACT or len(result) >= MAX_FILES:
                raise ValueError('Artifacts exceed size/file limit')
            result[name] = archive.extractfile(entry).read(entry.size + 1)
            if len(result[name]) != entry.size:
                raise ValueError('Truncated artifact')
            if language == 'cpp' and not result[name].startswith(b'\x7fELF'):
                raise ValueError('C++ artifact must be an ELF executable')
            if language == 'java' and not result[name].startswith(b'\xca\xfe\xba\xbe'):
                raise ValueError('Java artifact must be a JVM class file')
    required = {'py': 'bot.py', 'cpp': 'bot', 'java': 'Main.class'}[language]
    if required not in result:
        raise ValueError('Compiler did not produce the required artifact')
    return result


def pack(files, prefix=''):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w') as archive:
        for name, data in sorted(files.items()):
            entry = tarfile.TarInfo(prefix + name)
            entry.size, entry.uid, entry.gid, entry.mode = len(data), 10001, 10001, 0o700
            archive.addfile(entry, io.BytesIO(data))
    return output.getvalue()


class ArtifactStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        identity = self.root / '.store-id'
        try:
            with identity.open('x', encoding='ascii') as target:
                target.write(uuid4().hex)
                target.flush()
                os.fsync(target.fileno())
        except FileExistsError:
            pass
        self.identity = identity.read_text(encoding='ascii')
        if not re.fullmatch(r'[a-f0-9]{32}', self.identity):
            raise ValueError('Invalid artifact store identity; operator recovery required')

    def save(self, job_id, language, files, image):
        blob = pack(files, 'out/')
        digest = hashlib.sha256(blob).hexdigest()
        artifact_id = identifier(job_id)
        # No garbage collection of existing submissions. Refuse new writes at quota.
        used = sum(p.stat().st_size for p in self.root.glob('*') if p.is_file())
        if used + len(blob) > 512 * 1024 * 1024:
            raise ValueError('Artifact store quota reached (512 MiB); operator action required')
        metadata = dict(artifact_id=artifact_id, artifact_digest=digest, language=language, image=image,
                        artifact_store_id=self.identity)
        for suffix, content in [('tar', blob), ('json', json.dumps(metadata).encode())]:
            temporary = self.root / f'{artifact_id}.{suffix}.tmp'
            temporary.write_bytes(content)
            os.replace(temporary, self.root / f'{artifact_id}.{suffix}')
        return metadata

    def load(self, artifact_id, digest, image):
        artifact_id = identifier(artifact_id)
        metadata = json.loads((self.root / f'{artifact_id}.json').read_bytes())
        blob = (self.root / f'{artifact_id}.tar').read_bytes()
        if (metadata['image'] != image or metadata['artifact_digest'] != digest
                or hashlib.sha256(blob).hexdigest() != digest):
            raise ValueError('Artifact/toolchain mismatch; resubmit source with current sandbox image')
        return metadata['language'], unpack(blob, metadata['language'])

    def save_battlecode(self, job_id, language, source, image):
        artifact_id = identifier(job_id)
        payload = json.dumps({'language': language, 'source': base64.b64encode(source).decode(),
                              'image': image}, sort_keys=True).encode()
        used = sum(p.stat().st_size for p in self.root.glob('*') if p.is_file())
        if used + len(payload) > 512 * 1024 * 1024:
            raise ValueError('Artifact store quota reached')
        temporary = self.root / f'{artifact_id}.bc.tmp'
        temporary.write_bytes(payload)
        os.replace(temporary, self.root / f'{artifact_id}.bc.json')
        return {'artifact_id': artifact_id, 'artifact_digest': hashlib.sha256(payload).hexdigest(),
                'image': image, 'artifact_store_id': self.identity}

    def load_battlecode(self, artifact_id, digest, image):
        artifact_id = identifier(artifact_id)
        path = self.root / f'{artifact_id}.bc.json'
        if path.stat().st_size > 360000:
            raise ValueError('Battlecode artifact exceeds limit')
        raw = path.read_bytes()
        if not isinstance(digest, str) or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('Battlecode artifact digest mismatch')
        payload = json.loads(raw)
        if payload.get('image') != image or payload.get('language') not in ('py', 'java'):
            raise ValueError('Battlecode artifact/image mismatch')
        source = base64.b64decode(payload['source'], validate=True)
        if not 0 < len(source) <= 256 * 1024:
            raise ValueError('Battlecode source exceeds limit')
        return {'language': payload['language'], 'source': payload['source']}
