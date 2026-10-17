"""Cold snapshot format; regular files only, never tar.extractall()."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile

ROLES = ('data', 'uploads', 'artifacts')
IMAGE_ID = re.compile(r'^sha256:[a-f0-9]{64}$')


def digest_file(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def write_snapshot(roots, output, metadata):
    files, artifact_images = {}, set()
    with tarfile.open(fileobj=output, mode='w|gz', dereference=False) as archive:
        for role in ROLES:
            root = Path(roots[role])
            if root.is_symlink() or not root.is_dir():
                raise ValueError('All three real snapshot roots are required')
            for path in [root, *sorted(root.rglob('*'))]:
                name = role if path == root else role + '/' + path.relative_to(root).as_posix()
                if name == 'data/.writer.lock':
                    continue  # Coordination inode is not application data.
                if path.is_symlink() or not (path.is_dir() or path.is_file()):
                    raise ValueError(f'Unsupported snapshot entry: {name}')
                if path.is_file() and path.stat().st_nlink != 1:
                    raise ValueError(f'Hard-linked snapshot entry: {name}')
                entry = archive.gettarinfo(str(path), arcname=name)
                if path.is_file():
                    files[name] = {'size': entry.size, 'sha256': digest_file(path)}
                    if role == 'artifacts' and path.parent == root and path.suffix == '.json':
                        record = json.loads(path.read_bytes())
                        image = record.get('image', '')
                        if not IMAGE_ID.fullmatch(image):
                            raise ValueError('Artifact metadata lacks a valid pinned image ID')
                        artifact_images.add(image)
                    with path.open('rb') as source:
                        archive.addfile(entry, source)
                else:
                    archive.addfile(entry)
        manifest = {**metadata, 'format': 2, 'files': files, 'artifact_images': sorted(artifact_images)}
        raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode()
        entry = tarfile.TarInfo('manifest.json')
        entry.size = len(raw)
        import io
        archive.addfile(entry, io.BytesIO(raw))


def read_snapshot(source, roots=None):
    """Verify every file; optionally restore into three EMPTY directories."""
    if roots is not None:
        for role in ROLES:
            root = Path(roots[role])
            if root.is_symlink() or not root.is_dir() or any(root.iterdir()):
                raise ValueError('Restore requires three empty destination directories')
    files, seen, manifest = {}, set(), None
    with tarfile.open(fileobj=source, mode='r|gz') as archive:
        for entry in archive:
            if manifest is not None:
                raise ValueError('Unexpected entry after manifest')
            name = entry.name.rstrip('/')
            parts = PurePosixPath(name).parts
            if (not parts or name != PurePosixPath(name).as_posix() or '\\' in name or ':' in name
                    or name.startswith('/') or '..' in parts or name in seen
                    or not (entry.isfile() or entry.isdir())):
                raise ValueError('Unsafe or duplicate snapshot path/type')
            seen.add(name)
            if name == 'manifest.json':
                if not entry.isfile() or entry.size > 16 * 1024 * 1024:
                    raise ValueError('Invalid snapshot manifest')
                manifest = json.loads(archive.extractfile(entry).read())
                continue
            if parts[0] not in ROLES or name == 'data/.writer.lock':
                raise ValueError('Unexpected snapshot root')
            destination = None
            if roots is not None:
                destination = Path(roots[parts[0]]).joinpath(*parts[1:])
                if any(p.is_symlink() for p in [destination, *destination.parents]):
                    raise ValueError('Symlink in restore destination')
            if entry.isdir():
                if destination is not None:
                    destination.mkdir(parents=True, exist_ok=True)
                continue
            if len(parts) < 2:
                raise ValueError('Snapshot root must be a directory')
            target = None
            try:
                if destination is not None:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                                 | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0), 0o600)
                    target = os.fdopen(fd, 'wb')
                digest, count = hashlib.sha256(), 0
                with archive.extractfile(entry) as content:
                    while block := content.read(1024 * 1024):
                        count += len(block)
                        digest.update(block)
                        if target:
                            target.write(block)
                files[name] = {'size': count, 'sha256': digest.hexdigest()}
                if count != entry.size:
                    raise ValueError('Truncated snapshot file')
            finally:
                if target:
                    target.close()
            if destination is not None:
                destination.chmod(entry.mode & 0o777)
    if not manifest or manifest.get('format') != 2 or manifest.get('files') != files:
        raise ValueError('Snapshot checksum/manifest mismatch')
    if not all(role in seen for role in ROLES):
        raise ValueError('Snapshot must include all three roots')
    if not all(IMAGE_ID.fullmatch(image) for image in manifest.get('artifact_images', [])):
        raise ValueError('Invalid artifact image inventory')
    return manifest


if __name__ == '__main__':
    roots = {role: Path('/snapshot') / role for role in ROLES}
    if sys.argv[1] == 'restore':
        read_snapshot(sys.stdin.buffer, roots)
        # Root + CAP_CHOWN only in this helper, on NEW volumes; no host mounts.
        for root in roots.values():
            for path in [root, *root.rglob('*')]:
                os.chown(path, 10001, 10001)
    else:
        import fcntl
        # Hold the backend's inode across the entire three-volume copy. data is
        # RW only for this coordination file; uploads/artifacts are read-only.
        with (roots['data'] / '.writer.lock').open('a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            write_snapshot(roots, sys.stdout.buffer, json.loads(sys.argv[1]))
