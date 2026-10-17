"""Append-only Team and Official Match migrations v3 through v5."""
import sqlite3
import pytest

from backend import account_database
from backend.account_database import AccountDatabase, SCHEMA_VERSION, SchemaError, check_integrity, transaction
from backend.account_schema import MIGRATIONS


def test_new_database_creates_v5_with_team_and_official_indexes(tmp_path):
    db = AccountDatabase(tmp_path)
    db.migrate()
    with db.read() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        ledger = connection.execute("SELECT version, name FROM schema_migrations ORDER BY version").fetchall()
        assert [tuple(row) for row in ledger] == [
            (1, "account_foundation"),
            (2, "auth_service_core"),
            (3, "team_lifecycle_membership"),
            (4, "team_submission_journal"),
            (5, "official_match_scheduling"),
        ]
        indexes = {row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type='index'")}
        assert "membership_active_user_global" in indexes
        assert "team_memberships_team_active" in indexes
        assert "team_invitations_user_status" in indexes
        assert "submission_journal_team" in indexes
        assert "official_due" in indexes
        assert "official_schedule" in indexes
        assert connection.execute("SELECT 1 FROM sqlite_schema WHERE name='submission_journal'").fetchone()
        assert connection.execute("SELECT 1 FROM sqlite_schema WHERE name='official_match_requests'").fetchone()
        assert connection.execute("SELECT 1 FROM sqlite_schema WHERE name='official_match_slots'").fetchone()
        check_integrity(connection)


def test_v2_to_current_upgrade_preserves_existing_data(tmp_path, monkeypatch):
    db = AccountDatabase(tmp_path)
    # 1. Migrate only up to v2
    v2_migrations = MIGRATIONS[:2]
    with monkeypatch.context() as patch:
        patch.setattr(account_database, "MIGRATIONS", v2_migrations)
        patch.setattr(account_database, "SCHEMA_VERSION", 2)
        db.migrate()
        with db.maintenance() as connection, transaction(connection):
            connection.execute("""INSERT INTO users (id, username, display_name, system_role, status, password_hash, created_at, updated_at)
                VALUES ('u1', 'alice', 'Alice', 'PLAYER', 'ACTIVE', '$argon2id$v=19$m=65536,t=3,p=4$dummy$dummy', 100, 100)""")
            connection.execute("""INSERT INTO teams (id, slug, display_name, created_by, created_at, updated_at)
                VALUES ('t1', 'team-alpha', 'Team Alpha', 'u1', 100, 100)""")
            connection.execute("""INSERT INTO team_memberships (id, team_id, user_id, team_role, joined_at, left_at)
                VALUES ('m1', 't1', 'u1', 'CAPTAIN', 100, NULL)""")
            connection.execute("""INSERT INTO auth_sessions (id, token_hash, user_id, audience, auth_version, created_at, expires_at, idle_timeout_seconds)
                VALUES ('s1', ?, 'u1', 'PLAYER', 1, 100, 200, 60)""", ("a" * 64,))

    # 2. Upgrade from v2 through v3/v4 to current v5
    db.migrate()
    with db.read() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert connection.execute("SELECT count(*) FROM users WHERE id='u1'").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM teams WHERE id='t1'").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM team_memberships WHERE id='m1'").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM auth_sessions WHERE id='s1'").fetchone()[0] == 1
        check_integrity(connection)


def test_current_team_migrations_are_idempotent(tmp_path):
    db = AccountDatabase(tmp_path)
    db.migrate()
    db.migrate()
    db.migrate()
    with db.read() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert connection.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == SCHEMA_VERSION
        check_integrity(connection)


