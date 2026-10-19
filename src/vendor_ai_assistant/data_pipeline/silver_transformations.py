"""Silver transformations, validation, quarantine, and quality reporting."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Final, Iterable

from pyspark.sql import Column, DataFrame, SparkSession, Window
from pyspark.sql import functions as F
from pyspark.sql.types import StructType

from vendor_ai_assistant.data_pipeline.bronze_ingestion import (
    DEFAULT_BRONZE_DIR,
    PROJECT_ROOT,
)
from vendor_ai_assistant.data_pipeline.silver_schemas import (
    CUSTOMER_SCHEMA,
    DATA_QUALITY_REPORT_SCHEMA,
    INVENTORY_SCHEMA,
    ORDER_ITEM_SCHEMA,
    ORDER_SCHEMA,
    PRICING_SCHEMA,
    PRODUCT_SCHEMA,
    SHIPMENT_SCHEMA,
)
from vendor_ai_assistant.data_pipeline.spark_session import get_spark_session


DEFAULT_SILVER_DIR: Final[Path] = PROJECT_ROOT / "data" / "silver"
DEFAULT_QUARANTINE_DIR: Final[Path] = PROJECT_ROOT / "data" / "quarantine"
MONEY_TOLERANCE: Final[Decimal] = Decimal("0.01")


def _text(column_name: str) -> Column:
    return F.trim(F.col(column_name).cast("string"))


def _nullable_text(column_name: str) -> Column:
    value = _text(column_name)
    return F.when(value == "", F.lit(None).cast("string")).otherwise(value)


def _blank(column_name: str) -> Column:
    return F.col(column_name).isNull() | (F.trim(F.col(column_name)) == "")


def _conform(dataframe: DataFrame, schema: StructType) -> DataFrame:
    """Select fields in declared order and enforce each declared data type."""
    return dataframe.select(
        *[F.col(field.name).cast(field.dataType).alias(field.name) for field in schema]
    )


def _annotate_rejections(
    dataframe: DataFrame, checks: Iterable[tuple[str, Column]]
) -> DataFrame:
    reasons = [F.when(condition, F.lit(reason)) for reason, condition in checks]
    return dataframe.withColumn(
        "_rejection_reasons", F.array_compact(F.array(*reasons))
    ).withColumn("rejection_reason", F.concat_ws("; ", "_rejection_reasons"))


def _split_valid_rejected(dataframe: DataFrame) -> tuple[DataFrame, DataFrame]:
    valid = dataframe.filter(F.size("_rejection_reasons") == 0).drop(
        "_rejection_reasons", "rejection_reason"
    )
    rejected = dataframe.filter(F.size("_rejection_reasons") > 0).drop(
        "_rejection_reasons"
    )
    return valid, rejected


def _quarantine(
    dataframe: DataFrame, dataset_name: str, business_columns: list[str]
) -> DataFrame:
    return dataframe.select(*business_columns, "rejection_reason").withColumn(
        "dataset_name", F.lit(dataset_name)
    ).withColumn("_quarantined_at", F.current_timestamp())


def _write_parquet(
    dataframe: DataFrame, destination: Path, partitions: list[str] | None = None
) -> None:
    writer = dataframe.write.mode("overwrite")
    if partitions:
        writer = writer.partitionBy(*partitions)
    writer.parquet(str(destination))


def transform_products(bronze: DataFrame) -> tuple[DataFrame, DataFrame]:
    columns = [
        "sku",
        "product_name",
        "category",
        "brand",
        "pack_size",
        "unit_type",
        "_source_file",
        "_ingested_at",
        "_silver_processed_at",
    ]
    standardized = bronze.select(
        _text("SKU").alias("sku"),
        _text("Product Name").alias("product_name"),
        _text("Category").alias("category"),
        _text("Brand").alias("brand"),
        F.col("Pack Size").cast("int").alias("pack_size"),
        _text("Unit Type").alias("unit_type"),
        "_source_file",
        "_ingested_at",
        F.current_timestamp().alias("_silver_processed_at"),
    ).withColumn("_key_count", F.count("*").over(Window.partitionBy("sku")))

    annotated = _annotate_rejections(
        standardized,
        [
            ("missing_or_invalid_sku", _blank("sku") | ~F.col("sku").rlike(r"^SKU-\d{5}$")),
            ("duplicate_sku", F.col("_key_count") > 1),
            ("missing_product_name", _blank("product_name")),
            ("missing_category", _blank("category")),
            ("missing_brand", _blank("brand")),
            ("pack_size_must_be_positive", F.col("pack_size").isNull() | (F.col("pack_size") <= 0)),
            ("invalid_unit_type", ~F.col("unit_type").isin("g", "kg", "ml", "L", "pack")),
        ],
    ).drop("_key_count")
    valid, rejected = _split_valid_rejected(annotated)
    return _conform(valid, PRODUCT_SCHEMA), _quarantine(rejected, "products", columns)


def transform_inventory(
    bronze: DataFrame, valid_products: DataFrame
) -> tuple[DataFrame, DataFrame]:
    warehouse = F.split(_text("Warehouse / Location"), r"\s+-\s+", 2)
    columns = [field.name for field in INVENTORY_SCHEMA]
    standardized = bronze.select(
        _text("SKU / Product ID").alias("sku"),
        warehouse.getItem(0).alias("warehouse_id"),
        warehouse.getItem(1).alias("warehouse_name"),
        F.col("Quantity on Hand").cast("long").alias("quantity_on_hand"),
        F.col("Reserved Quantity").cast("long").alias("reserved_quantity"),
        F.col("Available Quantity").cast("long").alias("available_quantity"),
        F.col("Reorder Level").cast("long").alias("reorder_level"),
        F.col("Last Updated").cast("timestamp").alias("last_updated"),
        "_source_file",
        "_ingested_at",
        F.current_timestamp().alias("_silver_processed_at"),
    )
    standardized = (
        standardized.join(
            valid_products.select("sku").withColumn("_valid_sku", F.lit(True)),
            "sku",
            "left",
        )
        .withColumn(
            "_key_count", F.count("*").over(Window.partitionBy("sku", "warehouse_id"))
        )
    )
    quantity_columns = [
        "quantity_on_hand",
        "reserved_quantity",
        "available_quantity",
        "reorder_level",
    ]
    annotated = _annotate_rejections(
        standardized,
        [
            ("missing_sku", _blank("sku")),
            ("unknown_sku", F.col("_valid_sku").isNull()),
            ("invalid_warehouse_id", _blank("warehouse_id") | ~F.col("warehouse_id").rlike(r"^WH-[A-Z]{3}-\d{2}$")),
            ("missing_warehouse_name", _blank("warehouse_name")),
            ("duplicate_sku_warehouse", F.col("_key_count") > 1),
            ("invalid_inventory_quantity", F.greatest(*[F.col(c).isNull().cast("int") for c in quantity_columns]) == 1),
            ("negative_inventory_quantity", F.least(*[F.col(c) for c in quantity_columns]) < 0),
            ("reserved_exceeds_on_hand", F.col("reserved_quantity") > F.col("quantity_on_hand")),
            ("available_quantity_mismatch", F.col("available_quantity") != F.col("quantity_on_hand") - F.col("reserved_quantity")),
            ("missing_last_updated", F.col("last_updated").isNull()),
        ],
    ).drop("_valid_sku", "_key_count")
    valid, rejected = _split_valid_rejected(annotated)
    return _conform(valid, INVENTORY_SCHEMA), _quarantine(rejected, "inventory", columns)


def transform_pricing(
    bronze: DataFrame, valid_products: DataFrame
) -> tuple[DataFrame, DataFrame]:
    maximum_quantity = F.when(
        F.isnan(F.col("Maximum Quantity")), F.lit(None).cast("long")
    ).otherwise(F.col("Maximum Quantity").cast("long"))
    columns = [field.name for field in PRICING_SCHEMA]
    standardized = bronze.select(
        _text("Pricing ID").alias("pricing_id"),
        _text("SKU / Product ID").alias("sku"),
        _text("Customer Type").alias("customer_type"),
        _text("Retailer Tier").alias("retailer_tier"),
        F.col("Minimum Quantity").cast("long").alias("minimum_quantity"),
        maximum_quantity.alias("maximum_quantity"),
        _text("Quantity Slab").alias("quantity_slab"),
        F.col("Base Price (INR)").cast("decimal(18,2)").alias("base_price_inr"),
        F.col("Discount %").cast("decimal(9,4)").alias("discount_rate"),
        F.col("Wholesale / Net Unit Price (INR)").cast("decimal(18,2)").alias("net_unit_price_inr"),
        _text("Discount Rule").alias("discount_rule"),
        F.to_date("Valid From").alias("valid_from"),
        F.to_date("Valid To").alias("valid_to"),
        _text("Status").alias("status"),
        "_source_file",
        "_ingested_at",
        F.current_timestamp().alias("_silver_processed_at"),
    )
    standardized = (
        standardized.join(
            valid_products.select("sku").withColumn("_valid_sku", F.lit(True)),
            "sku",
            "left",
        )
        .withColumn("_id_count", F.count("*").over(Window.partitionBy("pricing_id")))
        .withColumn(
            "_rule_count",
            F.count("*").over(
                Window.partitionBy(
                    "sku", "customer_type", "retailer_tier", "minimum_quantity",
                    "maximum_quantity", "valid_from", "valid_to"
                )
            ),
        )
    )
    expected_net = F.round(F.col("base_price_inr") * (F.lit(1) - F.col("discount_rate")), 2)
    annotated = _annotate_rejections(
        standardized,
        [
            ("missing_pricing_id", _blank("pricing_id")),
            ("duplicate_pricing_id", F.col("_id_count") > 1),
            ("duplicate_pricing_rule", F.col("_rule_count") > 1),
            ("unknown_sku", F.col("_valid_sku").isNull()),
            ("invalid_customer_type", ~F.col("customer_type").isin("Customer", "Retailer")),
            ("invalid_retailer_tier", ~F.col("retailer_tier").isin("Not Applicable", "Bronze", "Silver", "Gold")),
            ("customer_tier_mismatch", ((F.col("customer_type") == "Customer") & (F.col("retailer_tier") != "Not Applicable")) | ((F.col("customer_type") == "Retailer") & (F.col("retailer_tier") == "Not Applicable"))),
            ("minimum_quantity_must_be_positive", F.col("minimum_quantity").isNull() | (F.col("minimum_quantity") < 1)),
            ("maximum_quantity_before_minimum", F.col("maximum_quantity").isNotNull() & (F.col("maximum_quantity") < F.col("minimum_quantity"))),
            ("base_price_must_be_positive", F.col("base_price_inr").isNull() | (F.col("base_price_inr") <= 0)),
            ("invalid_discount_rate", F.col("discount_rate").isNull() | (F.col("discount_rate") < 0) | (F.col("discount_rate") > 1)),
            ("net_price_mismatch", F.col("net_unit_price_inr").isNull() | (F.abs(F.col("net_unit_price_inr") - expected_net) > F.lit(MONEY_TOLERANCE))),
            ("invalid_validity_dates", F.col("valid_from").isNull() | F.col("valid_to").isNull() | (F.col("valid_from") > F.col("valid_to"))),
            ("invalid_pricing_status", ~F.col("status").isin("Active", "Inactive")),
            ("missing_quantity_slab", _blank("quantity_slab")),
            ("missing_discount_rule", _blank("discount_rule")),
        ],
    ).drop("_valid_sku", "_id_count", "_rule_count")
    valid, rejected = _split_valid_rejected(annotated)
    return _conform(valid, PRICING_SCHEMA), _quarantine(rejected, "pricing", columns)


def transform_customers(bronze: DataFrame) -> tuple[DataFrame, DataFrame]:
    columns = [field.name for field in CUSTOMER_SCHEMA]
    standardized = bronze.select(
        _text("Customer / Retailer ID").alias("buyer_id"),
        _text("Type").alias("buyer_type"),
        _text("Name / Business Name").alias("buyer_name"),
        _text("City").alias("city"),
        _text("State").alias("state"),
        _text("Phone").alias("phone"),
        F.lower(_text("Email")).alias("email"),
        _text("Retailer Tier").alias("retailer_tier"),
        F.col("Credit Limit (INR)").cast("decimal(18,2)").alias("credit_limit_inr"),
        _text("Payment Terms").alias("payment_terms"),
        _text("Discount Group").alias("discount_group"),
        _text("Status").alias("status"),
        "_source_file",
        "_ingested_at",
        F.current_timestamp().alias("_silver_processed_at"),
    ).withColumn("_key_count", F.count("*").over(Window.partitionBy("buyer_id")))
    annotated = _annotate_rejections(
        standardized,
        [
            ("missing_or_invalid_buyer_id", _blank("buyer_id") | ~F.col("buyer_id").rlike(r"^(CUS|RET)-\d{5}$")),
            ("duplicate_buyer_id", F.col("_key_count") > 1),
            ("invalid_buyer_type", ~F.col("buyer_type").isin("Customer", "Retailer")),
            ("buyer_id_type_mismatch", ((F.col("buyer_type") == "Customer") & ~F.col("buyer_id").startswith("CUS-")) | ((F.col("buyer_type") == "Retailer") & ~F.col("buyer_id").startswith("RET-"))),
            ("invalid_retailer_tier", ~F.col("retailer_tier").isin("Not Applicable", "Bronze", "Silver", "Gold")),
            ("buyer_type_tier_mismatch", ((F.col("buyer_type") == "Customer") & (F.col("retailer_tier") != "Not Applicable")) | ((F.col("buyer_type") == "Retailer") & (F.col("retailer_tier") == "Not Applicable"))),
            ("missing_buyer_name", _blank("buyer_name")),
            ("missing_location", _blank("city") | _blank("state")),
            ("invalid_phone", ~F.col("phone").rlike(r"^\+91-\d{5}-\d{5}$")),
            ("invalid_email", ~F.col("email").rlike(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")),
            ("negative_credit_limit", F.col("credit_limit_inr").isNull() | (F.col("credit_limit_inr") < 0)),
            ("invalid_payment_terms", ~F.col("payment_terms").isin("Due on Receipt", "Prepaid", "Net 15", "Net 30", "Net 45")),
            ("missing_discount_group", _blank("discount_group")),
            ("invalid_customer_status", ~F.col("status").isin("Active", "Inactive", "On Hold")),
        ],
    ).drop("_key_count")
    valid, rejected = _split_valid_rejected(annotated)
    return _conform(valid, CUSTOMER_SCHEMA), _quarantine(rejected, "customers_retailers", columns)


def _standardize_historical_orders(bronze: DataFrame) -> DataFrame:
    money = "decimal(20,2)"
    return bronze.select(
        _text("order_id").alias("order_id"),
        F.col("line_item_number").cast("int").alias("line_item_number"),
        _text("buyer_id").alias("buyer_id"),
        _text("buyer_type").alias("buyer_type"),
        F.to_date("order_date").alias("order_date"),
        _text("sku").alias("sku"),
        _text("product_name").alias("product_name"),
        F.col("quantity").cast("long").alias("quantity"),
        F.col("historical_unit_price_inr").cast("decimal(18,2)").alias("historical_unit_price_inr"),
        F.col("gross_amount_inr").cast(money).alias("gross_amount_inr"),
        F.col("discount_percent").cast("decimal(9,4)").alias("discount_rate"),
        F.col("discount_amount_inr").cast(money).alias("discount_amount_inr"),
        F.col("taxable_amount_inr").cast(money).alias("taxable_amount_inr"),
        F.col("tax_rate").cast("decimal(9,4)").alias("tax_rate"),
        F.col("tax_amount_inr").cast(money).alias("tax_amount_inr"),
        F.col("line_total_inr").cast(money).alias("line_total_inr"),
        _text("order_status").alias("order_status"),
        _text("payment_status").alias("payment_status"),
        _text("warehouse_id").alias("warehouse_id"),
        _text("ship_city").alias("ship_city"),
        _text("ship_state").alias("ship_state"),
        _nullable_text("shipping_method").alias("shipping_method"),
        _nullable_text("carrier").alias("carrier"),
        _nullable_text("tracking_number").alias("tracking_number"),
        F.to_date("shipment_date").alias("shipment_date"),
        F.to_date("expected_delivery_date").alias("expected_delivery_date"),
        F.to_date("delivery_date").alias("delivery_date"),
        "_source_file",
        "_ingested_at",
        F.current_timestamp().alias("_silver_processed_at"),
    )


def transform_historical_orders(
    bronze: DataFrame, valid_products: DataFrame, valid_customers: DataFrame
) -> tuple[DataFrame, DataFrame, DataFrame, DataFrame]:
    standardized = _standardize_historical_orders(bronze)
    base_columns = standardized.columns
    product_lookup = valid_products.select(
        "sku", F.col("product_name").alias("_master_product_name")
    ).withColumn("_valid_sku", F.lit(True))
    buyer_lookup = valid_customers.select(
        "buyer_id", F.col("buyer_type").alias("_master_buyer_type")
    ).withColumn("_valid_buyer", F.lit(True))
    standardized = standardized.join(product_lookup, "sku", "left").join(
        buyer_lookup, "buyer_id", "left"
    )
    line_window = Window.partitionBy("order_id", "line_item_number")
    order_window = Window.partitionBy("order_id")
    standardized = standardized.withColumn("_line_count", F.count("*").over(line_window))

    consistent_fields = [
        "buyer_id", "buyer_type", "order_date", "order_status", "payment_status",
        "ship_city", "ship_state", "shipping_method", "carrier", "tracking_number",
        "shipment_date", "expected_delivery_date", "delivery_date",
    ]
    consistency_checks: list[tuple[str, Column]] = []
    for field in consistent_fields:
        comparable = F.coalesce(F.col(field).cast("string"), F.lit("__NULL__"))
        standardized = standardized.withColumn(
            f"_consistent_{field}",
            F.min(comparable).over(order_window) == F.max(comparable).over(order_window),
        )
        consistency_checks.append(
            (f"inconsistent_order_{field}", ~F.col(f"_consistent_{field}"))
        )

    shipment_fields = [
        "shipping_method", "carrier", "tracking_number", "shipment_date",
        "expected_delivery_date", "delivery_date",
    ]
    present_count = sum(
        (F.col(field).isNotNull()).cast("int") for field in shipment_fields
    )
    expected_gross = F.round(F.col("quantity") * F.col("historical_unit_price_inr"), 2)
    expected_discount = F.round(F.col("gross_amount_inr") * F.col("discount_rate"), 2)
    expected_taxable = F.round(F.col("gross_amount_inr") - F.col("discount_amount_inr"), 2)
    expected_tax = F.round(F.col("taxable_amount_inr") * F.col("tax_rate"), 2)
    expected_total = F.round(F.col("taxable_amount_inr") + F.col("tax_amount_inr"), 2)
    order_statuses = [
        "Pending Confirmation", "Confirmed", "Allocated", "Picked", "Packed",
        "Shipped", "Delivered", "Cancelled", "Returned",
    ]
    checks: list[tuple[str, Column]] = [
        ("missing_order_id", _blank("order_id")),
        ("invalid_line_item_number", F.col("line_item_number").isNull() | (F.col("line_item_number") < 1)),
        ("duplicate_order_line", F.col("_line_count") > 1),
        ("unknown_sku", F.col("_valid_sku").isNull()),
        ("product_name_does_not_match_sku", F.col("_valid_sku").isNotNull() & (F.col("product_name") != F.col("_master_product_name"))),
        ("unknown_buyer", F.col("_valid_buyer").isNull()),
        ("buyer_type_does_not_match_buyer", F.col("_valid_buyer").isNotNull() & (F.col("buyer_type") != F.col("_master_buyer_type"))),
        ("invalid_order_date", F.col("order_date").isNull()),
        ("invalid_order_status", ~F.col("order_status").isin(*order_statuses)),
        ("invalid_payment_status", ~F.col("payment_status").isin("Paid", "Pending", "Voided", "Refunded", "Partially Refunded")),
        ("invalid_warehouse_id", _blank("warehouse_id") | ~F.col("warehouse_id").rlike(r"^WH-[A-Z]{3}-\d{2}$")),
        ("missing_shipping_location", _blank("ship_city") | _blank("ship_state")),
        ("quantity_must_be_positive", F.col("quantity").isNull() | (F.col("quantity") <= 0)),
        ("invalid_unit_price", F.col("historical_unit_price_inr").isNull() | (F.col("historical_unit_price_inr") < 0)),
        ("invalid_discount_rate", F.col("discount_rate").isNull() | (F.col("discount_rate") < 0) | (F.col("discount_rate") > 1)),
        ("invalid_tax_rate", F.col("tax_rate").isNull() | (F.col("tax_rate") < 0) | (F.col("tax_rate") > 1)),
        ("gross_amount_mismatch", F.col("gross_amount_inr").isNull() | (F.abs(F.col("gross_amount_inr") - expected_gross) > F.lit(MONEY_TOLERANCE))),
        ("discount_amount_mismatch", F.col("discount_amount_inr").isNull() | (F.abs(F.col("discount_amount_inr") - expected_discount) > F.lit(MONEY_TOLERANCE))),
        ("taxable_amount_mismatch", F.col("taxable_amount_inr").isNull() | (F.abs(F.col("taxable_amount_inr") - expected_taxable) > F.lit(MONEY_TOLERANCE))),
        ("tax_amount_mismatch", F.col("tax_amount_inr").isNull() | (F.abs(F.col("tax_amount_inr") - expected_tax) > F.lit(MONEY_TOLERANCE))),
        ("line_total_mismatch", F.col("line_total_inr").isNull() | (F.abs(F.col("line_total_inr") - expected_total) > F.lit(MONEY_TOLERANCE))),
        ("partial_shipment_details", (present_count != 0) & (present_count != len(shipment_fields))),
        ("shipment_before_order", F.col("shipment_date").isNotNull() & (F.col("shipment_date") < F.col("order_date"))),
        ("expected_delivery_before_shipment", F.col("expected_delivery_date").isNotNull() & (F.col("expected_delivery_date") < F.col("shipment_date"))),
        ("delivery_before_shipment", F.col("delivery_date").isNotNull() & (F.col("delivery_date") < F.col("shipment_date"))),
        ("cancelled_order_has_shipment", (F.col("order_status") == "Cancelled") & (present_count > 0)),
        ("fulfilled_order_missing_shipment", F.col("order_status").isin("Shipped", "Delivered", "Returned") & (present_count != len(shipment_fields))),
        ("delivered_order_missing_delivery_date", (F.col("order_status") == "Delivered") & F.col("delivery_date").isNull()),
        ("returned_order_missing_delivery_date", (F.col("order_status") == "Returned") & F.col("delivery_date").isNull()),
        *consistency_checks,
    ]
    annotated = _annotate_rejections(standardized, checks)

    # Reject all lines in a bad order; otherwise order totals would be partial.
    annotated = annotated.withColumn(
        "_order_has_invalid_line",
        F.max((F.size("_rejection_reasons") > 0).cast("int")).over(order_window),
    ).withColumn(
        "_rejection_reasons",
        F.when(
            (F.col("_order_has_invalid_line") == 1) & (F.size("_rejection_reasons") == 0),
            F.array(F.lit("order_contains_invalid_line")),
        ).otherwise(F.col("_rejection_reasons")),
    ).withColumn("rejection_reason", F.concat_ws("; ", "_rejection_reasons"))

    helper_columns = [column for column in annotated.columns if column.startswith("_consistent_")]
    annotated = annotated.drop(
        "_valid_sku", "_master_product_name", "_valid_buyer", "_master_buyer_type",
        "_line_count", "_order_has_invalid_line", *helper_columns
    )
    valid_lines, rejected_lines = _split_valid_rejected(annotated)
    valid_lines = valid_lines.withColumn("order_year", F.year("order_date")).withColumn(
        "order_month", F.month("order_date")
    )

    order_items = _conform(valid_lines, ORDER_ITEM_SCHEMA)
    orders = valid_lines.groupBy(
        "order_id", "buyer_id", "buyer_type", "order_date", "order_status",
        "payment_status", "ship_city", "ship_state", "order_year", "order_month",
    ).agg(
        F.sum("gross_amount_inr").alias("gross_amount_inr"),
        F.sum("discount_amount_inr").alias("discount_amount_inr"),
        F.sum("taxable_amount_inr").alias("taxable_amount_inr"),
        F.sum("tax_amount_inr").alias("tax_amount_inr"),
        F.sum("line_total_inr").alias("order_total_inr"),
        F.first("_source_file").alias("_source_file"),
        F.first("_ingested_at").alias("_ingested_at"),
        F.first("_silver_processed_at").alias("_silver_processed_at"),
    )
    orders = _conform(orders, ORDER_SCHEMA)

    shipments = (
        valid_lines.filter(F.col("tracking_number").isNotNull())
        .select(
            F.concat_ws("-", "order_id", "warehouse_id").alias("shipment_id"),
            "order_id", "warehouse_id", "shipping_method", "carrier",
            "tracking_number", "shipment_date", "expected_delivery_date",
            "delivery_date", "ship_city", "ship_state", "order_year", "order_month",
            "_source_file", "_ingested_at", "_silver_processed_at",
        )
        .dropDuplicates(["shipment_id"])
    )
    shipments = _conform(shipments, SHIPMENT_SCHEMA)
    quarantine = _quarantine(rejected_lines, "historical_orders", base_columns)
    return orders, order_items, shipments, quarantine


def run_silver_pipeline(
    spark: SparkSession,
    bronze_dir: Path = DEFAULT_BRONZE_DIR,
    silver_dir: Path = DEFAULT_SILVER_DIR,
    quarantine_dir: Path = DEFAULT_QUARANTINE_DIR,
) -> list[dict[str, object]]:
    """Transform all Bronze datasets and return reconciled quality counts."""
    bronze_dir, silver_dir, quarantine_dir = (
        bronze_dir.resolve(), silver_dir.resolve(), quarantine_dir.resolve()
    )
    reports: list[dict[str, object]] = []

    def process_master(
        name: str, transformer: object, *dependencies: DataFrame
    ) -> tuple[DataFrame, DataFrame]:
        source = spark.read.parquet(str(bronze_dir / name)).cache()
        valid, rejected = transformer(source, *dependencies)  # type: ignore[operator]
        valid, rejected = valid.cache(), rejected.cache()
        input_count, valid_count, rejected_count = source.count(), valid.count(), rejected.count()
        if input_count != valid_count + rejected_count:
            raise RuntimeError(f"Count reconciliation failed for {name}")
        _write_parquet(valid, silver_dir / name)
        _write_parquet(rejected, quarantine_dir / name)
        output_count = spark.read.parquet(str(silver_dir / name)).count()
        reports.append(
            dict(dataset_name=name, input_count=input_count, valid_count=valid_count,
                 rejected_count=rejected_count, output_count=output_count)
        )
        source.unpersist()
        rejected.unpersist()
        return valid, rejected

    products, _ = process_master("products", transform_products)
    inventory, _ = process_master("inventory", transform_inventory, products)
    pricing, _ = process_master("pricing", transform_pricing, products)
    customers, _ = process_master("customers_retailers", transform_customers)

    historical = spark.read.parquet(str(bronze_dir / "historical_orders")).cache()
    orders, order_items, shipments, rejected_orders = transform_historical_orders(
        historical, products, customers
    )
    orders, order_items, shipments, rejected_orders = (
        orders.cache(), order_items.cache(), shipments.cache(), rejected_orders.cache()
    )
    historical_count = historical.count()
    item_count, rejected_count = order_items.count(), rejected_orders.count()
    if historical_count != item_count + rejected_count:
        raise RuntimeError("Count reconciliation failed for historical_orders")
    for name, dataframe in [
        ("orders", orders), ("order_items", order_items), ("shipments", shipments)
    ]:
        _write_parquet(
            dataframe, silver_dir / name, partitions=["order_year", "order_month"]
        )
    _write_parquet(rejected_orders, quarantine_dir / "historical_orders")
    reports.append(
        dict(dataset_name="historical_orders", input_count=historical_count,
             valid_count=item_count, rejected_count=rejected_count, output_count=item_count)
    )
    order_input_count = historical.select("order_id").distinct().count()
    rejected_order_count = rejected_orders.select("order_id").distinct().count()
    order_output_count = spark.read.parquet(str(silver_dir / "orders")).count()
    reports.append(
        dict(dataset_name="orders", input_count=order_input_count,
             valid_count=orders.count(), rejected_count=rejected_order_count,
             output_count=order_output_count)
    )
    item_output_count = spark.read.parquet(str(silver_dir / "order_items")).count()
    reports.append(
        dict(dataset_name="order_items", input_count=historical_count,
             valid_count=item_count, rejected_count=rejected_count,
             output_count=item_output_count)
    )
    shipment_count = shipments.count()
    shipment_output_count = spark.read.parquet(str(silver_dir / "shipments")).count()
    reports.append(
        dict(dataset_name="shipments", input_count=shipment_count,
             valid_count=shipment_count, rejected_count=0,
             output_count=shipment_output_count)
    )

    checked_at = datetime.now(timezone.utc).replace(tzinfo=None)
    report_rows = [
        (
            report["dataset_name"], report["input_count"], report["valid_count"],
            report["rejected_count"], report["output_count"], checked_at,
        )
        for report in reports
    ]
    report_dataframe = spark.createDataFrame(
        report_rows, schema=DATA_QUALITY_REPORT_SCHEMA
    )
    _write_parquet(report_dataframe, silver_dir / "data_quality_report")

    for dataframe in [products, inventory, pricing, customers, historical, orders,
                      order_items, shipments, rejected_orders]:
        dataframe.unpersist()
    return reports


def main() -> None:
    parser = argparse.ArgumentParser(description="Transform Bronze vendor data to Silver")
    parser.add_argument("--bronze-dir", type=Path, default=DEFAULT_BRONZE_DIR)
    parser.add_argument("--silver-dir", type=Path, default=DEFAULT_SILVER_DIR)
    parser.add_argument("--quarantine-dir", type=Path, default=DEFAULT_QUARANTINE_DIR)
    args = parser.parse_args()

    spark = get_spark_session("vendor-ai-silver-transformations")
    try:
        reports = run_silver_pipeline(
            spark, args.bronze_dir, args.silver_dir, args.quarantine_dir
        )
        for report in reports:
            print(
                "{dataset_name}: input={input_count}, valid={valid_count}, "
                "rejected={rejected_count}, output={output_count}".format(**report)
            )
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
