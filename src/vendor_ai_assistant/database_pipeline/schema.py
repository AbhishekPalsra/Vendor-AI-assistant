"""Explicit relational schema for the SQLite serving database."""

from __future__ import annotations

import sqlite3
from typing import Final


CREATE_TABLE_STATEMENTS: Final[dict[str, str]] = {
    "dim_products": """
        CREATE TABLE dim_products (
            product_id TEXT PRIMARY KEY,
            product_name TEXT NOT NULL,
            category TEXT NOT NULL,
            brand TEXT NOT NULL,
            pack_size INTEGER NOT NULL CHECK (pack_size > 0),
            unit_type TEXT NOT NULL,
            _gold_processed_at TEXT NOT NULL
        )
    """,
    "dim_buyers": """
        CREATE TABLE dim_buyers (
            buyer_id TEXT PRIMARY KEY,
            buyer_type TEXT NOT NULL,
            buyer_name TEXT NOT NULL,
            city TEXT NOT NULL,
            state TEXT NOT NULL,
            retailer_tier TEXT NOT NULL,
            credit_limit_inr NUMERIC NOT NULL CHECK (credit_limit_inr >= 0),
            payment_terms TEXT NOT NULL,
            discount_group TEXT NOT NULL,
            status TEXT NOT NULL,
            _gold_processed_at TEXT NOT NULL
        )
    """,
    "dim_warehouses": """
        CREATE TABLE dim_warehouses (
            warehouse_id TEXT PRIMARY KEY,
            warehouse_city TEXT NOT NULL,
            region TEXT NOT NULL,
            _gold_processed_at TEXT NOT NULL
        )
    """,
    "fact_inventory": """
        CREATE TABLE fact_inventory (
            product_id TEXT NOT NULL,
            warehouse_id TEXT NOT NULL,
            quantity_on_hand INTEGER NOT NULL CHECK (quantity_on_hand >= 0),
            reserved_quantity INTEGER NOT NULL CHECK (reserved_quantity >= 0),
            available_quantity INTEGER NOT NULL CHECK (available_quantity >= 0),
            reorder_level INTEGER NOT NULL CHECK (reorder_level >= 0),
            last_updated TEXT NOT NULL,
            is_low_stock INTEGER NOT NULL CHECK (is_low_stock IN (0, 1)),
            _gold_processed_at TEXT NOT NULL,
            PRIMARY KEY (product_id, warehouse_id),
            FOREIGN KEY (product_id) REFERENCES dim_products(product_id),
            FOREIGN KEY (warehouse_id) REFERENCES dim_warehouses(warehouse_id),
            CHECK (available_quantity = quantity_on_hand - reserved_quantity)
        )
    """,
    "fact_pricing": """
        CREATE TABLE fact_pricing (
            pricing_id TEXT PRIMARY KEY,
            product_id TEXT NOT NULL,
            buyer_type TEXT NOT NULL,
            retailer_tier TEXT NOT NULL,
            minimum_quantity INTEGER NOT NULL CHECK (minimum_quantity > 0),
            maximum_quantity INTEGER,
            quantity_slab TEXT NOT NULL,
            base_price_inr NUMERIC NOT NULL CHECK (base_price_inr > 0),
            discount_rate NUMERIC NOT NULL CHECK (discount_rate BETWEEN 0 AND 1),
            net_unit_price_inr NUMERIC NOT NULL CHECK (net_unit_price_inr >= 0),
            valid_from TEXT NOT NULL,
            valid_to TEXT NOT NULL,
            status TEXT NOT NULL,
            is_current INTEGER NOT NULL CHECK (is_current IN (0, 1)),
            _gold_processed_at TEXT NOT NULL,
            FOREIGN KEY (product_id) REFERENCES dim_products(product_id),
            CHECK (maximum_quantity IS NULL OR maximum_quantity >= minimum_quantity),
            CHECK (valid_to >= valid_from)
        )
    """,
    "fact_orders": """
        CREATE TABLE fact_orders (
            order_id TEXT PRIMARY KEY,
            buyer_id TEXT NOT NULL,
            warehouse_id TEXT,
            buyer_type TEXT NOT NULL,
            order_date TEXT NOT NULL,
            order_status TEXT NOT NULL,
            payment_status TEXT NOT NULL,
            destination_city TEXT NOT NULL,
            destination_state TEXT NOT NULL,
            gross_amount_inr NUMERIC NOT NULL CHECK (gross_amount_inr >= 0),
            discount_amount_inr NUMERIC NOT NULL CHECK (discount_amount_inr >= 0),
            taxable_amount_inr NUMERIC NOT NULL CHECK (taxable_amount_inr >= 0),
            tax_amount_inr NUMERIC NOT NULL CHECK (tax_amount_inr >= 0),
            order_total_inr NUMERIC NOT NULL CHECK (order_total_inr >= 0),
            order_year INTEGER NOT NULL,
            order_month INTEGER NOT NULL CHECK (order_month BETWEEN 1 AND 12),
            _gold_processed_at TEXT NOT NULL,
            FOREIGN KEY (buyer_id) REFERENCES dim_buyers(buyer_id),
            FOREIGN KEY (warehouse_id) REFERENCES dim_warehouses(warehouse_id)
        )
    """,
    "fact_order_items": """
        CREATE TABLE fact_order_items (
            order_id TEXT NOT NULL,
            line_item_number INTEGER NOT NULL CHECK (line_item_number > 0),
            product_id TEXT NOT NULL,
            quantity INTEGER NOT NULL CHECK (quantity > 0),
            historical_unit_price_inr NUMERIC NOT NULL CHECK (historical_unit_price_inr >= 0),
            gross_amount_inr NUMERIC NOT NULL CHECK (gross_amount_inr >= 0),
            discount_rate NUMERIC NOT NULL CHECK (discount_rate BETWEEN 0 AND 1),
            discount_amount_inr NUMERIC NOT NULL CHECK (discount_amount_inr >= 0),
            taxable_amount_inr NUMERIC NOT NULL CHECK (taxable_amount_inr >= 0),
            tax_rate NUMERIC NOT NULL CHECK (tax_rate BETWEEN 0 AND 1),
            tax_amount_inr NUMERIC NOT NULL CHECK (tax_amount_inr >= 0),
            line_total_inr NUMERIC NOT NULL CHECK (line_total_inr >= 0),
            order_year INTEGER NOT NULL,
            order_month INTEGER NOT NULL CHECK (order_month BETWEEN 1 AND 12),
            _gold_processed_at TEXT NOT NULL,
            PRIMARY KEY (order_id, line_item_number),
            FOREIGN KEY (order_id) REFERENCES fact_orders(order_id),
            FOREIGN KEY (product_id) REFERENCES dim_products(product_id)
        )
    """,
    "fact_shipments": """
        CREATE TABLE fact_shipments (
            shipment_id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL,
            warehouse_id TEXT NOT NULL,
            shipping_method TEXT NOT NULL,
            carrier TEXT NOT NULL,
            tracking_number TEXT NOT NULL,
            shipment_date TEXT NOT NULL,
            expected_delivery_date TEXT NOT NULL,
            delivery_date TEXT,
            destination_city TEXT NOT NULL,
            destination_state TEXT NOT NULL,
            order_year INTEGER NOT NULL,
            order_month INTEGER NOT NULL CHECK (order_month BETWEEN 1 AND 12),
            _gold_processed_at TEXT NOT NULL,
            FOREIGN KEY (order_id) REFERENCES fact_orders(order_id),
            FOREIGN KEY (warehouse_id) REFERENCES dim_warehouses(warehouse_id),
            CHECK (expected_delivery_date >= shipment_date),
            CHECK (delivery_date IS NULL OR delivery_date >= shipment_date)
        )
    """,
    "mart_product_availability": """
        CREATE TABLE mart_product_availability (
            product_id TEXT NOT NULL,
            product_name TEXT NOT NULL,
            category TEXT NOT NULL,
            brand TEXT NOT NULL,
            pack_size INTEGER NOT NULL,
            unit_type TEXT NOT NULL,
            warehouse_id TEXT NOT NULL,
            warehouse_city TEXT NOT NULL,
            region TEXT NOT NULL,
            quantity_on_hand INTEGER NOT NULL,
            reserved_quantity INTEGER NOT NULL,
            available_quantity INTEGER NOT NULL,
            reorder_level INTEGER NOT NULL,
            is_low_stock INTEGER NOT NULL CHECK (is_low_stock IN (0, 1)),
            last_updated TEXT NOT NULL,
            _gold_processed_at TEXT NOT NULL,
            PRIMARY KEY (product_id, warehouse_id),
            FOREIGN KEY (product_id) REFERENCES dim_products(product_id),
            FOREIGN KEY (warehouse_id) REFERENCES dim_warehouses(warehouse_id),
            CHECK (available_quantity = quantity_on_hand - reserved_quantity)
        )
    """,
    "mart_pricing_catalog": """
        CREATE TABLE mart_pricing_catalog (
            pricing_id TEXT PRIMARY KEY,
            product_id TEXT NOT NULL,
            product_name TEXT NOT NULL,
            category TEXT NOT NULL,
            brand TEXT NOT NULL,
            pack_size INTEGER NOT NULL,
            unit_type TEXT NOT NULL,
            buyer_type TEXT NOT NULL,
            retailer_tier TEXT NOT NULL,
            minimum_quantity INTEGER NOT NULL,
            maximum_quantity INTEGER,
            quantity_slab TEXT NOT NULL,
            base_price_inr NUMERIC NOT NULL,
            discount_rate NUMERIC NOT NULL,
            net_unit_price_inr NUMERIC NOT NULL,
            valid_from TEXT NOT NULL,
            valid_to TEXT NOT NULL,
            status TEXT NOT NULL,
            is_current INTEGER NOT NULL CHECK (is_current IN (0, 1)),
            _gold_processed_at TEXT NOT NULL,
            FOREIGN KEY (product_id) REFERENCES dim_products(product_id),
            CHECK (valid_to >= valid_from)
        )
    """,
    "mart_order_history": """
        CREATE TABLE mart_order_history (
            order_id TEXT NOT NULL,
            line_item_number INTEGER NOT NULL,
            order_date TEXT NOT NULL,
            order_status TEXT NOT NULL,
            payment_status TEXT NOT NULL,
            buyer_id TEXT NOT NULL,
            buyer_type TEXT NOT NULL,
            buyer_name TEXT NOT NULL,
            buyer_city TEXT NOT NULL,
            buyer_state TEXT NOT NULL,
            retailer_tier TEXT NOT NULL,
            product_id TEXT NOT NULL,
            product_name TEXT NOT NULL,
            category TEXT NOT NULL,
            brand TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            historical_unit_price_inr NUMERIC NOT NULL,
            gross_amount_inr NUMERIC NOT NULL,
            discount_rate NUMERIC NOT NULL,
            discount_amount_inr NUMERIC NOT NULL,
            taxable_amount_inr NUMERIC NOT NULL,
            tax_rate NUMERIC NOT NULL,
            tax_amount_inr NUMERIC NOT NULL,
            line_total_inr NUMERIC NOT NULL,
            order_total_inr NUMERIC NOT NULL,
            destination_city TEXT NOT NULL,
            destination_state TEXT NOT NULL,
            shipment_count INTEGER NOT NULL CHECK (shipment_count >= 0),
            warehouse_ids TEXT,
            carriers TEXT,
            tracking_numbers TEXT,
            first_shipment_date TEXT,
            latest_expected_delivery_date TEXT,
            latest_delivery_date TEXT,
            order_year INTEGER NOT NULL,
            order_month INTEGER NOT NULL CHECK (order_month BETWEEN 1 AND 12),
            _gold_processed_at TEXT NOT NULL,
            PRIMARY KEY (order_id, line_item_number),
            FOREIGN KEY (order_id) REFERENCES fact_orders(order_id),
            FOREIGN KEY (buyer_id) REFERENCES dim_buyers(buyer_id),
            FOREIGN KEY (product_id) REFERENCES dim_products(product_id)
        )
    """,
    "gold_quality_report": """
        CREATE TABLE gold_quality_report (
            dataset_name TEXT PRIMARY KEY,
            source_count INTEGER NOT NULL,
            output_count INTEGER NOT NULL,
            duplicate_count INTEGER NOT NULL,
            null_key_count INTEGER NOT NULL,
            foreign_key_failure_count INTEGER NOT NULL,
            reconciliation_failure_count INTEGER NOT NULL,
            reconciliation_results TEXT NOT NULL,
            checks_passed INTEGER NOT NULL CHECK (checks_passed IN (0, 1)),
            pipeline_timestamp TEXT NOT NULL
        )
    """,
}

