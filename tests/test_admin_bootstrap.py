import hashlib
import io
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest
from argon2 import extract_parameters
from argon2.low_level import Type
from fastapi.testclient import TestClient

from backend import admin_cli
from backend.account_database import AccountDatabase
from backend.admin_cli import AccountExistsError, bootstrap_admin
from backend.passwords import hash_password, needs_rehash, verify_password
from backend.writer_lock import WriterAlreadyRunning, WriterLock
from backend.main import create_app
from scripts.volume_snapshot import ROLES, read_snapshot, write_snapshot


# Test-only secret; never supplied to a process command line or any real dataset.
PASSWORD = "a long test-only passphrase 42"
PROJECT = Path(__file__).resolve().parents[1]


def test_password_hashing_uses_argon2id_random_salts():
    first, second = hash_password(PASSWORD), hash_password(PASSWORD)
    assert first.startswith("$argon2id$") and first != second
    assert PASSWORD not in first
    params = extract_parameters(first)
    assert params.type == Type.ID
    assert (params.memory_cost, params.time_cost, params.parallelism) == (65536, 3, 4)
    assert verify_password(first, PASSWORD)
    assert not verify_password(first, PASSWORD + "incorrect")
    assert not needs_rehash(first)


@pytest.mark.parametrize("password", ["", "short", "x" * 1025, "😀" * 257, "\ud800" * 15])
def test_bad_new_password_rejected(password):
    with pytest.raises(ValueError):
        hash_password(password)


@pytest.mark.parametrize("encoded,password", [
    ("plain-text", PASSWORD), ("$argon2id$malformed", PASSWORD), (None, PASSWORD),
    ("$argon2i$malformed", PASSWORD), ("$argon2id$malformed", "\ud800"),
])
def test_invalid_password_hash_returns_false(encoded, password):
    assert not verify_password(encoded, password)


def test_bootstrap_persisted_admin_and_audit_are_atomic(tmp_path):
    user_id = bootstrap_admin(tmp_path, "  Main.Admin  ", PASSWORD, "Local Admin")
    with AccountDatabase(tmp_path).read() as connection:
        row = connection.execute("SELECT * FROM users").fetchone()
        assert (row["id"], row["username"], row["display_name"], row["system_role"], row["status"]) == (
            user_id, "main.admin", "Local Admin", "ADMIN", "ACTIVE")
        assert verify_password(row["password_hash"], PASSWORD)
        assert row["password_changed_at"] == row["created_at"]
        event = connection.execute("SELECT * FROM audit_events").fetchone()
        assert event["action"] == "OFFLINE_ADMIN_CREATED"
        assert event["actor_user_id"] == event["target_id"] == user_id
        assert event["details_json"] == "{}"
        assert connection.execute("SELECT count(*) FROM auth_sessions").fetchone()[0] == 0
    assert PASSWORD.encode() not in (tmp_path / "arena.sqlite3").read_bytes()


def test_bootstrap_duplicate_does_not_reset_or_promote_existing_user(tmp_path):
    bootstrap_admin(tmp_path, "main.admin", PASSWORD)
    with pytest.raises(AccountExistsError):
        bootstrap_admin(tmp_path, "MAIN.ADMIN", PASSWORD + "different")
    with AccountDatabase(tmp_path).maintenance() as connection:
        connection.execute("""INSERT INTO users (
            id, username, display_name, system_role, status, created_at, updated_at)
            VALUES ('player', 'player', 'Player', 'PLAYER', 'INVITED', 100, 100)""")
    with pytest.raises(AccountExistsError):
        bootstrap_admin(tmp_path, "player", PASSWORD)
    with AccountDatabase(tmp_path).read() as connection:
        assert connection.execute("SELECT count(*) FROM users WHERE system_role='ADMIN'").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM audit_events").fetchone()[0] == 1
        assert connection.execute("SELECT status FROM users WHERE id='player'").fetchone()[0] == "INVITED"
        assert verify_password(connection.execute("SELECT password_hash FROM users WHERE username='main.admin'").fetchone()[0], PASSWORD)


def test_bad_password_leaves_no_admin_or_event(tmp_path):
    with pytest.raises(ValueError):
        bootstrap_admin(tmp_path, "main.admin", "short")
    with AccountDatabase(tmp_path).read() as connection:
        assert connection.execute("SELECT count(*) FROM users").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM audit_events").fetchone()[0] == 0


