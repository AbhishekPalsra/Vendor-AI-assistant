"""Idempotent PySpark transformations from validated Silver data to Gold."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Final

from pyspark.sql import Column, DataFrame, SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import StructType

from vendor_ai_assistant.data_pipeline.bronze_ingestion import PROJECT_ROOT
from vendor_ai_assistant.data_pipeline.gold_schemas import (
    DIM_BUYERS_SCHEMA,
    DIM_PRODUCTS_SCHEMA,
    DIM_WAREHOUSES_SCHEMA,
    FACT_INVENTORY_SCHEMA,
    FACT_ORDER_ITEMS_SCHEMA,
    FACT_ORDERS_SCHEMA,
    FACT_PRICING_SCHEMA,
    FACT_SHIPMENTS_SCHEMA,
    GOLD_QUALITY_REPORT_SCHEMA,
    MART_ORDER_HISTORY_SCHEMA,
    MART_PRICING_CATALOG_SCHEMA,
    MART_PRODUCT_AVAILABILITY_SCHEMA,
)
from vendor_ai_assistant.data_pipeline.silver_transformations import DEFAULT_SILVER_DIR
from vendor_ai_assistant.data_pipeline.spark_session import get_spark_session


DEFAULT_GOLD_DIR: Final[Path] = PROJECT_ROOT / "data" / "gold"
MONEY_TOLERANCE: Final[Decimal] = Decimal("0.01")
SILVER_DATASETS: Final[tuple[str, ...]] = (
    "products",
    "customers_retailers",
    "inventory",
    "pricing",
    "orders",
    "order_items",
    "shipments",
)
ORDER_PARTITIONED_DATASETS: Final[set[str]] = {
    "fact_orders",
    "fact_order_items",
    "fact_shipments",
    "mart_order_history",
}


def _conform(dataframe: DataFrame, schema: StructType) -> DataFrame:
    return dataframe.select(
        *[F.col(field.name).cast(field.dataType).alias(field.name) for field in schema]
    )


def _processed_at(pipeline_timestamp: datetime) -> Column:
    return F.lit(pipeline_timestamp).cast("timestamp")


def transform_dim_products(products: DataFrame, timestamp: datetime) -> DataFrame:
    return _conform(
        products.select(
            "sku", "product_name", "category", "brand", "pack_size", "unit_type",
            _processed_at(timestamp).alias("_gold_processed_at"),
        ),
        DIM_PRODUCTS_SCHEMA,
    )


def transform_dim_buyers(buyers: DataFrame, timestamp: datetime) -> DataFrame:
    return _conform(
        buyers.select(
            "buyer_id", "buyer_type", "buyer_name", "city", "state",
            "retailer_tier", "credit_limit_inr", "payment_terms", "discount_group",
            "status", _processed_at(timestamp).alias("_gold_processed_at"),
        ),
        DIM_BUYERS_SCHEMA,
    )


def transform_dim_warehouses(inventory: DataFrame, timestamp: datetime) -> DataFrame:
    region_by_city = F.create_map(
        F.lit("Bengaluru"), F.lit("South"),
        F.lit("Delhi NCR"), F.lit("North"),
        F.lit("Jaipur"), F.lit("North"),
        F.lit("Kolkata"), F.lit("East"),
        F.lit("Lucknow"), F.lit("North"),
        F.lit("Mumbai"), F.lit("West"),
    )
    warehouses = inventory.select(
        "warehouse_id", F.col("warehouse_name").alias("warehouse_city")
    ).distinct()
    return _conform(
        warehouses.select(
            "warehouse_id",
            "warehouse_city",
            F.coalesce(region_by_city[F.col("warehouse_city")], F.lit("Unknown")).alias(
                "region"
            ),
            _processed_at(timestamp).alias("_gold_processed_at"),
        ),
        DIM_WAREHOUSES_SCHEMA,
    )


def transform_fact_inventory(inventory: DataFrame, timestamp: datetime) -> DataFrame:
    return _conform(
        inventory.select(
            "sku", "warehouse_id", "quantity_on_hand", "reserved_quantity",
            "available_quantity", "reorder_level", "last_updated",
            (F.col("available_quantity") <= F.col("reorder_level")).alias("is_low_stock"),
            _processed_at(timestamp).alias("_gold_processed_at"),
        ),
        FACT_INVENTORY_SCHEMA,
    )


def transform_fact_pricing(
    pricing: DataFrame, run_date: date, timestamp: datetime
) -> DataFrame:
    current = (
        (F.col("status") == "Active")
        & (F.col("valid_from") <= F.lit(run_date))
        & (F.col("valid_to") >= F.lit(run_date))
    )
    return _conform(
        pricing.select(
            "pricing_id", "sku", F.col("customer_type").alias("buyer_type"),
            "retailer_tier", "minimum_quantity", "maximum_quantity", "quantity_slab",
            "base_price_inr", "discount_rate", "net_unit_price_inr", "valid_from",
            "valid_to", "status", current.alias("is_current"),
            _processed_at(timestamp).alias("_gold_processed_at"),
        ),
        FACT_PRICING_SCHEMA,
    )


def transform_fact_order_items(items: DataFrame, timestamp: datetime) -> DataFrame:
    return _conform(
        items.select(
            "order_id", "line_item_number", "sku", "quantity",
            "historical_unit_price_inr", "gross_amount_inr", "discount_rate",
            "discount_amount_inr", "taxable_amount_inr", "tax_rate",
            "tax_amount_inr", "line_total_inr", "order_year", "order_month",
            _processed_at(timestamp).alias("_gold_processed_at"),
        ),
        FACT_ORDER_ITEMS_SCHEMA,
    )


def transform_fact_orders(
    orders: DataFrame, items: DataFrame, timestamp: datetime
) -> DataFrame:
    item_totals = items.groupBy("order_id").agg(
        F.sum("gross_amount_inr").alias("gross_amount_inr"),
        F.sum("discount_amount_inr").alias("discount_amount_inr"),
        F.sum("taxable_amount_inr").alias("taxable_amount_inr"),
        F.sum("tax_amount_inr").alias("tax_amount_inr"),
        F.sum("line_total_inr").alias("order_total_inr"),
    )
    header = orders.select(
        "order_id", "buyer_id", "buyer_type", "order_date", "order_status",
        "payment_status", F.col("ship_city").alias("destination_city"),
        F.col("ship_state").alias("destination_state"), "order_year", "order_month",
    )
    return _conform(
        header.join(item_totals, "order_id", "inner").select(
            "order_id", "buyer_id", "buyer_type", "order_date", "order_status",
            "payment_status", "destination_city", "destination_state",
            "gross_amount_inr", "discount_amount_inr", "taxable_amount_inr",
            "tax_amount_inr", "order_total_inr", "order_year", "order_month",
            _processed_at(timestamp).alias("_gold_processed_at"),
        ),
        FACT_ORDERS_SCHEMA,
    )


def transform_fact_shipments(shipments: DataFrame, timestamp: datetime) -> DataFrame:
    return _conform(
        shipments.select(
            "shipment_id", "order_id", "warehouse_id", "shipping_method", "carrier",
            "tracking_number", "shipment_date", "expected_delivery_date", "delivery_date",
            F.col("ship_city").alias("destination_city"),
            F.col("ship_state").alias("destination_state"), "order_year", "order_month",
            _processed_at(timestamp).alias("_gold_processed_at"),
        ),
        FACT_SHIPMENTS_SCHEMA,
    )


def transform_mart_product_availability(
    products: DataFrame, inventory: DataFrame, warehouses: DataFrame, timestamp: datetime
) -> DataFrame:
    p, i, w = products.alias("p"), inventory.alias("i"), warehouses.alias("w")
    joined = i.join(p, "sku", "inner").join(w, "warehouse_id", "inner")
    return _conform(
        joined.select(
            "sku", "p.product_name", "p.category", "p.brand", "p.pack_size",
            "p.unit_type", "warehouse_id", "w.warehouse_city", "w.region",
            "i.quantity_on_hand", "i.reserved_quantity", "i.available_quantity",
            "i.reorder_level", "i.is_low_stock", "i.last_updated",
            _processed_at(timestamp).alias("_gold_processed_at"),
        ),
        MART_PRODUCT_AVAILABILITY_SCHEMA,
    )


def transform_mart_pricing_catalog(
    products: DataFrame, pricing: DataFrame, timestamp: datetime
) -> DataFrame:
    p, r = products.alias("p"), pricing.alias("r")
    return _conform(
        r.join(p, "sku", "inner").select(
            "r.pricing_id", "sku", "p.product_name", "p.category", "p.brand",
            "p.pack_size", "p.unit_type", "r.buyer_type", "r.retailer_tier",
            "r.minimum_quantity", "r.maximum_quantity", "r.quantity_slab",
            "r.base_price_inr", "r.discount_rate", "r.net_unit_price_inr",
            "r.valid_from", "r.valid_to", "r.status", "r.is_current",
            _processed_at(timestamp).alias("_gold_processed_at"),
        ),
        MART_PRICING_CATALOG_SCHEMA,
    )


def _shipment_summary(shipments: DataFrame) -> DataFrame:
    return shipments.groupBy("order_id").agg(
        F.count("shipment_id").cast("long").alias("shipment_count"),
        F.concat_ws(", ", F.sort_array(F.collect_set("warehouse_id"))).alias(
            "warehouse_ids"
        ),
        F.concat_ws(", ", F.sort_array(F.collect_set("carrier"))).alias("carriers"),
        F.concat_ws(", ", F.sort_array(F.collect_set("tracking_number"))).alias(
            "tracking_numbers"
        ),
        F.min("shipment_date").alias("first_shipment_date"),
        F.max("expected_delivery_date").alias("latest_expected_delivery_date"),
        F.max("delivery_date").alias("latest_delivery_date"),
    )


def transform_mart_order_history(
    orders: DataFrame,
    items: DataFrame,
    products: DataFrame,
    buyers: DataFrame,
    shipments: DataFrame,
    timestamp: datetime,
) -> DataFrame:
    o, i, p, b = (
        orders.alias("o"), items.alias("i"), products.alias("p"), buyers.alias("b")
    )
    summary = _shipment_summary(shipments).alias("s")
    joined = (
        i.join(o, "order_id", "inner")
        .join(p, "sku", "inner")
        .join(b, "buyer_id", "inner")
        .join(summary, "order_id", "left")
    )
    return _conform(
        joined.select(
            "order_id", "i.line_item_number", "o.order_date", "o.order_status",
            "o.payment_status", "buyer_id", "b.buyer_type", "b.buyer_name",
            F.col("b.city").alias("buyer_city"), F.col("b.state").alias("buyer_state"),
            "b.retailer_tier", "sku", "p.product_name", "p.category", "p.brand",
            "i.quantity", "i.historical_unit_price_inr", "i.gross_amount_inr",
            "i.discount_rate", "i.discount_amount_inr", "i.taxable_amount_inr",
            "i.tax_rate", "i.tax_amount_inr", "i.line_total_inr",
            "o.order_total_inr", "o.destination_city", "o.destination_state",
            F.coalesce(F.col("s.shipment_count"), F.lit(0)).cast("long").alias(
                "shipment_count"
            ),
            "s.warehouse_ids", "s.carriers", "s.tracking_numbers",
            "s.first_shipment_date", "s.latest_expected_delivery_date",
            "s.latest_delivery_date", "i.order_year", "i.order_month",
            _processed_at(timestamp).alias("_gold_processed_at"),
        ),
        MART_ORDER_HISTORY_SCHEMA,
    )


def build_gold_datasets(
    silver: dict[str, DataFrame], run_date: date, pipeline_timestamp: datetime
) -> dict[str, DataFrame]:
    """Build every Gold DataFrame without reading or writing external state."""
    dim_products = transform_dim_products(silver["products"], pipeline_timestamp)
    dim_buyers = transform_dim_buyers(
        silver["customers_retailers"], pipeline_timestamp
    )
    dim_warehouses = transform_dim_warehouses(silver["inventory"], pipeline_timestamp)
    fact_inventory = transform_fact_inventory(silver["inventory"], pipeline_timestamp)
    fact_pricing = transform_fact_pricing(silver["pricing"], run_date, pipeline_timestamp)
    fact_order_items = transform_fact_order_items(
        silver["order_items"], pipeline_timestamp
    )
    fact_orders = transform_fact_orders(
        silver["orders"], silver["order_items"], pipeline_timestamp
    )
    fact_shipments = transform_fact_shipments(silver["shipments"], pipeline_timestamp)
    return {
        "dim_products": dim_products,
        "dim_buyers": dim_buyers,
        "dim_warehouses": dim_warehouses,
        "fact_inventory": fact_inventory,
        "fact_pricing": fact_pricing,
        "fact_orders": fact_orders,
        "fact_order_items": fact_order_items,
        "fact_shipments": fact_shipments,
        "mart_product_availability": transform_mart_product_availability(
            dim_products, fact_inventory, dim_warehouses, pipeline_timestamp
        ),
        "mart_pricing_catalog": transform_mart_pricing_catalog(
            dim_products, fact_pricing, pipeline_timestamp
        ),
        "mart_order_history": transform_mart_order_history(
            fact_orders, fact_order_items, dim_products, dim_buyers, fact_shipments,
            pipeline_timestamp,
        ),
    }


def _duplicate_count(dataframe: DataFrame, keys: list[str]) -> int:
    row = (
        dataframe.groupBy(*keys)
        .count()
        .filter(F.col("count") > 1)
        .select(F.sum(F.col("count") - 1).alias("duplicates"))
        .first()
    )
    return int(row["duplicates"] or 0)


def _null_key_count(dataframe: DataFrame, keys: list[str]) -> int:
    condition = F.lit(False)
    for key in keys:
        condition = condition | F.col(key).isNull()
    return dataframe.filter(condition).count()


def _foreign_key_failures(
    dataframe: DataFrame, references: list[tuple[list[str], DataFrame]]
) -> int:
    return sum(
        dataframe.join(reference.select(*keys).distinct(), keys, "left_anti").count()
        for keys, reference in references
    )


def _money_mismatch(actual: str, expected: Column) -> Column:
    return F.abs(F.col(actual) - expected) > F.lit(MONEY_TOLERANCE)


def _business_reconciliation_counts(
    silver: dict[str, DataFrame], gold: dict[str, DataFrame], run_date: date
) -> dict[str, int]:
    inventory_failures = gold["fact_inventory"].filter(
        F.col("available_quantity")
        != F.col("quantity_on_hand") - F.col("reserved_quantity")
    ).count()
    expected_net = F.round(
        F.col("base_price_inr") * (F.lit(1) - F.col("discount_rate")), 2
    )
    expected_current = (
        (F.col("status") == "Active")
        & (F.col("valid_from") <= F.lit(run_date))
        & (F.col("valid_to") >= F.lit(run_date))
    )
    pricing_failures = gold["fact_pricing"].filter(
        _money_mismatch("net_unit_price_inr", expected_net)
        | (F.col("valid_from") > F.col("valid_to"))
        | (F.col("is_current") != expected_current)
    ).count()
    item_failures = gold["fact_order_items"].filter(
        _money_mismatch(
            "gross_amount_inr",
            F.round(F.col("quantity") * F.col("historical_unit_price_inr"), 2),
        )
        | _money_mismatch(
            "discount_amount_inr",
            F.round(F.col("gross_amount_inr") * F.col("discount_rate"), 2),
        )
        | _money_mismatch(
            "taxable_amount_inr",
            F.round(F.col("gross_amount_inr") - F.col("discount_amount_inr"), 2),
        )
        | _money_mismatch(
            "tax_amount_inr",
            F.round(F.col("taxable_amount_inr") * F.col("tax_rate"), 2),
        )
        | _money_mismatch(
            "line_total_inr",
            F.round(F.col("taxable_amount_inr") + F.col("tax_amount_inr"), 2),
        )
    ).count()
    silver_orders = silver["orders"].select(
        "order_id",
        *[
            F.col(column).alias(f"silver_{column}")
            for column in [
                "gross_amount_inr", "discount_amount_inr", "taxable_amount_inr",
                "tax_amount_inr", "order_total_inr",
            ]
        ],
    )
    order_comparison = gold["fact_orders"].join(silver_orders, "order_id", "inner")
    order_condition = F.lit(False)
    for column in [
        "gross_amount_inr", "discount_amount_inr", "taxable_amount_inr",
        "tax_amount_inr", "order_total_inr",
    ]:
        order_condition = order_condition | _money_mismatch(
            column, F.col(f"silver_{column}")
        )
    order_failures = order_comparison.filter(order_condition).count()
    return {
        "fact_inventory": inventory_failures,
        "fact_pricing": pricing_failures,
        "fact_orders": order_failures,
        "fact_order_items": item_failures,
    }


def create_quality_report(
    spark: SparkSession,
    silver: dict[str, DataFrame],
    gold: dict[str, DataFrame],
    run_date: date,
    pipeline_timestamp: datetime,
) -> tuple[DataFrame, list[dict[str, object]]]:
    """Execute dynamic grain, key, FK, and business-rule validations."""
    source_counts = {
        "dim_products": silver["products"].count(),
        "dim_buyers": silver["customers_retailers"].count(),
        "dim_warehouses": silver["inventory"].select("warehouse_id").distinct().count(),
        "fact_inventory": silver["inventory"].count(),
        "fact_pricing": silver["pricing"].count(),
        "fact_orders": silver["orders"].count(),
        "fact_order_items": silver["order_items"].count(),
        "fact_shipments": silver["shipments"].count(),
        "mart_product_availability": silver["inventory"].count(),
        "mart_pricing_catalog": silver["pricing"].count(),
        "mart_order_history": silver["order_items"].count(),
    }
    keys = {
        "dim_products": ["sku"],
        "dim_buyers": ["buyer_id"],
        "dim_warehouses": ["warehouse_id"],
        "fact_inventory": ["sku", "warehouse_id"],
        "fact_pricing": ["pricing_id"],
        "fact_orders": ["order_id"],
        "fact_order_items": ["order_id", "line_item_number"],
        "fact_shipments": ["shipment_id"],
        "mart_product_availability": ["sku", "warehouse_id"],
        "mart_pricing_catalog": ["pricing_id"],
        "mart_order_history": ["order_id", "line_item_number"],
    }
    products, buyers, warehouses = (
        gold["dim_products"], gold["dim_buyers"], gold["dim_warehouses"]
    )
    orders = gold["fact_orders"]
    foreign_keys: dict[str, list[tuple[list[str], DataFrame]]] = {
        "dim_products": [],
        "dim_buyers": [],
        "dim_warehouses": [],
        "fact_inventory": [(["sku"], products), (["warehouse_id"], warehouses)],
        "fact_pricing": [(["sku"], products)],
        "fact_orders": [(["buyer_id"], buyers)],
        "fact_order_items": [(["sku"], products), (["order_id"], orders)],
        "fact_shipments": [(["order_id"], orders), (["warehouse_id"], warehouses)],
        "mart_product_availability": [
            (["sku"], products), (["warehouse_id"], warehouses)
        ],
        "mart_pricing_catalog": [(["sku"], products)],
        "mart_order_history": [
            (["sku"], products), (["buyer_id"], buyers), (["order_id"], orders)
        ],
    }
    business_failures = _business_reconciliation_counts(silver, gold, run_date)
    reports: list[dict[str, object]] = []
    for name, dataframe in gold.items():
        output_count = dataframe.count()
        duplicate_count = _duplicate_count(dataframe, keys[name])
        null_count = _null_key_count(dataframe, keys[name])
        fk_count = _foreign_key_failures(dataframe, foreign_keys[name])
        grain_delta = abs(source_counts[name] - output_count)
        business_count = business_failures.get(name, 0)
        reconciliation_count = grain_delta + business_count
        passed = (
            duplicate_count == 0
            and null_count == 0
            and fk_count == 0
            and reconciliation_count == 0
        )
        reports.append(
            {
                "dataset_name": name,
                "source_count": source_counts[name],
                "output_count": output_count,
                "duplicate_count": duplicate_count,
                "null_key_count": null_count,
                "foreign_key_failure_count": fk_count,
                "reconciliation_failure_count": reconciliation_count,
                "reconciliation_results": (
                    f"source_output_match={str(grain_delta == 0).lower()}; "
                    f"business_rule_failures={business_count}"
                ),
                "checks_passed": passed,
                "pipeline_timestamp": pipeline_timestamp,
            }
        )
    rows = [tuple(report[field.name] for field in GOLD_QUALITY_REPORT_SCHEMA) for report in reports]
    return spark.createDataFrame(rows, GOLD_QUALITY_REPORT_SCHEMA), reports


def _write_gold(dataframe: DataFrame, destination: Path, partitioned: bool) -> None:
    writer = dataframe.write.mode("overwrite")
    if partitioned:
        writer = writer.partitionBy("order_year", "order_month")
    writer.parquet(str(destination))


def run_gold_pipeline(
    spark: SparkSession,
    silver_dir: Path = DEFAULT_SILVER_DIR,
    gold_dir: Path = DEFAULT_GOLD_DIR,
    run_date: date | None = None,
) -> list[dict[str, object]]:
    """Validate and overwrite all Gold outputs using Silver inputs only."""
    silver_dir, gold_dir = silver_dir.resolve(), gold_dir.resolve()
    effective_date = run_date or datetime.now(timezone.utc).date()
    pipeline_timestamp = datetime.now(timezone.utc).replace(tzinfo=None)
    silver = {
        name: spark.read.parquet(str(silver_dir / name)).cache()
        for name in SILVER_DATASETS
    }
    gold = {
        name: dataframe.cache()
        for name, dataframe in build_gold_datasets(
            silver, effective_date, pipeline_timestamp
        ).items()
    }
    quality_report, reports = create_quality_report(
        spark, silver, gold, effective_date, pipeline_timestamp
    )
    failed = [report["dataset_name"] for report in reports if not report["checks_passed"]]
    if failed:
        raise RuntimeError(
            "Gold validation failed before write for: " + ", ".join(str(x) for x in failed)
        )

    for name, dataframe in gold.items():
        _write_gold(dataframe, gold_dir / name, name in ORDER_PARTITIONED_DATASETS)
        persisted_count = spark.read.parquet(str(gold_dir / name)).count()
        expected_count = next(
            int(report["output_count"])
            for report in reports
            if report["dataset_name"] == name
        )
        if persisted_count != expected_count:
            raise RuntimeError(
                f"Gold read-back count failed for {name}: {persisted_count} != {expected_count}"
            )
    _write_gold(quality_report, gold_dir / "gold_quality_report", False)

    for dataframe in [*silver.values(), *gold.values()]:
        dataframe.unpersist()
    return reports


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Gold analytics datasets from Silver")
    parser.add_argument("--silver-dir", type=Path, default=DEFAULT_SILVER_DIR)
    parser.add_argument("--gold-dir", type=Path, default=DEFAULT_GOLD_DIR)
    parser.add_argument(
        "--run-date", type=date.fromisoformat, default=None,
        help="Date used for is_current pricing flags (YYYY-MM-DD)",
    )
    args = parser.parse_args()
    spark = get_spark_session("vendor-ai-gold-transformations")
    try:
        reports = run_gold_pipeline(spark, args.silver_dir, args.gold_dir, args.run_date)
        for report in reports:
            print(
                "{dataset_name}: source={source_count}, output={output_count}, "
                "duplicates={duplicate_count}, null_keys={null_key_count}, "
                "fk_failures={foreign_key_failure_count}, "
                "reconciliation_failures={reconciliation_failure_count}, "
                "passed={checks_passed}".format(**report)
            )
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
