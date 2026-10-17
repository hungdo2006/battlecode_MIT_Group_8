"""All account foundation tests use isolated data directories, never ./data."""
import sqlite3

import pytest

from backend import account_database
from backend.account_database import AccountDatabase, SCHEMA_VERSION, SchemaError, check_integrity, transaction


@pytest.fixture
def database(tmp_path):
    result = AccountDatabase(tmp_path / "data")
    result.migrate()
    return result


def add_user(connection, user="alice", role="PLAYER"):
    connection.execute("""INSERT INTO users (
        id, username, display_name, system_role, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, 'INVITED', 100, 100)""", (user, user, user.title(), role))


def add_team(connection, team="red", creator="alice"):
    connection.execute("""INSERT INTO teams (
        id, slug, display_name, created_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, 100, 100)""", (team, team, team.title(), creator))


def test_inert_constructor_and_missing_read_do_not_create_database(tmp_path):
    db = AccountDatabase(tmp_path / "absent")
    assert not db.data_dir.exists()
    with pytest.raises(sqlite3.OperationalError):
        with db.read():
            pytest.fail("A missing database must not be initialized by a reader")
    assert not db.data_dir.exists()


def test_schema_migration_is_idempotent_and_persists(database):
    with database.maintenance() as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 2  # FULL
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        with transaction(connection):
            add_user(connection)
        ledger = tuple(connection.execute("SELECT * FROM schema_migrations").fetchone())
    database.migrate()
    reopened = AccountDatabase(database.data_dir)
    with reopened.read() as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert tuple(connection.execute("SELECT * FROM schema_migrations").fetchone()) == ledger
        assert connection.execute("SELECT username FROM users").fetchone()[0] == "alice"
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        assert tables == {"schema_migrations", "users", "auth_sessions", "account_tokens", "teams",
                          "team_memberships", "team_invitations", "submission_ownership", "team_game_bots",
                          "audit_events"}
        check_integrity(connection)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("DELETE FROM users")


@pytest.mark.parametrize("corruption", ["newer", "unversioned", "ledger", "identity", "missing_table", "drift"])
def test_incompatible_database_rejected_without_reset(database, corruption):
    with sqlite3.connect(database.path) as connection:
        if corruption == "newer":
            connection.execute("PRAGMA user_version = 999")
        elif corruption == "unversioned":
            connection.execute("PRAGMA user_version = 0")
        elif corruption == "ledger":
            connection.execute("UPDATE schema_migrations SET checksum = ?", ("0" * 64,))
        elif corruption == "identity":
            connection.execute("PRAGMA application_id = 1")
        elif corruption == "missing_table":
            connection.execute("DROP TABLE audit_events")
        else:
            connection.execute("ALTER TABLE users ADD COLUMN unexpected TEXT")
    before = database.path.read_bytes()
    with pytest.raises(SchemaError):
        database.migrate()
    assert database.path.read_bytes() == before
    with pytest.raises(SchemaError):
        with database.read():
            pass


def test_refuse_unrelated_unversioned_database(tmp_path):
    db = AccountDatabase(tmp_path)
    with sqlite3.connect(db.path) as connection:
        connection.execute("CREATE TABLE unrelated (secret TEXT)")
        connection.execute("INSERT INTO unrelated VALUES ('preserve')")
    before = db.path.read_bytes()
    with pytest.raises(SchemaError, match="foreign unversioned"):
        db.migrate()
    assert db.path.read_bytes() == before


def test_failed_future_migration_rolls_back_ddl_and_version(database, monkeypatch):
    next_version = SCHEMA_VERSION + 1
    migrations = account_database.MIGRATIONS + (
        (next_version, "failing_example", ("CREATE TABLE migration_probe (id INTEGER)", "INVALID SQL")),)
    monkeypatch.setattr(account_database, "MIGRATIONS", migrations)
    monkeypatch.setattr(account_database, "SCHEMA_VERSION", next_version)
    with pytest.raises(sqlite3.OperationalError):
        database.migrate()
    with sqlite3.connect(database.path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert connection.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == SCHEMA_VERSION
        assert not connection.execute("SELECT name FROM sqlite_schema WHERE name='migration_probe'").fetchall()


def test_append_only_future_migration_can_alter_existing_table(database, monkeypatch):
    next_version = SCHEMA_VERSION + 1
    migrations = account_database.MIGRATIONS + (
        (next_version, "example_upgrade", ("ALTER TABLE users ADD COLUMN example_note TEXT",)),)
    monkeypatch.setattr(account_database, "MIGRATIONS", migrations)
    monkeypatch.setattr(account_database, "SCHEMA_VERSION", next_version)
    database.migrate()
    database.migrate()
    with database.read() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == next_version
        assert connection.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == next_version
        assert "example_note" in {row[1] for row in connection.execute("PRAGMA table_info(users)")}
        check_integrity(connection)


def test_user_identity_and_role_constraints(database):
    with database.maintenance() as connection:
        add_user(connection)
        with pytest.raises(sqlite3.IntegrityError):
            add_user(connection)  # duplicate ID and canonical username
        for sql in [
            "UPDATE users SET username='ALICE'",
            "UPDATE users SET system_role='SUPERUSER'",
            "UPDATE users SET status='ACTIVE'",  # no hash
            "UPDATE users SET password_hash='plaintext'",
            "UPDATE users SET updated_at=1",
            "UPDATE users SET auth_version='not-an-integer'",
            "UPDATE users SET created_at='not-a-timestamp'",
            "UPDATE users SET auth_version=1.5",
        ]:
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(sql)


def test_memberships_unique_captain_and_admin_separation(database):
    with database.maintenance() as connection:
        for user, role in [("alice", "PLAYER"), ("bobby", "PLAYER"), ("admin", "ADMIN")]:
            add_user(connection, user, role)
        add_team(connection)
        connection.execute("INSERT INTO team_memberships VALUES ('m1', 'red', 'alice', 'CAPTAIN', 100, NULL)")
        for member in [
            ("m2", "red", "alice", "MEMBER", 100, None),
            ("m3", "red", "bobby", "CAPTAIN", 100, None),
            ("m4", "red", "admin", "MEMBER", 100, None),
            ("m5", "unknown", "bobby", "MEMBER", 100, None),
        ]:
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO team_memberships VALUES (?, ?, ?, ?, ?, ?)", member)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE users SET system_role='ADMIN' WHERE id='alice'")
        # Membership history remains; a departed user can join again with a new ID.
        with transaction(connection):
            connection.execute("UPDATE team_memberships SET left_at=101 WHERE id='m1'")
            connection.execute("INSERT INTO team_memberships VALUES ('m6', 'red', 'bobby', 'CAPTAIN', 101, NULL)")
        assert connection.execute("SELECT count(*) FROM team_memberships").fetchone()[0] == 2