def test_audit_failure_rolls_back_admin(tmp_path):
    db = AccountDatabase(tmp_path)
    with db.maintenance() as connection:
        connection.execute("""CREATE TEMP TRIGGER reject_audit BEFORE INSERT ON audit_events
            BEGIN SELECT RAISE(ABORT, 'test failure'); END""")
        with pytest.raises(sqlite3.IntegrityError):
            admin_cli._insert_admin(connection, "main.admin", PASSWORD, "Admin")
    with db.read() as connection:
        assert connection.execute("SELECT count(*) FROM users").fetchone()[0] == 0


def test_cli_hidden_prompt_and_no_password_in_output(tmp_path, monkeypatch, capsys):
    prompts = []
    monkeypatch.setattr(admin_cli.sys.stdin, "isatty", lambda: True)
    def hidden_prompt(prompt):
        prompts.append(prompt)
        return PASSWORD
    monkeypatch.setattr(admin_cli.getpass, "getpass", hidden_prompt)
    assert admin_cli.main(["--data-dir", str(tmp_path), "create-admin", "--username", "admin"]) == 0
    output = capsys.readouterr()
    assert len(prompts) == 2
    assert PASSWORD not in output.out + output.err
    assert "$argon2" not in output.out + output.err
    assert "Account HTTP remains opt-in" in output.out


def test_cli_confirmation_failure_does_not_create_admin(tmp_path, monkeypatch):
    monkeypatch.setattr(admin_cli.sys.stdin, "isatty", lambda: True)
    answers = iter([PASSWORD, "mismatch"])
    monkeypatch.setattr(admin_cli.getpass, "getpass", lambda _: next(answers))
    assert admin_cli.main(["--data-dir", str(tmp_path), "create-admin", "--username", "admin"]) == 1
    with AccountDatabase(tmp_path).read() as connection:
        assert connection.execute("SELECT count(*) FROM users").fetchone()[0] == 0


def test_cli_refuses_echo_fallback(tmp_path, monkeypatch, capsys):
    import warnings
    monkeypatch.setattr(admin_cli.sys.stdin, "isatty", lambda: True)
    def unsafe_prompt(_):
        warnings.warn("Echo unavailable", admin_cli.getpass.GetPassWarning)
        pytest.fail("Must stop before reading a potentially echoed password")
    monkeypatch.setattr(admin_cli.getpass, "getpass", unsafe_prompt)
    assert admin_cli.main(["--data-dir", str(tmp_path), "create-admin", "--username", "admin"]) == 1
    assert "refused" in capsys.readouterr().err


