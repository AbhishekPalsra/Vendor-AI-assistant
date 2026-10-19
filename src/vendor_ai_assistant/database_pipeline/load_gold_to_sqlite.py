"""Atomically rebuild the SQLite serving database from Gold Parquet datasets."""

from __future__ import annotations

import argparse
import os
import sqlite3
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pandas as pd
from pandas.api.types import is_bool_dtype, is_datetime64_any_dtype
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from vendor_ai_assistant.data_pipeline.bronze_ingestion import PROJECT_ROOT
from vendor_ai_assistant.data_pipeline.spark_session import get_spark_session
from vendor_ai_assistant.database_pipeline.schema import (
    LOAD_ORDER,
    create_schema,
    populate_search_indexes,
)
from vendor_ai_assistant.database_pipeline.sqlite_connection import (
    DEFAULT_DB_PATH,
    get_sqlite_connection,
)


DEFAULT_GOLD_DIR: Final[Path] = PROJECT_ROOT / "data" / "gold"


def _read_gold_dataset(
    spark: SparkSession, gold_dir: Path, table_name: str
) -> DataFrame:
    source_path = gold_dir / table_name
    if not source_path.is_dir():
        raise FileNotFoundError(f"Missing Gold dataset: {source_path}")
    dataframe = spark.read.parquet(str(source_path))

    # A single order can be fulfilled by multiple warehouses. Populate the
    # optional order warehouse only when the relationship is unambiguous.
    if table_name == "fact_orders":
        shipments_path = gold_dir / "fact_shipments"
        shipment_warehouses = spark.read.parquet(str(shipments_path)).groupBy(
            "order_id"
        ).agg(
            F.countDistinct("warehouse_id").alias("_warehouse_count"),
            F.min("warehouse_id").alias("_single_warehouse_id"),
        )
        dataframe = (
            dataframe.join(shipment_warehouses, "order_id", "left")
            .withColumn(
                "warehouse_id",
                F.when(
                    F.col("_warehouse_count") == 1, F.col("_single_warehouse_id")
                ).otherwise(F.lit(None).cast("string")),
            )
            .drop("_warehouse_count", "_single_warehouse_id")
        )
    return dataframe


def _sqlite_value(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (datetime, date)):
        return value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    return value


def _prepare_for_sqlite(dataframe: pd.DataFrame) -> pd.DataFrame:
    prepared = dataframe.rename(columns={"sku": "product_id"}).copy()
    for column_name in prepared.columns:
        series = prepared[column_name]
        if is_bool_dtype(series.dtype):
            prepared[column_name] = series.astype("Int64").astype(object).where(
                series.notna(), None
            )
        elif is_datetime64_any_dtype(series.dtype):
            formatted = series.dt.strftime("%Y-%m-%d %H:%M:%S.%f")
            prepared[column_name] = formatted.astype(object).where(series.notna(), None)
        else:
            prepared[column_name] = series.astype(object).map(_sqlite_value)
    return prepared


def _table_columns(
    connection: sqlite3.Connection, table_name: str
) -> list[str]:
    rows = connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
    return [row[1] for row in rows]


def _validate_dataframe_columns(
    connection: sqlite3.Connection, table_name: str, dataframe: pd.DataFrame
) -> pd.DataFrame:
    expected = _table_columns(connection, table_name)
    actual = set(dataframe.columns)
    missing = set(expected) - actual
    extra = actual - set(expected)
    if missing or extra:
        raise ValueError(
            f"Column mismatch for {table_name}: missing={sorted(missing)}, "
            f"extra={sorted(extra)}"
        )
    return dataframe[expected]


def _temporary_database_path(database_path: Path) -> Path:
    resolved = database_path.resolve()
    temporary = resolved.with_suffix(resolved.suffix + ".tmp")
    if temporary.parent != resolved.parent or temporary.name != resolved.name + ".tmp":
        raise ValueError(f"Unsafe temporary database path: {temporary}")
    return temporary


def load_gold_to_sqlite(
    spark: SparkSession,
    gold_dir: Path = DEFAULT_GOLD_DIR,
    database_path: Path = DEFAULT_DB_PATH,
) -> dict[str, int]:
    """Load Gold tables into a constrained SQLite database and replace atomically."""
    gold_dir = gold_dir.resolve()
    database_path = database_path.resolve()
    temporary_path = _temporary_database_path(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    if temporary_path.exists():
        if not temporary_path.is_file() or temporary_path.is_symlink():
            raise RuntimeError(f"Refusing to remove unsafe temporary path: {temporary_path}")
        temporary_path.unlink()

    connection = get_sqlite_connection(temporary_path)
    loaded_counts: dict[str, int] = {}
    try:
        create_schema(connection)
        for table_name in LOAD_ORDER:
            spark_dataframe = _read_gold_dataset(spark, gold_dir, table_name)
            input_count = spark_dataframe.count()
            pandas_dataframe = _prepare_for_sqlite(spark_dataframe.toPandas())
            pandas_dataframe = _validate_dataframe_columns(
                connection, table_name, pandas_dataframe
            )
            pandas_dataframe.to_sql(
                table_name,
                connection,
                if_exists="append",
                index=False,
                chunksize=5_000,
            )
            loaded_count = connection.execute(
                f'SELECT COUNT(*) FROM "{table_name}"'
            ).fetchone()[0]
            if input_count != loaded_count:
                raise RuntimeError(
                    f"Count mismatch for {table_name}: {input_count} != {loaded_count}"
                )
            loaded_counts[table_name] = loaded_count
            print(
                f"{table_name}: input={input_count}, loaded={loaded_count}"
            )

        populate_search_indexes(connection)

        foreign_key_failures = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()
        if foreign_key_failures:
            raise RuntimeError(
                f"SQLite foreign-key validation failed: {foreign_key_failures[:10]}"
            )
        integrity_result = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity_result != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {integrity_result}")
        connection.commit()
    except Exception:
        connection.close()
        if temporary_path.exists() and temporary_path.is_file():
            temporary_path.unlink()
        raise
    else:
        connection.close()

    os.replace(temporary_path, database_path)
    print(f"SQLite serving database created at {database_path}")
    return loaded_counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Load Gold Parquet data into SQLite")
    parser.add_argument("--gold-dir", type=Path, default=DEFAULT_GOLD_DIR)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB_PATH)
    args = parser.parse_args()
    spark = get_spark_session("vendor-ai-gold-to-sqlite")
    try:
        load_gold_to_sqlite(spark, args.gold_dir, args.database)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
