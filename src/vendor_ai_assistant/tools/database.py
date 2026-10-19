"""Read-only, parameterized SQLite access for approved handlers."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final, Iterator, Sequence

from vendor_ai_assistant.database_pipeline.sqlite_connection import DEFAULT_DB_PATH


class DatabaseUnavailableError(RuntimeError):
    """Raised internally when the serving database cannot be read."""


READ_ONLY_PREFIXES: Final[tuple[str, ...]] = ("SELECT", "WITH")


@contextmanager
def read_only_connection(
    database_path: Path = DEFAULT_DB_PATH,
) -> Iterator[sqlite3.Connection]:
    path = database_path.resolve()
    if not path.is_file():
        raise DatabaseUnavailableError("Serving database is unavailable")
    try:
        connection = sqlite3.connect(
            f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5.0
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA foreign_keys = ON")
    except sqlite3.Error as error:
        raise DatabaseUnavailableError("Serving database is unavailable") from error
    try:
        yield connection
    finally:
        connection.close()


def fetch_all(
    connection: sqlite3.Connection,
    query: str,
    parameters: Sequence[Any] = (),
) -> list[dict[str, Any]]:
    normalized = query.lstrip().upper()
    if not normalized.startswith(READ_ONLY_PREFIXES):
        raise ValueError("Only read-only queries are permitted")
    return [dict(row) for row in connection.execute(query, tuple(parameters)).fetchall()]


def fetch_one(
    connection: sqlite3.Connection,
    query: str,
    parameters: Sequence[Any] = (),
) -> dict[str, Any] | None:
    rows = fetch_all(connection, query, parameters)
    return rows[0] if rows else None


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

