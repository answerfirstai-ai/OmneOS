"""SQLite connection settings for local databases."""

from __future__ import annotations

import sqlite3


def configure_sqlite(connection: sqlite3.Connection) -> None:
    """Use WAL and a short busy wait for the single local process."""

    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA temp_store=MEMORY")
    connection.execute("PRAGMA busy_timeout=2000")
