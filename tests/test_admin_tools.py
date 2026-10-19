"""Authorization and live read-only tests for the explicit admin tools."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import unittest
from pathlib import Path

from vendor_ai_assistant.tools.registry import execute_tool
from vendor_ai_assistant.tools.results import ACCESS_DENIED_MESSAGE


DB_PATH = Path(__file__).resolve().parents[1] / "data" / "vendor_ai.db"
ADMIN_TOOLS = {
    "admin_search_buyers": {},
    "admin_get_buyer_details": {"buyer_id": "BUYER-PLACEHOLDER"},
    "admin_search_orders": {},
    "admin_get_order_details": {"order_id": "ORDER-PLACEHOLDER"},
    "admin_search_inventory": {},
    "admin_search_pricing": {},
}


class AdminToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        connection = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
        cls.buyer_id = connection.execute(
            "SELECT buyer_id FROM fact_orders GROUP BY buyer_id "
            "ORDER BY COUNT(*) DESC LIMIT 1"
        ).fetchone()[0]
        cls.order_id = connection.execute(
            "SELECT order_id FROM fact_orders WHERE buyer_id=? LIMIT 1",
            (cls.buyer_id,),
        ).fetchone()[0]
        cls.product_id = connection.execute(
            "SELECT product_id FROM fact_inventory LIMIT 1"
        ).fetchone()[0]
        cls.warehouse_city = connection.execute(
            "SELECT warehouse_city FROM dim_warehouses LIMIT 1"
        ).fetchone()[0]
        connection.close()
        cls.admin_context = {
            "authenticated": True,
            "role": "admin",
            "principal_id": "ADMIN-DEMO",
        }
        cls.customer_context = {
            "authenticated": True,
            "role": "customer",
            "buyer_id": cls.buyer_id,
        }
        cls.hash_before = hashlib.sha256(DB_PATH.read_bytes()).hexdigest()

    @classmethod
    def tearDownClass(cls) -> None:
        if hashlib.sha256(DB_PATH.read_bytes()).hexdigest() != cls.hash_before:
            raise AssertionError("Serving database changed during admin tool tests")

    def test_every_admin_tool_rejects_non_admin_roles(self) -> None:
        arguments_by_tool = {
            **ADMIN_TOOLS,
            "admin_get_buyer_details": {"buyer_id": self.buyer_id},
            "admin_get_order_details": {"order_id": self.order_id},
        }
        for tool, arguments in arguments_by_tool.items():
            with self.subTest(tool=tool):
                result = execute_tool(tool, arguments, self.customer_context)
                self.assertEqual(result["status"], "access_denied")
                self.assertEqual(result["message"], ACCESS_DENIED_MESSAGE)
                unauthenticated = execute_tool(tool, arguments, {"role": "admin"})
                self.assertEqual(unauthenticated["status"], "access_denied")

    def test_admin_can_search_and_inspect_any_buyer(self) -> None:
        search = execute_tool(
            "admin_search_buyers",
            {"query": self.buyer_id, "limit": 5},
            self.admin_context,
        )
        self.assertEqual(search["status"], "success")
        self.assertEqual(search["data"][0]["buyer_id"], self.buyer_id)

        details = execute_tool(
            "admin_get_buyer_details",
            {"buyer_id": self.buyer_id},
            self.admin_context,
        )
        self.assertEqual(details["status"], "success")
        self.assertEqual(details["data"][0]["buyer_id"], self.buyer_id)
        self.assertGreater(details["data"][0]["order_summary"]["order_count"], 0)

    def test_admin_can_search_all_orders_and_get_nested_details(self) -> None:
        search = execute_tool(
            "admin_search_orders",
            {"buyer_id": self.buyer_id, "limit": 10},
            self.admin_context,
        )
        self.assertEqual(search["status"], "success")
        self.assertTrue(all(row["buyer_id"] == self.buyer_id for row in search["data"]))

        details = execute_tool(
            "admin_get_order_details",
            {"order_id": self.order_id},
            self.admin_context,
        )
        self.assertEqual(details["status"], "success")
        order = details["data"][0]
        self.assertEqual(order["order_id"], self.order_id)
        self.assertEqual(order["buyer_id"], self.buyer_id)
        self.assertGreater(len(order["items"]), 0)
        self.assertIsInstance(order["shipments"], list)

    def test_admin_can_view_internal_inventory_and_pricing(self) -> None:
        inventory = execute_tool(
            "admin_search_inventory",
            {"query": self.product_id, "warehouse_city": self.warehouse_city},
            self.admin_context,
        )
        self.assertEqual(inventory["status"], "success")
        stock = inventory["data"][0]
        self.assertIn("reserved_quantity", stock)
        self.assertIn("reorder_level", stock)

        pricing = execute_tool(
            "admin_search_pricing",
            {"query": self.product_id, "limit": 10},
            self.admin_context,
        )
        self.assertEqual(pricing["status"], "success")
        self.assertTrue(all(row["product_id"] == self.product_id for row in pricing["data"]))
        self.assertTrue(all("discount_rate" in row for row in pricing["data"]))

    def test_admin_results_are_json_safe_and_do_not_expose_sql(self) -> None:
        results = [
            execute_tool("admin_search_buyers", {"limit": 2}, self.admin_context),
            execute_tool("admin_search_orders", {"limit": 2}, self.admin_context),
            execute_tool("admin_search_inventory", {"limit": 2}, self.admin_context),
            execute_tool("admin_search_pricing", {"limit": 2}, self.admin_context),
        ]
        for result in results:
            encoded = json.dumps(result).lower()
            self.assertNotIn("traceback", encoded)
            self.assertNotIn("vendor_ai.db", encoded)
            self.assertNotIn("select ", encoded)
            self.assertEqual(
                set(result),
                {"status", "data", "message", "missing_fields", "candidates", "metadata"},
            )


if __name__ == "__main__":
    unittest.main()