def test_submission_binding_prevents_cross_team_and_cross_game_active_bot(database):
    with database.maintenance() as connection:
        add_user(connection)
        add_team(connection, "red")
        add_team(connection, "blue")
        connection.execute("INSERT INTO submission_ownership VALUES ('bot1', 'red', 'robot_battle', 'alice', 'NEW', 100)")
        for team, game, bot in [("blue", "robot_battle", "bot1"), ("red", "ott_v2", "bot1"),
                                ("red", "robot_battle", "missing")]:
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO team_game_bots VALUES (?, ?, ?, 'alice', 100, 1)", (team, game, bot))
        connection.execute("INSERT INTO team_game_bots VALUES ('red', 'robot_battle', 'bot1', 'alice', 100, 1)")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO team_game_bots VALUES ('red', 'robot_battle', 'bot1', 'alice', 100, 2)")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM submission_ownership WHERE bot_id='bot1'")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO submission_ownership VALUES ('bot2', 'red', 'ott_v2', NULL, 'NEW', 100)")
        # An explicitly verified legacy binding may have no attributable uploader.
        connection.execute("INSERT INTO submission_ownership VALUES ('old', 'red', 'ott_v2', NULL, 'LEGACY_VERIFIED', 100)")


def test_token_and_session_constraints(database):
    with database.maintenance() as connection:
        add_user(connection)
        valid = ("session1", "a" * 64, "alice", "PLAYER", 1, 100, 200, None, None, 60)
        connection.execute("INSERT INTO auth_sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", valid)
        for index, replacement in [(0, None), (1, "raw-token"), (2, "missing"), (3, "ROOT"), (6, 99)]:
            values = list(valid)
            values[0], values[1] = "session2", "b" * 64
            values[index] = replacement
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO auth_sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", values)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO auth_sessions VALUES ('duplicate', ?, 'alice', 'PLAYER', 1, 100, 200, NULL, NULL, 60)", ("a" * 64,))
        connection.execute("INSERT INTO account_tokens VALUES ('t1', ?, 'ACCOUNT_INVITE', NULL, 'alice', 100, 200, NULL, NULL)", ("c" * 64,))
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO account_tokens VALUES ('t2', ?, 'PASSWORD_RESET', NULL, 'alice', 100, 200, NULL, NULL)", ("d" * 64,))


def test_invitation_uniqueness_and_lifecycle(database):
    with database.maintenance() as connection:
        add_user(connection)
        add_user(connection, "bobby")
        add_team(connection)
        connection.execute("INSERT INTO team_invitations VALUES ('i1', 'red', 'bobby', 'alice', 'PENDING', 100, 200, NULL)")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO team_invitations VALUES ('i2', 'red', 'bobby', 'alice', 'PENDING', 100, 200, NULL)")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE team_invitations SET status='ACCEPTED' WHERE id='i1'")
        connection.execute("UPDATE team_invitations SET status='DECLINED', responded_at=101 WHERE id='i1'")
        connection.execute("INSERT INTO team_invitations VALUES ('i2', 'red', 'bobby', 'alice', 'PENDING', 102, 200, NULL)")


def test_integrity_check_detects_foreign_key_damage(database):
    # Simulate an out-of-band tool ignoring foreign_keys; normal writes forbid it.
    with sqlite3.connect(database.path) as connection:
        connection.execute("INSERT INTO teams VALUES ('bad', 'bad', 'Bad', 'DRAFT', 'missing', 100, 100)")
    with database.read() as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        with pytest.raises(SchemaError, match="integrity"):
            check_integrity(connection)
    with pytest.raises(SchemaError):
        database.migrate()


def test_old_sqlite_fails_before_creating_database(tmp_path, monkeypatch):
    monkeypatch.setattr(sqlite3, "sqlite_version_info", (3, 35, 0))
    with pytest.raises(SchemaError, match="SQLite 3.38"):
        AccountDatabase(tmp_path).migrate()
    assert not (tmp_path / "arena.sqlite3").exists()
