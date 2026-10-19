"""Explicit schemas for dimensional, fact, mart, and quality Gold datasets."""

from pyspark.sql.types import (
    BooleanType,
    DateType,
    DecimalType,
    IntegerType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)


GOLD_LINEAGE = [StructField("_gold_processed_at", TimestampType(), False)]
MONEY_18 = DecimalType(18, 2)
MONEY_20 = DecimalType(20, 2)
RATE = DecimalType(9, 4)

DIM_PRODUCTS_SCHEMA = StructType(
    [
        StructField("sku", StringType(), False),
        StructField("product_name", StringType(), False),
        StructField("category", StringType(), False),
        StructField("brand", StringType(), False),
        StructField("pack_size", IntegerType(), False),
        StructField("unit_type", StringType(), False),
        *GOLD_LINEAGE,
    ]
)

DIM_BUYERS_SCHEMA = StructType(
    [
        StructField("buyer_id", StringType(), False),
        StructField("buyer_type", StringType(), False),
        StructField("buyer_name", StringType(), False),
        StructField("city", StringType(), False),
        StructField("state", StringType(), False),
        StructField("retailer_tier", StringType(), False),
        StructField("credit_limit_inr", MONEY_18, False),
        StructField("payment_terms", StringType(), False),
        StructField("discount_group", StringType(), False),
        StructField("status", StringType(), False),
        *GOLD_LINEAGE,
    ]
)

DIM_WAREHOUSES_SCHEMA = StructType(
    [
        StructField("warehouse_id", StringType(), False),
        StructField("warehouse_city", StringType(), False),
        StructField("region", StringType(), False),
        *GOLD_LINEAGE,
    ]
)

FACT_INVENTORY_SCHEMA = StructType(
    [
        StructField("sku", StringType(), False),
        StructField("warehouse_id", StringType(), False),
        StructField("quantity_on_hand", LongType(), False),
        StructField("reserved_quantity", LongType(), False),
        StructField("available_quantity", LongType(), False),
        StructField("reorder_level", LongType(), False),
        StructField("last_updated", TimestampType(), False),
        StructField("is_low_stock", BooleanType(), False),
        *GOLD_LINEAGE,
    ]
)

FACT_PRICING_SCHEMA = StructType(
    [
        StructField("pricing_id", StringType(), False),
        StructField("sku", StringType(), False),
        StructField("buyer_type", StringType(), False),
        StructField("retailer_tier", StringType(), False),
        StructField("minimum_quantity", LongType(), False),
        StructField("maximum_quantity", LongType(), True),
        StructField("quantity_slab", StringType(), False),
        StructField("base_price_inr", MONEY_18, False),
        StructField("discount_rate", RATE, False),
        StructField("net_unit_price_inr", MONEY_18, False),
        StructField("valid_from", DateType(), False),
        StructField("valid_to", DateType(), False),
        StructField("status", StringType(), False),
        StructField("is_current", BooleanType(), False),
        *GOLD_LINEAGE,
    ]
)

FACT_ORDERS_SCHEMA = StructType(
    [
        StructField("order_id", StringType(), False),
        StructField("buyer_id", StringType(), False),
        StructField("buyer_type", StringType(), False),
        StructField("order_date", DateType(), False),
        StructField("order_status", StringType(), False),
        StructField("payment_status", StringType(), False),
        StructField("destination_city", StringType(), False),
        StructField("destination_state", StringType(), False),
        StructField("gross_amount_inr", MONEY_20, False),
        StructField("discount_amount_inr", MONEY_20, False),
        StructField("taxable_amount_inr", MONEY_20, False),
        StructField("tax_amount_inr", MONEY_20, False),
        StructField("order_total_inr", MONEY_20, False),
        StructField("order_year", IntegerType(), False),
        StructField("order_month", IntegerType(), False),
        *GOLD_LINEAGE,
    ]
)

FACT_ORDER_ITEMS_SCHEMA = StructType(
    [
        StructField("order_id", StringType(), False),
        StructField("line_item_number", IntegerType(), False),
        StructField("sku", StringType(), False),
        StructField("quantity", LongType(), False),
        StructField("historical_unit_price_inr", MONEY_18, False),
        StructField("gross_amount_inr", MONEY_20, False),
        StructField("discount_rate", RATE, False),
        StructField("discount_amount_inr", MONEY_20, False),
        StructField("taxable_amount_inr", MONEY_20, False),
        StructField("tax_rate", RATE, False),
        StructField("tax_amount_inr", MONEY_20, False),
        StructField("line_total_inr", MONEY_20, False),
        StructField("order_year", IntegerType(), False),
        StructField("order_month", IntegerType(), False),
        *GOLD_LINEAGE,
    ]
)

