"""stdlib-only OS checks, also executable on Linux without app dependencies.

python3 -m unittest discover -s tests -p test_writer_lock_os.py -v
"""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from backend.writer_lock import WriterLock

ROOT = Path(__file__).resolve().parents[1]


class WriterLockOSTest(unittest.TestCase):
    def test_child_cannot_take_parent_lock_then_can_after_release(self):
        code = """
from pathlib import Path
import sys
from backend.writer_lock import WriterLock, WriterAlreadyRunning
try:
    with WriterLock(Path(sys.argv[1])):
        pass
except WriterAlreadyRunning:
    sys.exit(23)
"""
        with tempfile.TemporaryDirectory(prefix='arena-os-lock-') as folder:
            args = [sys.executable, '-B', '-c', code, folder]
            with WriterLock(Path(folder)):
                result = subprocess.run(args, cwd=ROOT, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 23, result.stderr)
            result = subprocess.run(args, cwd=ROOT, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_child_crash_releases_lock_without_deleting_inode(self):
        code = """
import os,sys
from pathlib import Path
from backend.writer_lock import WriterLock
lock = WriterLock(Path(sys.argv[1]))
lock.__enter__()
os._exit(0)
"""
        with tempfile.TemporaryDirectory(prefix='arena-os-lock-') as folder:
            result = subprocess.run([sys.executable, '-B', '-c', code, folder], cwd=ROOT,
                                    capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            path = Path(folder) / '.writer.lock'
            self.assertTrue(path.exists())
            with WriterLock(Path(folder)):
                pass
            self.assertTrue(path.exists())


if __name__ == '__main__':
    unittest.main()
