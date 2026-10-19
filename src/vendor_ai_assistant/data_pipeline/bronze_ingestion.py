"""Bronze-layer ingestion for the vendor AI source datasets.

The Bronze layer intentionally performs no business-data cleaning, renaming,
deduplication, or joins. Excel sources are loaded by pandas/openpyxl before
conversion to Spark DataFrames; the CSV source is loaded directly by Spark.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Final

import pandas as pd
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

from vendor_ai_assistant.data_pipeline.spark_session import get_spark_session


PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
DEFAULT_RAW_DIR: Final[Path] = PROJECT_ROOT / "data" / "raw_data"
DEFAULT_BRONZE_DIR: Final[Path] = PROJECT_ROOT / "data" / "bronze"

EXCEL_DATASETS: Final[dict[str, str]] = {
    "products": "products.xlsx",
    "inventory": "inventory.xlsx",
    "pricing": "pricing.xlsx",
    "customers_retailers": "customers_retailers.xlsx",
}
CSV_DATASETS: Final[dict[str, str]] = {
    "historical_orders": "historical_orders.csv",
}


def _with_ingestion_metadata(dataframe: DataFrame, source_file: str) -> DataFrame:
    """Append technical lineage fields without modifying business columns."""
    return dataframe.withColumn("_source_file", F.lit(source_file)).withColumn(
        "_ingested_at", F.current_timestamp()
    )


def read_excel_as_spark(spark: SparkSession, source_path: Path) -> DataFrame:
    """Read an Excel workbook with pandas/openpyxl and convert it to Spark."""
    pandas_dataframe = pd.read_excel(source_path, engine="openpyxl")
    return spark.createDataFrame(pandas_dataframe)


def ingest_bronze(
    spark: SparkSession,
    raw_dir: Path = DEFAULT_RAW_DIR,
    bronze_dir: Path = DEFAULT_BRONZE_DIR,
) -> dict[str, Path]:
    """Ingest every raw source and overwrite its corresponding Bronze dataset."""
    raw_dir = raw_dir.resolve()
    bronze_dir = bronze_dir.resolve()
    written: dict[str, Path] = {}

    for dataset_name, filename in EXCEL_DATASETS.items():
        source_path = raw_dir / filename
        dataframe = read_excel_as_spark(spark, source_path)
        bronze_dataframe = _with_ingestion_metadata(dataframe, filename)
        destination = bronze_dir / dataset_name
        bronze_dataframe.write.mode("overwrite").parquet(str(destination))
        written[dataset_name] = destination

    for dataset_name, filename in CSV_DATASETS.items():
        source_path = raw_dir / filename
        dataframe = spark.read.option("header", True).option("inferSchema", True).csv(
            str(source_path)
        )
        bronze_dataframe = _with_ingestion_metadata(dataframe, filename)
        destination = bronze_dir / dataset_name
        bronze_dataframe.write.mode("overwrite").parquet(str(destination))
        written[dataset_name] = destination

    return written


def main() -> None:
    """Run Bronze ingestion from the command line."""
    parser = argparse.ArgumentParser(description="Ingest raw vendor data to Bronze")
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--bronze-dir", type=Path, default=DEFAULT_BRONZE_DIR)
    args = parser.parse_args()

    spark = get_spark_session("vendor-ai-bronze-ingestion")
    try:
        outputs = ingest_bronze(spark, args.raw_dir, args.bronze_dir)
        for dataset_name, destination in outputs.items():
            print(f"Wrote {dataset_name} to {destination}")
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
