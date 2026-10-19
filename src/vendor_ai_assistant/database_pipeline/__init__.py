"""SQLite serving database utilities for curated vendor data."""

from vendor_ai_assistant.database_pipeline.sqlite_connection import (
    DEFAULT_DB_PATH,
    get_sqlite_connection,
)

__all__ = ["DEFAULT_DB_PATH", "get_sqlite_connection"]
