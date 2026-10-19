"""Reusable Spark session construction."""

import os
import sys
from pathlib import Path

from pyspark.sql import SparkSession


def get_spark_session(app_name: str = "vendor-ai-data-pipeline") -> SparkSession:
    """Return the active Spark session, creating a local one when necessary."""
    # Spark's Windows launcher otherwise looks for a Unix-style ``python3``.
    os.environ.setdefault("PYSPARK_PYTHON", sys.executable)
    os.environ.setdefault("PYSPARK_DRIVER_PYTHON", sys.executable)

    # Allow a project-local Hadoop Windows runtime without requiring global setup.
    local_hadoop_home = Path(__file__).resolve().parents[3] / ".hadoop"
    if sys.platform == "win32" and (local_hadoop_home / "bin" / "winutils.exe").is_file():
        os.environ.setdefault("HADOOP_HOME", str(local_hadoop_home))
        hadoop_bin = str(local_hadoop_home / "bin")
        if hadoop_bin not in os.environ.get("PATH", "").split(os.pathsep):
            os.environ["PATH"] = hadoop_bin + os.pathsep + os.environ.get("PATH", "")
    return (
        SparkSession.builder.appName(app_name)
        .master("local[*]")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", "8")
        .getOrCreate()
    )