LOAD_ORDER: Final[tuple[str, ...]] = tuple(CREATE_TABLE_STATEMENTS)

CREATE_INDEX_STATEMENTS: Final[tuple[str, ...]] = (
    "CREATE INDEX idx_inventory_warehouse ON fact_inventory(warehouse_id)",
    "CREATE INDEX idx_pricing_product ON fact_pricing(product_id)",
    "CREATE INDEX idx_orders_buyer_date ON fact_orders(buyer_id, order_date)",
    "CREATE INDEX idx_order_items_product ON fact_order_items(product_id)",
    "CREATE INDEX idx_shipments_order ON fact_shipments(order_id)",
    "CREATE INDEX idx_shipments_warehouse ON fact_shipments(warehouse_id)",
    "CREATE INDEX idx_availability_location ON mart_product_availability(warehouse_id)",
    "CREATE INDEX idx_pricing_catalog_product ON mart_pricing_catalog(product_id)",
    "CREATE INDEX idx_order_history_buyer ON mart_order_history(buyer_id, order_date)",
    "CREATE INDEX idx_order_history_product ON mart_order_history(product_id, order_date)",
)

CREATE_SEARCH_INDEX_STATEMENTS: Final[tuple[str, ...]] = (
    """
    CREATE VIRTUAL TABLE product_search_fts USING fts5(
        product_id UNINDEXED,
        product_name,
        brand,
        category,
        pack_text
    )
    """,
)


def create_schema(connection: sqlite3.Connection) -> None:
    """Create all serving tables and indexes on an empty SQLite database."""
    for statement in CREATE_TABLE_STATEMENTS.values():
        connection.execute(statement)
    for statement in CREATE_INDEX_STATEMENTS:
        connection.execute(statement)
    for statement in CREATE_SEARCH_INDEX_STATEMENTS:
        connection.execute(statement)
    connection.commit()


def populate_search_indexes(connection: sqlite3.Connection) -> None:
    """Rebuild derived search indexes from authoritative serving tables."""

    connection.execute("DELETE FROM product_search_fts")
    connection.execute(
        """
        INSERT INTO product_search_fts(
            product_id, product_name, brand, category, pack_text
        )
        SELECT
            product_id,
            product_name,
            brand,
            category,
            CAST(pack_size AS TEXT) || ' ' || unit_type
        FROM dim_products
        """
    )
    connection.commit()
