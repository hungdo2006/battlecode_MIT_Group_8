"""Offline account maintenance: python -m backend.admin_cli --help.

There is deliberately no password flag, environment fallback, or startup hook.
"""
import argparse
import getpass
from pathlib import Path
import sqlite3
import sys
import time
import uuid
import warnings

from .account_database import AccountDatabase, SchemaError, check_integrity, transaction
from .account_identity import normalize_username
from .passwords import hash_password
from .writer_lock import WriterAlreadyRunning


class AccountExistsError(ValueError):
    pass


def _ensure_available(connection, username):
    if connection.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
        # Never promote/overwrite an existing Player or reset an existing Admin.
        raise AccountExistsError("Username already exists; no account was changed")


def _insert_admin(connection, username, password, display_name):
    _ensure_available(connection, username)
    if not 1 <= len(display_name.strip()) <= 64:
        raise ValueError("Display name must contain 1..64 characters")
    encoded = hash_password(password)
    user_id, now = uuid.uuid4().hex, int(time.time())
    with transaction(connection):
        connection.execute("""INSERT INTO users (
            id, username, display_name, system_role, status, password_hash,
            created_at, updated_at, password_changed_at)
            VALUES (?, ?, ?, 'ADMIN', 'ACTIVE', ?, ?, ?, ?)""",
            (user_id, username, display_name.strip(), encoded, now, now, now))
        connection.execute("""INSERT INTO audit_events (
            occurred_at, actor_user_id, action, target_type, target_id)
            VALUES (?, ?, 'OFFLINE_ADMIN_CREATED', 'user', ?)""", (now, user_id, user_id))
    # No hash or password is returned/logged.
    return user_id


def bootstrap_admin(data_dir: Path, username: str, password: str, display_name: str | None = None) -> str:
    """Trusted Python helper for offline callers/tests; password is never argv."""
    username = normalize_username(username)
    with AccountDatabase(data_dir).maintenance() as connection:
        return _insert_admin(connection, username, password, display_name or username)


def invalidate_restored_auth(data_dir: Path) -> dict:
    """Offline post-restore fence: no restored session or token remains usable."""
    with AccountDatabase(data_dir).maintenance() as connection, transaction(connection):
        now = int(time.time())
        sessions = connection.execute("""UPDATE auth_sessions
            SET revoked_at=max(created_at, ?) WHERE revoked_at IS NULL""", (now,)).rowcount
        tokens = connection.execute("""UPDATE account_tokens SET revoked_at=max(created_at, ?)
            WHERE consumed_at IS NULL AND revoked_at IS NULL""", (now,)).rowcount
        users = connection.execute("""UPDATE users SET auth_version=auth_version+1,
            updated_at=max(updated_at, ?) WHERE status='ACTIVE'""", (now,)).rowcount
        connection.execute("""INSERT INTO audit_events (
            occurred_at, actor_user_id, action, target_type, target_id, details_json)
            VALUES (?, NULL, 'RESTORE_AUTH_INVALIDATED', 'system', 'restore', ?)""",
            (now, '{"reason":"offline_restore_fence"}'))
        return {"sessions_revoked": sessions, "tokens_revoked": tokens, "users_fenced": users}


def main(argv=None):
    parser = argparse.ArgumentParser(description="NEON ARENA offline account maintenance (stop backend first)")
    parser.add_argument("--data-dir", type=Path, required=True,
                        help="Explicit data directory, e.g. ./data or /app/data (no implicit default)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="Create/validate schema without creating an account")
    commands.add_parser("check", help="Read-only schema, SQLite integrity and foreign-key checks")
    commands.add_parser("invalidate-restored-auth",
                        help="Revoke restored sessions/tokens before first startup")
    create = commands.add_parser("create-admin", help="Create an Admin using a hidden terminal prompt")
    create.add_argument("--username", required=True)
    create.add_argument("--display-name")
    args = parser.parse_args(argv)
    database = AccountDatabase(args.data_dir)
    try:
        if args.command == "check":
            with database.read() as connection:
                check_integrity(connection)
            print("Account schema and SQLite integrity: OK")
        elif args.command == "migrate":
            database.migrate()
            print("Account schema is current")
        elif args.command == "invalidate-restored-auth":
            result = invalidate_restored_auth(args.data_dir)
            print("Restored authentication invalidated: "
                  f"{result['sessions_revoked']} sessions, {result['tokens_revoked']} tokens, "
                  f"{result['users_fenced']} active users")
        else:
            username = normalize_username(args.username)
            # Refuse redirected input: getpass can otherwise fall back to echoing.
            if not sys.stdin.isatty():
                raise ValueError("create-admin requires an interactive terminal; do not pipe a password")
            with database.maintenance() as connection:
                _ensure_available(connection, username)
                with warnings.catch_warnings():
                    warnings.simplefilter("error", getpass.GetPassWarning)
                    password = getpass.getpass("New Admin password: ")
                    confirmation = getpass.getpass("Confirm password: ")
                if password != confirmation:
                    raise ValueError("Passwords do not match; no Admin was created")
                user_id = _insert_admin(connection, username, password, args.display_name or username)
                del password, confirmation
            print(f"Admin account created: {username} ({user_id}). Account HTTP remains opt-in via server configuration.")
        return 0
    except (ValueError, SchemaError, WriterAlreadyRunning, sqlite3.Error, OSError, getpass.GetPassWarning) as exc:
        print(f"Account maintenance refused: {exc}", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("Account maintenance cancelled", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
