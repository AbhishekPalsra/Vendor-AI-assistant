# Vendor AI Assistant

For a detailed architecture walkthrough, learning roadmap, trade-off analysis,
and project-specific interview preparation, read the
[Interview and Learning Guide](docs/INTERVIEW_PROJECT_GUIDE.md).

## Bronze ingestion

The Bronze pipeline copies each raw dataset to its own Parquet directory without
cleaning, renaming, joining, or otherwise transforming business fields. It adds
only `_source_file` and `_ingested_at` lineage columns.

```powershell
uv run ingest-bronze
```

Inputs are read from `data/raw_data` and outputs are written to
`data/bronze/<dataset_name>/`. Alternate locations can be supplied with
`--raw-dir` and `--bronze-dir`.

PySpark on native Windows also requires a compatible Hadoop `winutils.exe` and
`HADOOP_HOME` configuration in order to write to the local filesystem. This is
an environment prerequisite; Linux and managed Spark environments do not need
that Windows-specific setup.

## Silver transformations

Run the validated Silver transformations after Bronze ingestion:

```powershell
uv run transform-silver
```

Valid typed datasets are written to `data/silver`, rejected source records are
written to `data/quarantine` with rejection reasons, and the reconciled run
report is stored at `data/silver/data_quality_report`. The `orders`,
`order_items`, and `shipments` datasets are partitioned by `order_year` and
`order_month`.

## Gold analytics layer

Build all Gold dimensions, facts, marts, and the Gold quality report from
Silver only:

```powershell
uv run transform-gold
```

Use `--run-date YYYY-MM-DD` to reproduce pricing `is_current` flags for a
specific date. Outputs are overwritten safely under `data/gold`; order-related
facts and `mart_order_history` are partitioned by `order_year` and
`order_month`.

Run the Gold transformation and row-grain tests with:

```powershell
uv run python -m unittest discover -s tests -v
```

## SQLite serving database

Rebuild `data/vendor_ai.db` atomically from the curated Gold Parquet datasets:

```powershell
uv run load-gold-sqlite
```

The loader creates explicit primary-key, foreign-key, check, and index
definitions before appending rows with pandas. It loads dimensions before facts
and marts, validates the temporary database, and replaces the serving database
only after every check passes.

Validate the finished database independently with:

```powershell
uv run validate-sqlite-load
```