def test_cli_refuses_password_argument_and_redirected_input(tmp_path):
    # The parser rejects the flag without ever passing a secret via argv.
    with pytest.raises(SystemExit) as exc:
        admin_cli.main(["--data-dir", str(tmp_path), "create-admin", "--username", "admin", "--password"])
    assert exc.value.code == 2
    result = subprocess.run([sys.executable, "-B", "-m", "backend.admin_cli", "--data-dir", str(tmp_path),
                             "create-admin", "--username", "admin"], cwd=PROJECT,
                            input="", capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert "interactive terminal" in result.stderr
    assert not (tmp_path / "arena.sqlite3").exists()


@pytest.mark.parametrize("existing", [False, True])
def test_cross_process_writer_prevents_bootstrap_before_database_open(tmp_path, existing):
    if existing:
        AccountDatabase(tmp_path).migrate()
    before = (tmp_path / "arena.sqlite3").read_bytes() if existing else None
    program = """
import sys
from pathlib import Path
from backend.admin_cli import bootstrap_admin
from backend.writer_lock import WriterAlreadyRunning
try:
    bootstrap_admin(Path(sys.argv[1]), 'blocked.admin', 'test-only long passphrase')
except WriterAlreadyRunning:
    sys.exit(23)
sys.exit(99)
"""
    with WriterLock(tmp_path):
        result = subprocess.run([sys.executable, "-B", "-c", program, str(tmp_path)], cwd=PROJECT,
                                capture_output=True, text=True, timeout=10)
    assert result.returncode == 23, result.stderr
    if existing:
        assert (tmp_path / "arena.sqlite3").read_bytes() == before
    else:
        assert not (tmp_path / "arena.sqlite3").exists()
    # OS lock is released; the next writer can proceed without deleting lockfile.
    bootstrap_admin(tmp_path, "allowed.admin", PASSWORD)


def test_cli_lock_prevents_prompt_and_migration(tmp_path, monkeypatch):
    monkeypatch.setattr(admin_cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(admin_cli.getpass, "getpass", lambda _: pytest.fail("Lock must be obtained before prompting"))
    with WriterLock(tmp_path):
        assert admin_cli.main(["--data-dir", str(tmp_path), "create-admin", "--username", "admin"]) == 1
    assert not (tmp_path / "arena.sqlite3").exists()


def test_sqlite_bootstrap_preserves_legacy_files_and_ignores_legacy_identity(tmp_path):
    files = {"sessions.json": b'{"legacy-session":"keep"}', "bots.json": b'{"bot":"keep"}',
             "invitations.json": b'[{"old":"invitation"}]', "games.json": b'{"rules":"keep"}',
             "matches/old.json": b'{"game_id":"robot_battle","rules_snapshot":{"max_turns":10}}',
             "replays/old.jsonl": b'{"turn":0}\n{"turn":1}\n'}
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    before = {name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() for name in files}
    bootstrap_admin(tmp_path, "admin", PASSWORD)
    assert before == {name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() for name in files}
    with AccountDatabase(tmp_path).read() as connection:
        assert connection.execute("SELECT count(*) FROM submission_ownership").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM team_memberships").fetchone()[0] == 0


def test_cli_migrate_check_and_reopen_in_separate_processes(tmp_path):
    for command in ["migrate", "migrate", "check"]:
        result = subprocess.run([sys.executable, "-B", "-m", "backend.admin_cli", "--data-dir", str(tmp_path), command],
                                cwd=PROJECT, capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr


def test_running_backend_and_account_maintenance_respect_same_writer_lock(tmp_path):
    data = tmp_path / "data"
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/api/health").status_code == 200
        assert not (data / "arena.sqlite3").exists()  # no implicit startup migration
    bootstrap_admin(data, "admin", PASSWORD)
    db_before = (data / "arena.sqlite3").read_bytes()
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/api/health").status_code == 200
        with pytest.raises(WriterAlreadyRunning):
            bootstrap_admin(data, "another.admin", PASSWORD)
        assert (data / "arena.sqlite3").read_bytes() == db_before
    # Opposite direction: holding maintenance must prevent Store startup.
    with AccountDatabase(data).maintenance():
        with pytest.raises(WriterAlreadyRunning):
            with TestClient(create_app(tmp_path)):
                pytest.fail("Backend cannot start while maintenance owns the data lock")
    with AccountDatabase(data).read() as connection:
        assert connection.execute("SELECT count(*) FROM users").fetchone()[0] == 1


def test_cold_snapshot_restore_keeps_sqlite_and_legacy_replay(tmp_path):
    source = {role: tmp_path / "source" / role for role in ROLES}
    restored = {role: tmp_path / "restored" / role for role in ROLES}
    for folder in [*source.values(), *restored.values()]:
        folder.mkdir(parents=True)
    bootstrap_admin(source["data"], "admin", PASSWORD)
    (source["data"] / "replays").mkdir()
    (source["data"] / "replays" / "old.jsonl").write_bytes(b'{"turn":0}\n{"turn":1}\n')
    archive = io.BytesIO()
    # Same cold-snapshot helper as existing backup; no Docker Engine/volumes used.
    with WriterLock(source["data"]):
        write_snapshot(source, archive, {"qa": "account-foundation"})
    archive.seek(0)
    manifest = read_snapshot(archive, restored)
    assert "data/arena.sqlite3" in manifest["files"]
    assert (restored["data"] / "arena.sqlite3").read_bytes() == (source["data"] / "arena.sqlite3").read_bytes()
    assert (restored["data"] / "replays" / "old.jsonl").read_bytes() == b'{"turn":0}\n{"turn":1}\n'
    with AccountDatabase(restored["data"]).read() as connection:
        assert verify_password(connection.execute("SELECT password_hash FROM users WHERE username='admin'").fetchone()[0], PASSWORD)
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
