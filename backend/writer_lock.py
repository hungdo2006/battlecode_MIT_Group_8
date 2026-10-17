"""One backend writer per data volume, on Windows and Linux.

The lock file is permanent: unlinking it could let two processes lock different
inodes. OS locks are released on process exit, including an abrupt crash.
"""
import errno
import os
from pathlib import Path


class WriterAlreadyRunning(RuntimeError):
    pass


class WriterLock:
    def __init__(self, data_dir: Path):
        self.path = Path(data_dir).resolve() / ".writer.lock"
        self.fd = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0), 0o600)
        try:
            os.set_inheritable(fd, False)
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")  # msvcrt locks a real byte; never truncate.
            os.lseek(fd, 0, os.SEEK_SET)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise WriterAlreadyRunning(
                    f"Another NEON ARENA writer holds {self.path}. Use one backend/worker per data volume."
                ) from exc
            raise
        except BaseException:
            os.close(fd)
            raise
        self.fd = fd
        return self

    def __exit__(self, *exc):
        if self.fd is not None:
            # Closing the descriptor releases the lock without removing its path.
            os.close(self.fd)
            self.fd = None