FACT_SHIPMENTS_SCHEMA = StructType(
    [
        StructField("shipment_id", StringType(), False),
        StructField("order_id", StringType(), False),
        StructField("warehouse_id", StringType(), False),
        StructField("shipping_method", StringType(), False),
        StructField("carrier", StringType(), False),
        StructField("tracking_number", StringType(), False),
        StructField("shipment_date", DateType(), False),
        StructField("expected_delivery_date", DateType(), False),
        StructField("delivery_date", DateType(), True),
        StructField("destination_city", StringType(), False),
        StructField("destination_state", StringType(), False),
        StructField("order_year", IntegerType(), False),
        StructField("order_month", IntegerType(), False),
        *GOLD_LINEAGE,
    ]
)

MART_PRODUCT_AVAILABILITY_SCHEMA = StructType(
    [
        StructField("sku", StringType(), False),
        StructField("product_name", StringType(), False),
        StructField("category", StringType(), False),
        StructField("brand", StringType(), False),
        StructField("pack_size", IntegerType(), False),
        StructField("unit_type", StringType(), False),
        StructField("warehouse_id", StringType(), False),
        StructField("warehouse_city", StringType(), False),
        StructField("region", StringType(), False),
        StructField("quantity_on_hand", LongType(), False),
        StructField("reserved_quantity", LongType(), False),
        StructField("available_quantity", LongType(), False),
        StructField("reorder_level", LongType(), False),
        StructField("is_low_stock", BooleanType(), False),
        StructField("last_updated", TimestampType(), False),
        *GOLD_LINEAGE,
    ]
)

MART_PRICING_CATALOG_SCHEMA = StructType(
    [
        StructField("pricing_id", StringType(), False),
        StructField("sku", StringType(), False),
        StructField("product_name", StringType(), False),
        StructField("category", StringType(), False),
        StructField("brand", StringType(), False),
        StructField("pack_size", IntegerType(), False),
        StructField("unit_type", StringType(), False),
        StructField("buyer_type", StringType(), False),
        StructField("retailer_tier", StringType(), False),
        StructField("minimum_quantity", LongType(), False),
        StructField("maximum_quantity", LongType(), True),
        StructField("quantity_slab", StringType(), False),
        StructField("base_price_inr", MONEY_18, False),
        StructField("discount_rate", RATE, False),
        StructField("net_unit_price_inr", MONEY_18, False),
        StructField("valid_from", DateType(), False),
        StructField("valid_to", DateType(), False),
        StructField("status", StringType(), False),
        StructField("is_current", BooleanType(), False),
        *GOLD_LINEAGE,
    ]
)

MART_ORDER_HISTORY_SCHEMA = StructType(
    [
        StructField("order_id", StringType(), False),
        StructField("line_item_number", IntegerType(), False),
        StructField("order_date", DateType(), False),
        StructField("order_status", StringType(), False),
        StructField("payment_status", StringType(), False),
        StructField("buyer_id", StringType(), False),
        StructField("buyer_type", StringType(), False),
        StructField("buyer_name", StringType(), False),
        StructField("buyer_city", StringType(), False),
        StructField("buyer_state", StringType(), False),
        StructField("retailer_tier", StringType(), False),
        StructField("sku", StringType(), False),
        StructField("product_name", StringType(), False),
        StructField("category", StringType(), False),
        StructField("brand", StringType(), False),
        StructField("quantity", LongType(), False),
        StructField("historical_unit_price_inr", MONEY_18, False),
        StructField("gross_amount_inr", MONEY_20, False),
        StructField("discount_rate", RATE, False),
        StructField("discount_amount_inr", MONEY_20, False),
        StructField("taxable_amount_inr", MONEY_20, False),
        StructField("tax_rate", RATE, False),
        StructField("tax_amount_inr", MONEY_20, False),
        StructField("line_total_inr", MONEY_20, False),
        StructField("order_total_inr", MONEY_20, False),
        StructField("destination_city", StringType(), False),
        StructField("destination_state", StringType(), False),
        StructField("shipment_count", LongType(), False),
        StructField("warehouse_ids", StringType(), True),
        StructField("carriers", StringType(), True),
        StructField("tracking_numbers", StringType(), True),
        StructField("first_shipment_date", DateType(), True),
        StructField("latest_expected_delivery_date", DateType(), True),
        StructField("latest_delivery_date", DateType(), True),
        StructField("order_year", IntegerType(), False),
        StructField("order_month", IntegerType(), False),
        *GOLD_LINEAGE,
    ]
)

GOLD_QUALITY_REPORT_SCHEMA = StructType(
    [
        StructField("dataset_name", StringType(), False),
        StructField("source_count", LongType(), False),
        StructField("output_count", LongType(), False),
        StructField("duplicate_count", LongType(), False),
        StructField("null_key_count", LongType(), False),
        StructField("foreign_key_failure_count", LongType(), False),
        StructField("reconciliation_failure_count", LongType(), False),
        StructField("reconciliation_results", StringType(), False),
        StructField("checks_passed", BooleanType(), False),
        StructField("pipeline_timestamp", TimestampType(), False),
    ]
)
