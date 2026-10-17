"""Offline-only SQLite foundation, independent of Store and FastAPI startup.

Every maintenance writer holds the same OS lock as the backend. Future backend
integration must use its existing lifespan lock, not nest maintenance() in it.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time

from .account_schema import MIGRATIONS
from .writer_lock import WriterLock


SCHEMA_VERSION = MIGRATIONS[-1][0]
APPLICATION_ID = 0x4E415554  # NAUT; prevents adopting an unrelated SQLite DB.


class SchemaError(RuntimeError):
    """Unknown, damaged or incompatible account schema; never reset it silently."""


def _checksum(statements):
    return hashlib.sha256("\n".join(statements).encode("utf-8")).hexdigest()


def _schema_checksum(connection):
    # Catalog SQL survives physical backups. Include indexes/triggers as well as
    # tables; the ledger's *rows* do not affect this fingerprint. Later ALTER
    # migrations can record a new fingerprint without changing earlier SQL.
    objects = [tuple(row) for row in connection.execute("""SELECT type, name, tbl_name, sql
        FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name""")]
    return hashlib.sha256(json.dumps(objects, ensure_ascii=True).encode("utf-8")).hexdigest()


@contextmanager
def transaction(connection):
    """Short explicit transaction; executescript() would implicitly commit."""
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def _validate_version(connection):
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    application = connection.execute("PRAGMA application_id").fetchone()[0]
    objects = {row[0] for row in connection.execute(
        "SELECT name FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'")}
    if version < 0 or version > SCHEMA_VERSION:
        raise SchemaError(f"Unsupported schema version {version}; supported: 0..{SCHEMA_VERSION}")
    if version == 0:
        if objects or application != 0:
            raise SchemaError("Refusing to initialize a non-empty or foreign unversioned database")
        return 0
    if application != APPLICATION_ID or "schema_migrations" not in objects:
        raise SchemaError("Account database identity or migration ledger is missing")
    try:
        ledger = [tuple(row) for row in connection.execute(
            "SELECT version, name, checksum, schema_checksum FROM schema_migrations ORDER BY version")]
        expected = [(v, name, _checksum(sql)) for v, name, sql in MIGRATIONS if v <= version]
        if [row[:3] for row in ledger] != expected:
            raise SchemaError("Schema version and migration checksums disagree")
        if not ledger or ledger[-1][3] != _schema_checksum(connection):
            raise SchemaError("SQLite schema differs from the recorded migration fingerprint")
    except sqlite3.DatabaseError as exc:
        raise SchemaError("Invalid account migration ledger/schema") from exc
    return version


def _migrate(connection):
    with transaction(connection):
        version = _validate_version(connection)
        if version == 0:
            connection.execute("""CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                checksum TEXT NOT NULL CHECK (length(checksum) = 64),
                schema_checksum TEXT NOT NULL CHECK (length(schema_checksum) = 64),
                applied_at INTEGER NOT NULL
            ) STRICT""")
        for number, name, statements in MIGRATIONS:
            if number <= version:
                continue
            for statement in statements:
                connection.execute(statement)
            connection.execute("INSERT INTO schema_migrations VALUES (?, ?, ?, ?, ?)",
                               (number, name, _checksum(statements), _schema_checksum(connection), int(time.time())))
            connection.execute(f"PRAGMA user_version = {number}")  # trusted migration constant
        connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
        _validate_version(connection)
        check_integrity(connection)


def check_integrity(connection):
    """SQLite's integrity_check does not check foreign keys; run both."""
    integrity = [row[0] for row in connection.execute("PRAGMA integrity_check")]
    if integrity != ["ok"] or connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise SchemaError("SQLite integrity or foreign-key check failed")


class AccountDatabase:
    def __init__(self, data_dir: Path):
        # Inert constructor: importing/constructing this never creates files.
        self.data_dir = Path(data_dir).resolve()
        self.path = self.data_dir / "arena.sqlite3"

    def _connect(self, *, readonly=False, create=False):
        if sqlite3.sqlite_version_info < (3, 38, 0):
            raise SchemaError("SQLite 3.38+ is required (STRICT tables and built-in JSON support)")
        if create:
            # The writer already owns WriterLock. New databases contain password
            # hashes; do not rely on a potentially permissive Linux umask.
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(descriptor)
        mode = "ro" if readonly else "rw"
        connection = sqlite3.connect(self.path.as_uri() + f"?mode={mode}", uri=True,
                                     isolation_level=None, timeout=5)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
                raise SchemaError("This SQLite build does not enforce foreign keys")
            # No WAL sidecars in B.1. Refuse, rather than silently converting a DB.
            if connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
                raise SchemaError("Account foundation requires DELETE journal mode")
            connection.execute("PRAGMA synchronous = FULL")
            return connection
        except BaseException:
            connection.close()
            raise

    @contextmanager
    def maintenance(self):
        """Explicit offline migration/bootstrap. Lock BEFORE even opening SQLite."""
        with WriterLock(self.data_dir):
            connection = self._connect(create=True)
            try:
                _migrate(connection)
                yield connection
            finally:
                connection.close()

    def migrate(self):
        with self.maintenance():
            pass

    @contextmanager
    def writer_connection(self, writer_lock):
        """Borrow an EXISTING outer WriterLock; never initialize or migrate.

        Future FastAPI callers keep the outer lock for the entire lifespan and
        create/use each connection in its owning thread. Close before unlock.
        """
        require_writer(writer_lock, self.data_dir)
        connection = self._connect()
        try:
            validate_service_connection(connection, writer_lock)
            check_integrity(connection)
            yield connection
        finally:
            connection.close()

    @contextmanager
    def read(self):
        """No initialization or fallback when a DB is missing or incompatible."""
        connection = self._connect(readonly=True)
        try:
            if _validate_version(connection) != SCHEMA_VERSION:
                raise SchemaError("Explicit offline migration is required")
            yield connection
        finally:
            connection.close()


def require_writer(writer_lock, data_dir):
    if (not isinstance(writer_lock, WriterLock) or writer_lock.fd is None
            or writer_lock.path != Path(data_dir).resolve() / ".writer.lock"):
        raise RuntimeError("An active WriterLock for this database is required")


def validate_service_connection(connection, writer_lock):
    """DI boundary for trusted callers, not an authorization API."""
    rows = connection.execute("PRAGMA database_list").fetchall()
    main_path = next((row[2] for row in rows if row[1] == "main"), None)
    if not main_path or Path(main_path).name != "arena.sqlite3":
        raise SchemaError("Service requires a persisted arena.sqlite3 database")
    require_writer(writer_lock, Path(main_path).parent)
    if connection.in_transaction or connection.isolation_level is not None:
        raise RuntimeError("Service requires an idle connection with explicit transactions")
    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        raise SchemaError("Service connection must enforce foreign keys")
    if connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
        raise SchemaError("Service connection requires DELETE journal mode")
    if connection.execute("PRAGMA synchronous").fetchone()[0] != 2:
        raise SchemaError("Service connection requires synchronous=FULL")
    if _validate_version(connection) != SCHEMA_VERSION:
        raise SchemaError("Explicit offline migration is required")
