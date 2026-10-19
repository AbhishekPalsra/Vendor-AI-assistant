"""Reusable SQLite connection creation with enforced referential integrity."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Final


PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH: Final[Path] = PROJECT_ROOT / "data" / "vendor_ai.db"


def get_sqlite_connection(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open a SQLite connection and enable foreign-key enforcement."""
    resolved_path = db_path.resolve()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(resolved_path)
    connection.execute("PRAGMA foreign_keys = ON")
    enabled = connection.execute("PRAGMA foreign_keys").fetchone()[0]
    if enabled != 1:
        connection.close()
        raise RuntimeError("SQLite foreign-key enforcement could not be enabled")
    return connection
