"""Explicit schemas for curated Silver datasets."""

from pyspark.sql.types import (
    DateType,
    DecimalType,
    IntegerType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)


LINEAGE_FIELDS = [
    StructField("_source_file", StringType(), False),
    StructField("_ingested_at", TimestampType(), False),
    StructField("_silver_processed_at", TimestampType(), False),
]

PRODUCT_SCHEMA = StructType(
    [
        StructField("sku", StringType(), False),
        StructField("product_name", StringType(), False),
        StructField("category", StringType(), False),
        StructField("brand", StringType(), False),
        StructField("pack_size", IntegerType(), False),
        StructField("unit_type", StringType(), False),
        *LINEAGE_FIELDS,
    ]
)

INVENTORY_SCHEMA = StructType(
    [
        StructField("sku", StringType(), False),
        StructField("warehouse_id", StringType(), False),
        StructField("warehouse_name", StringType(), False),
        StructField("quantity_on_hand", LongType(), False),
        StructField("reserved_quantity", LongType(), False),
        StructField("available_quantity", LongType(), False),
        StructField("reorder_level", LongType(), False),
        StructField("last_updated", TimestampType(), False),
        *LINEAGE_FIELDS,
    ]
)

PRICING_SCHEMA = StructType(
    [
        StructField("pricing_id", StringType(), False),
        StructField("sku", StringType(), False),
        StructField("customer_type", StringType(), False),
        StructField("retailer_tier", StringType(), False),
        StructField("minimum_quantity", LongType(), False),
        StructField("maximum_quantity", LongType(), True),
        StructField("quantity_slab", StringType(), False),
        StructField("base_price_inr", DecimalType(18, 2), False),
        StructField("discount_rate", DecimalType(9, 4), False),
        StructField("net_unit_price_inr", DecimalType(18, 2), False),
        StructField("discount_rule", StringType(), False),
        StructField("valid_from", DateType(), False),
        StructField("valid_to", DateType(), False),
        StructField("status", StringType(), False),
        *LINEAGE_FIELDS,
    ]
)

CUSTOMER_SCHEMA = StructType(
    [
        StructField("buyer_id", StringType(), False),
        StructField("buyer_type", StringType(), False),
        StructField("buyer_name", StringType(), False),
        StructField("city", StringType(), False),
        StructField("state", StringType(), False),
        StructField("phone", StringType(), False),
        StructField("email", StringType(), False),
        StructField("retailer_tier", StringType(), False),
        StructField("credit_limit_inr", DecimalType(18, 2), False),
        StructField("payment_terms", StringType(), False),
        StructField("discount_group", StringType(), False),
        StructField("status", StringType(), False),
        *LINEAGE_FIELDS,
    ]
)

ORDER_SCHEMA = StructType(
    [
        StructField("order_id", StringType(), False),
        StructField("buyer_id", StringType(), False),
        StructField("buyer_type", StringType(), False),
        StructField("order_date", DateType(), False),
        StructField("order_status", StringType(), False),
        StructField("payment_status", StringType(), False),
        StructField("ship_city", StringType(), False),
        StructField("ship_state", StringType(), False),
        StructField("gross_amount_inr", DecimalType(20, 2), False),
        StructField("discount_amount_inr", DecimalType(20, 2), False),
        StructField("taxable_amount_inr", DecimalType(20, 2), False),
        StructField("tax_amount_inr", DecimalType(20, 2), False),
        StructField("order_total_inr", DecimalType(20, 2), False),
        StructField("order_year", IntegerType(), False),
        StructField("order_month", IntegerType(), False),
        *LINEAGE_FIELDS,
    ]
)

ORDER_ITEM_SCHEMA = StructType(
    [
        StructField("order_id", StringType(), False),
        StructField("line_item_number", IntegerType(), False),
        StructField("sku", StringType(), False),
        StructField("product_name", StringType(), False),
        StructField("quantity", LongType(), False),
        StructField("historical_unit_price_inr", DecimalType(18, 2), False),
        StructField("gross_amount_inr", DecimalType(20, 2), False),
        StructField("discount_rate", DecimalType(9, 4), False),
        StructField("discount_amount_inr", DecimalType(20, 2), False),
        StructField("taxable_amount_inr", DecimalType(20, 2), False),
        StructField("tax_rate", DecimalType(9, 4), False),
        StructField("tax_amount_inr", DecimalType(20, 2), False),
        StructField("line_total_inr", DecimalType(20, 2), False),
        StructField("order_year", IntegerType(), False),
        StructField("order_month", IntegerType(), False),
        *LINEAGE_FIELDS,
    ]
)

SHIPMENT_SCHEMA = StructType(
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
        StructField("ship_city", StringType(), False),
        StructField("ship_state", StringType(), False),
        StructField("order_year", IntegerType(), False),
        StructField("order_month", IntegerType(), False),
        *LINEAGE_FIELDS,
    ]
)

DATA_QUALITY_REPORT_SCHEMA = StructType(
    [
        StructField("dataset_name", StringType(), False),
        StructField("input_count", LongType(), False),
        StructField("valid_count", LongType(), False),
        StructField("rejected_count", LongType(), False),
        StructField("output_count", LongType(), False),
        StructField("checked_at", TimestampType(), False),
    ]
)