def test_v3_upgrade_fails_and_rolls_back_if_conflicting_active_memberships_exist(tmp_path, monkeypatch):
    db = AccountDatabase(tmp_path)
    # Setup v2 with a user who has active memberships in two different teams
    v2_migrations = MIGRATIONS[:2]
    with monkeypatch.context() as patch:
        patch.setattr(account_database, "MIGRATIONS", v2_migrations)
        patch.setattr(account_database, "SCHEMA_VERSION", 2)
        db.migrate()
        with db.maintenance() as connection, transaction(connection):
            connection.execute("""INSERT INTO users (id, username, display_name, system_role, status, password_hash, created_at, updated_at)
                VALUES ('u1', 'alice', 'Alice', 'PLAYER', 'ACTIVE', '$argon2id$v=19$m=65536,t=3,p=4$dummy$dummy', 100, 100)""")
            connection.execute("""INSERT INTO users (id, username, display_name, system_role, status, password_hash, created_at, updated_at)
                VALUES ('u2', 'bob', 'Bob', 'PLAYER', 'ACTIVE', '$argon2id$v=19$m=65536,t=3,p=4$dummy$dummy', 100, 100)""")
            connection.execute("""INSERT INTO teams (id, slug, display_name, created_by, created_at, updated_at)
                VALUES ('t1', 'team-alpha', 'Team Alpha', 'u1', 100, 100)""")
            connection.execute("""INSERT INTO teams (id, slug, display_name, created_by, created_at, updated_at)
                VALUES ('t2', 'team-beta', 'Team Beta', 'u2', 100, 100)""")
            # Alice is CAPTAIN of t1 and also MEMBER of t2 (both active left_at IS NULL):
            connection.execute("""INSERT INTO team_memberships (id, team_id, user_id, team_role, joined_at, left_at)
                VALUES ('m1', 't1', 'u1', 'CAPTAIN', 100, NULL)""")
            connection.execute("""INSERT INTO team_memberships (id, team_id, user_id, team_role, joined_at, left_at)
                VALUES ('m2', 't2', 'u1', 'MEMBER', 100, NULL)""")

    # Attempting to migrate to v3 must fail because of UNIQUE index on active user_id
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
        db.migrate()

    # Verify rollback: database remains intact at v2!
    with sqlite3.connect(db.path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 2
        # Data was not destroyed or silently altered
        assert connection.execute("SELECT count(*) FROM team_memberships").fetchone()[0] == 2


def test_v3_upgrade_succeeds_with_historical_memberships(tmp_path, monkeypatch):
    db = AccountDatabase(tmp_path)
    v2_migrations = MIGRATIONS[:2]
    with monkeypatch.context() as patch:
        patch.setattr(account_database, "MIGRATIONS", v2_migrations)
        patch.setattr(account_database, "SCHEMA_VERSION", 2)
        db.migrate()
        with db.maintenance() as connection, transaction(connection):
            connection.execute("""INSERT INTO users (id, username, display_name, system_role, status, password_hash, created_at, updated_at)
                VALUES ('u1', 'alice', 'Alice', 'PLAYER', 'ACTIVE', '$argon2id$v=19$m=65536,t=3,p=4$dummy$dummy', 100, 100)""")
            connection.execute("""INSERT INTO teams (id, slug, display_name, created_by, created_at, updated_at)
                VALUES ('t1', 'team-alpha', 'Team Alpha', 'u1', 100, 100)""")
            connection.execute("""INSERT INTO teams (id, slug, display_name, created_by, created_at, updated_at)
                VALUES ('t2', 'team-beta', 'Team Beta', 'u1', 100, 100)""")
            # Alice left t1, now active in t2
            connection.execute("""INSERT INTO team_memberships (id, team_id, user_id, team_role, joined_at, left_at)
                VALUES ('m1', 't1', 'u1', 'CAPTAIN', 100, 110)""")
            connection.execute("""INSERT INTO team_memberships (id, team_id, user_id, team_role, joined_at, left_at)
                VALUES ('m2', 't2', 'u1', 'CAPTAIN', 110, NULL)""")

    # v3 unique index remains valid; then v4 journal is applied.
    db.migrate()
    with db.read() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert connection.execute("SELECT count(*) FROM team_memberships").fetchone()[0] == 2
        check_integrity(connection)


def test_v3_to_v4_upgrade_preserves_ownership_and_creates_journal(tmp_path, monkeypatch):
    db = AccountDatabase(tmp_path)
    with monkeypatch.context() as patch:
        patch.setattr(account_database, "MIGRATIONS", MIGRATIONS[:3])
        patch.setattr(account_database, "SCHEMA_VERSION", 3)
        db.migrate()
        with db.maintenance() as connection, transaction(connection):
            connection.execute("""INSERT INTO users
                (id, username, display_name, system_role, status, password_hash, created_at, updated_at)
                VALUES ('u1', 'alice', 'Alice', 'PLAYER', 'ACTIVE',
                '$argon2id$v=19$m=65536,t=3,p=4$dummy$dummy', 100, 100)""")
            connection.execute("""INSERT INTO teams (id,slug,display_name,created_by,created_at,updated_at)
                VALUES ('team-one','team-one','Team One','u1',100,100)""")
            connection.execute("""INSERT INTO team_memberships (id,team_id,user_id,team_role,joined_at,left_at)
                VALUES ('member-one','team-one','u1','CAPTAIN',100,NULL)""")
            connection.execute("""INSERT INTO submission_ownership
                (bot_id,team_id,game_id,uploaded_by,origin,created_at)
                VALUES ('bot-existing','team-one','robot_battle','u1','NEW',100)""")
    db.migrate()
    with db.read() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert connection.execute("SELECT count(*) FROM submission_ownership").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM submission_journal").fetchone()[0] == 0
        check_integrity(connection)


def test_v4_to_v5_upgrade_is_append_only_and_idempotent(tmp_path,monkeypatch):
    db=AccountDatabase(tmp_path)
    with monkeypatch.context() as patch:
        patch.setattr(account_database,"MIGRATIONS",MIGRATIONS[:4])
        patch.setattr(account_database,"SCHEMA_VERSION",4)
        db.migrate()
    db.migrate()
    db.migrate()
    with db.read() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0]==5
        assert connection.execute("SELECT count(*) FROM schema_migrations").fetchone()[0]==5
        assert connection.execute("SELECT count(*) FROM official_match_requests").fetchone()[0]==0
        check_integrity(connection)
