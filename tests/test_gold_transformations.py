"""Integration tests for Gold transformation logic and row grains."""

from __future__ import annotations

import unittest
from datetime import date, datetime

from pyspark.sql import functions as F

from vendor_ai_assistant.data_pipeline.gold_transformations import (
    SILVER_DATASETS,
    build_gold_datasets,
)
from vendor_ai_assistant.data_pipeline.silver_transformations import DEFAULT_SILVER_DIR
from vendor_ai_assistant.data_pipeline.spark_session import get_spark_session


class GoldTransformationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spark = get_spark_session("vendor-ai-gold-tests")
        cls.silver = {
            name: cls.spark.read.parquet(str(DEFAULT_SILVER_DIR / name)).cache()
            for name in SILVER_DATASETS
        }
        cls.gold = {
            name: dataframe.cache()
            for name, dataframe in build_gold_datasets(
                cls.silver,
                run_date=date(2026, 8, 21),
                pipeline_timestamp=datetime(2026, 8, 21, 0, 0, 0),
            ).items()
        }

    @classmethod
    def tearDownClass(cls) -> None:
        for dataframe in [*cls.silver.values(), *cls.gold.values()]:
            dataframe.unpersist()
        cls.spark.stop()

    def assert_unique(self, dataset: str, keys: list[str]) -> None:
        duplicates = (
            self.gold[dataset].groupBy(*keys).count().filter(F.col("count") > 1).count()
        )
        self.assertEqual(duplicates, 0, f"{dataset} contains duplicate keys")

    def test_dimensions_have_unique_expected_grains(self) -> None:
        self.assertEqual(
            self.gold["dim_products"].count(), self.silver["products"].count()
        )
        self.assertEqual(
            self.gold["dim_buyers"].count(),
            self.silver["customers_retailers"].count(),
        )
        expected_warehouses = self.silver["inventory"].select("warehouse_id").distinct().count()
        self.assertEqual(self.gold["dim_warehouses"].count(), expected_warehouses)
        self.assert_unique("dim_products", ["sku"])
        self.assert_unique("dim_buyers", ["buyer_id"])
        self.assert_unique("dim_warehouses", ["warehouse_id"])

    def test_fact_grains_match_silver(self) -> None:
        mappings = {
            "fact_inventory": "inventory",
            "fact_pricing": "pricing",
            "fact_orders": "orders",
            "fact_order_items": "order_items",
            "fact_shipments": "shipments",
        }
        for gold_name, silver_name in mappings.items():
            with self.subTest(dataset=gold_name):
                self.assertEqual(
                    self.gold[gold_name].count(), self.silver[silver_name].count()
                )
        self.assert_unique("fact_inventory", ["sku", "warehouse_id"])
        self.assert_unique("fact_pricing", ["pricing_id"])
        self.assert_unique("fact_orders", ["order_id"])
        self.assert_unique("fact_order_items", ["order_id", "line_item_number"])
        self.assert_unique("fact_shipments", ["shipment_id"])

    def test_inventory_and_pricing_logic(self) -> None:
        inventory_failures = self.gold["fact_inventory"].filter(
            (F.col("available_quantity") != F.col("quantity_on_hand") - F.col("reserved_quantity"))
            | (F.col("is_low_stock") != (F.col("available_quantity") <= F.col("reorder_level")))
        ).count()
        pricing_failures = self.gold["fact_pricing"].filter(
            (F.abs(
                F.col("net_unit_price_inr")
                - F.round(F.col("base_price_inr") * (1 - F.col("discount_rate")), 2)
            ) > F.lit(0.01))
            | (F.col("valid_from") > F.col("valid_to"))
            | (
                F.col("is_current")
                != (
                    (F.col("status") == "Active")
                    & (F.col("valid_from") <= F.lit(date(2026, 8, 21)))
                    & (F.col("valid_to") >= F.lit(date(2026, 8, 21)))
                )
            )
        ).count()
        self.assertEqual(inventory_failures, 0)
        self.assertEqual(pricing_failures, 0)

    def test_fact_order_totals_are_calculated_from_items(self) -> None:
        item_totals = self.gold["fact_order_items"].groupBy("order_id").agg(
            F.sum("line_total_inr").alias("expected_total")
        )
        failures = self.gold["fact_orders"].join(item_totals, "order_id").filter(
            F.col("order_total_inr") != F.col("expected_total")
        ).count()
        self.assertEqual(failures, 0)

    def test_marts_preserve_driver_grains(self) -> None:
        self.assertEqual(
            self.gold["mart_product_availability"].count(),
            self.gold["fact_inventory"].count(),
        )
        self.assertEqual(
            self.gold["mart_pricing_catalog"].count(),
            self.gold["fact_pricing"].count(),
        )
        self.assertEqual(
            self.gold["mart_order_history"].count(),
            self.gold["fact_order_items"].count(),
        )
        self.assert_unique("mart_product_availability", ["sku", "warehouse_id"])
        self.assert_unique("mart_pricing_catalog", ["pricing_id"])
        self.assert_unique("mart_order_history", ["order_id", "line_item_number"])


if __name__ == "__main__":
    unittest.main()
