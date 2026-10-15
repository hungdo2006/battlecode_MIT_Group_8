"""Trusted helper copied ONLY into the bot image; no credentials or Docker API.

Transfer via exec pipes because Docker archive endpoints do not reliably expose
tmpfs contents on all Engines. Never extracts caller-supplied paths.
"""
import base64
import io
import json
import os
import re
import stat
import sys
import tarfile

LIMIT = 16 * 1024 * 1024


def valid(name):
    return bool(re.fullmatch(r'(bot(?:\.py|\.cpp)?|Main\.java|[A-Za-z_$][A-Za-z0-9_$]*\.class)', name))


def main():
    operation, target = sys.argv[1:]
    if target not in ('/work/src', '/work/out', '/work/app'):
        raise ValueError('Invalid workspace')
    if operation == 'upload':
        files = json.loads(sys.stdin.buffer.readline(24 * 1024 * 1024))
        if not isinstance(files, dict) or len(files) > 256:
            raise ValueError('Invalid file list')
        os.makedirs(target, mode=0o700, exist_ok=True)
        total = 0
        for name, encoded in files.items():
            if not valid(name):
                raise ValueError('Invalid artifact name')
            data = base64.b64decode(encoded, validate=True)
            total += len(data)
            if total > LIMIT:
                raise ValueError('Files exceed limit')
            descriptor = os.open(target + '/' + name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o700)
            with os.fdopen(descriptor, 'wb') as output:
                output.write(data)
    elif operation == 'export':
        output, total = io.BytesIO(), 0
        entries = list(os.scandir(target))
        if len(entries) > 256:
            raise ValueError('Too many artifacts')
        with tarfile.open(fileobj=output, mode='w') as archive:
            for entry in entries:
                if not valid(entry.name):
                    raise ValueError('Invalid artifact name')
                descriptor = os.open(entry.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(descriptor, 'rb') as source:
                    info = os.fstat(source.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                        raise ValueError('Artifact must be a regular file, never a link/device')
                    total += info.st_size
                    if total > LIMIT:
                        raise ValueError('Artifact exceeds limit')
                    item = tarfile.TarInfo('out/' + entry.name)
                    item.size, item.mode = info.st_size, 0o700
                    archive.addfile(item, source)
        sys.stdout.buffer.write(output.getvalue())
    else:
        raise ValueError('Unknown transfer operation')


if __name__ == '__main__':
    main()
