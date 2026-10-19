"""Validate table counts, foreign keys, and integrity of the SQLite serving DB."""

from __future__ import annotations

import argparse
from pathlib import Path

from vendor_ai_assistant.database_pipeline.schema import LOAD_ORDER
from vendor_ai_assistant.database_pipeline.sqlite_connection import (
    DEFAULT_DB_PATH,
    get_sqlite_connection,
)


def validate_sqlite_load(database_path: Path = DEFAULT_DB_PATH) -> bool:
    resolved_path = database_path.resolve()
    if not resolved_path.is_file():
        print(f"FAILURE: SQLite database does not exist: {resolved_path}")
        return False

    connection = get_sqlite_connection(resolved_path)
    success = True
    try:
        for table_name in LOAD_ORDER:
            count = connection.execute(
                f'SELECT COUNT(*) FROM "{table_name}"'
            ).fetchone()[0]
            print(f"{table_name}: {count}")

        failures = connection.execute("PRAGMA foreign_key_check").fetchall()
        if failures:
            success = False
            print(f"FAILURE: {len(failures)} foreign-key violation(s)")
            for failure in failures[:20]:
                print(f"  {failure}")
        else:
            print("SUCCESS: PRAGMA foreign_key_check returned no violations")

        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            success = False
            print(f"FAILURE: PRAGMA integrity_check returned {integrity}")
        else:
            print("SUCCESS: PRAGMA integrity_check returned ok")
    except Exception as error:
        success = False
        print(f"FAILURE: SQLite validation error: {error}")
    finally:
        connection.close()
    return success


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the SQLite Gold load")
    parser.add_argument("--database", type=Path, default=DEFAULT_DB_PATH)
    args = parser.parse_args()
    if not validate_sqlite_load(args.database):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
