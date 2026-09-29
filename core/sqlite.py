"""SQLite connection settings for local databases."""

from __future__ import annotations

import sqlite3


def configure_sqlite(connection: sqlite3.Connection) -> None:
    """Use WAL and a short busy wait for the single local process."""

    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA temp_store=MEMORY")
    connection.execute("PRAGMA busy_timeout=2000")


def ensure_schema(connection: sqlite3.Connection, name: str, version: int, statement: str) -> None:
    """Create a table when it is missing and record the schema version.

    Existing databases keep their rows. A newer version than this process
    understands is refused instead of being rewritten.
    """

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            name TEXT PRIMARY KEY,
            version INTEGER NOT NULL
        )
        """
    )
    row = connection.execute(
        "SELECT version FROM schema_migrations WHERE name = ?",
        (name,),
    ).fetchone()
    current = int(row[0]) if row is not None else 0
    if current > version:
        raise RuntimeError(f"database schema {name} version {current} is newer than {version}")
    connection.execute(statement)
    connection.execute(
        """
        INSERT INTO schema_migrations (name, version)
        VALUES (?, ?)
        ON CONFLICT(name) DO UPDATE SET version = excluded.version
        """,
        (name, version),
    )


def ensure_column(
    connection: sqlite3.Connection, table: str, column: str, declaration: str
) -> None:
    """Add a column when an older database does not have it."""

    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    names = {str(row[1]) for row in rows}
    if column not in names:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
