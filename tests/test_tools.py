"""Security, definition, handler, and live SQLite tests for retrieval tools."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import unittest
from pathlib import Path

from vendor_ai_assistant.tools.database import read_only_connection
from vendor_ai_assistant.tools.loader import load_tool_definitions
from vendor_ai_assistant.tools.registry import (
    HANDLERS,
    execute_tool,
    get_registered_tool_names,
)
from vendor_ai_assistant.tools.results import ACCESS_DENIED_MESSAGE


DB_PATH = Path(__file__).resolve().parents[1] / "data" / "vendor_ai.db"


class ToolDefinitionTests(unittest.TestCase):
    def test_all_definitions_match_handlers(self) -> None:
        definitions = load_tool_definitions()
        names = {definition["function"]["name"] for definition in definitions}
        self.assertEqual(len(definitions), 14)
        self.assertEqual(names, set(HANDLERS))
        self.assertEqual(names, set(get_registered_tool_names()))
        for definition in definitions:
            parameters = definition["function"]["parameters"]
            self.assertEqual(parameters["type"], "object")
            self.assertIs(parameters["additionalProperties"], False)

    def test_no_internal_analytics_or_authentication_arguments_exist(self) -> None:
        names = set(get_registered_tool_names())
        forbidden_names = {"sales", "revenue", "margin", "profit", "ranking", "analytics"}
        self.assertFalse(any(word in name for name in names for word in forbidden_names))
        forbidden_arguments = {
            "buyer_id", "authenticated", "is_authenticated", "retailer_tier",
            "credit_limit", "raw_sql", "sql",
        }
        for definition in load_tool_definitions():
            name = definition["function"]["name"]
            properties = set(definition["function"]["parameters"]["properties"])
            if name.startswith("admin_"):
                self.assertTrue(
                    properties.isdisjoint(
                        {"authenticated", "is_authenticated", "raw_sql", "sql"}
                    )
                )
            else:
                self.assertTrue(properties.isdisjoint(forbidden_arguments))


class ToolHandlerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        connection = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
        cls.customer_id = connection.execute(
            "SELECT buyer_id FROM dim_buyers "
            "WHERE buyer_type='Customer' AND status='Active' LIMIT 1"
        ).fetchone()[0]
        cls.retailer_id, cls.retailer_tier = connection.execute(
            "SELECT buyer_id, retailer_tier FROM dim_buyers "
            "WHERE buyer_type='Retailer' AND status='Active' LIMIT 1"
        ).fetchone()
        cls.public_sku = connection.execute(
            "SELECT product_id FROM fact_pricing WHERE buyer_type='Customer' "
            "AND retailer_tier='Not Applicable' AND minimum_quantity<=1 "
            "AND (maximum_quantity IS NULL OR maximum_quantity>=1) LIMIT 1"
        ).fetchone()[0]
        cls.retailer_sku = connection.execute(
            "SELECT product_id FROM fact_pricing WHERE buyer_type='Retailer' "
            "AND retailer_tier=? AND minimum_quantity<=50 "
            "AND (maximum_quantity IS NULL OR maximum_quantity>=50) LIMIT 1",
            (cls.retailer_tier,),
        ).fetchone()[0]
        cls.owned_order = connection.execute(
            "SELECT order_id FROM fact_orders WHERE buyer_id=? LIMIT 1",
            (cls.customer_id,),
        ).fetchone()[0]
        cls.other_order, cls.other_buyer = connection.execute(
            "SELECT order_id, buyer_id FROM fact_orders WHERE buyer_id<>? LIMIT 1",
            (cls.customer_id,),
        ).fetchone()
        cls.multi_order, cls.multi_buyer = connection.execute(
            "SELECT s.order_id, o.buyer_id FROM fact_shipments s "
            "JOIN fact_orders o ON o.order_id=s.order_id "
            "GROUP BY s.order_id HAVING COUNT(1)>1 LIMIT 1"
        ).fetchone()
        cls.delivered_buyer = connection.execute(
            "SELECT buyer_id FROM fact_orders WHERE order_status='Delivered' LIMIT 1"
        ).fetchone()[0]
        connection.close()
        cls.hash_before = hashlib.sha256(DB_PATH.read_bytes()).hexdigest()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.hash_after = hashlib.sha256(DB_PATH.read_bytes()).hexdigest()
        if cls.hash_before != cls.hash_after:
            raise AssertionError("Serving database changed during read-only tool tests")

    def test_missing_inputs_are_not_guessed(self) -> None:
        self.assertEqual(execute_tool("search_products", {})["status"], "needs_clarification")
        self.assertEqual(
            execute_tool("get_product_details", {})["status"], "needs_clarification"
        )
        quote = execute_tool("get_price_quote", {"sku": self.public_sku})
        self.assertEqual(quote["status"], "needs_clarification")
        self.assertIn("quantity", quote["missing_fields"])
        status = execute_tool(
            "get_order_status", {}, {"authenticated": True, "buyer_id": self.customer_id}
        )
        self.assertEqual(status["status"], "needs_clarification")

    def test_ambiguous_products_return_candidates(self) -> None:
        result = execute_tool("search_products", {"query": "Rice", "limit": 10})
        self.assertEqual(result["status"], "ambiguous")
        self.assertGreater(len(result["candidates"]), 1)
        self.assertTrue(all("sku" in item for item in result["candidates"]))

    def test_missing_location_returns_needs_clarification(self) -> None:
        result = execute_tool("search_available_products", {"query": self.public_sku})
        self.assertEqual(result["status"], "needs_clarification")
        self.assertIn("warehouse_city", result["missing_fields"])

    def test_retailer_tier_comes_only_from_authenticated_account(self) -> None:
        context = {"authenticated": True, "buyer_id": self.retailer_id}
        result = execute_tool(
            "get_price_quote", {"sku": self.retailer_sku, "quantity": 50}, context
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"][0]["retailer_tier"], self.retailer_tier)
        rejected = execute_tool(
            "get_price_quote",
            {"sku": self.retailer_sku, "quantity": 50, "retailer_tier": "Gold"},
            context,
        )
        self.assertEqual(rejected["status"], "invalid_request")

    def test_unauthenticated_price_is_standard_customer_price(self) -> None:
        result = execute_tool(
            "get_price_quote", {"sku": self.public_sku, "quantity": 1}
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"][0]["buyer_type"], "Customer")
        self.assertEqual(result["data"][0]["retailer_tier"], "Not Applicable")

    def test_protected_tools_require_authentication(self) -> None:
        calls = {
            "get_my_account": {},
            "get_order_status": {"order_id": self.owned_order},
            "get_order_history": {},
            "get_repurchase_suggestions": {},
        }
        for name, arguments in calls.items():
            with self.subTest(tool=name):
                self.assertEqual(
                    execute_tool(name, arguments)["status"], "authentication_required"
                )

    def test_cross_account_access_is_denied_without_record_disclosure(self) -> None:
        context = {"authenticated": True, "buyer_id": self.customer_id}
        other = execute_tool("get_order_status", {"order_id": self.other_order}, context)
        absent = execute_tool("get_order_status", {"order_id": "ORDER-DOES-NOT-EXIST"}, context)
        self.assertEqual(other["status"], "access_denied")
        self.assertEqual(other["message"], ACCESS_DENIED_MESSAGE)
        self.assertEqual((other["status"], other["message"]), (absent["status"], absent["message"]))
        for tool in ("get_my_account", "get_order_history", "get_repurchase_suggestions"):
            result = execute_tool(tool, {"buyer_id": self.other_buyer}, context)
            self.assertEqual(result["status"], "invalid_request")

    def test_multiple_shipments_do_not_duplicate_order(self) -> None:
        result = execute_tool(
            "get_order_status",
            {"order_id": self.multi_order},
            {"authenticated": True, "buyer_id": self.multi_buyer},
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["data"]), 1)
        self.assertGreater(len(result["data"][0]["shipments"]), 1)

    def test_history_and_suggestions_are_scoped_to_authenticated_buyer(self) -> None:
        context = {"authenticated": True, "buyer_id": self.delivered_buyer}
        history = execute_tool("get_order_history", {"limit": 10}, context)
        suggestions = execute_tool("get_repurchase_suggestions", {"limit": 10}, context)
        self.assertIn(history["status"], {"success", "no_results"})
        self.assertIn(suggestions["status"], {"success", "no_results"})
        if suggestions["status"] == "success":
            with read_only_connection() as connection:
                allowed = {
                    row[0]
                    for row in connection.execute(
                        "SELECT DISTINCT product_id FROM mart_order_history "
                        "WHERE buyer_id=? AND order_status='Delivered'",
                        (self.delivered_buyer,),
                    )
                }
            self.assertTrue({item["sku"] for item in suggestions["data"]}.issubset(allowed))

    def test_handlers_are_read_only(self) -> None:
        with read_only_connection() as connection:
            self.assertEqual(connection.execute("PRAGMA query_only").fetchone()[0], 1)
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("DELETE FROM dim_products")

    def test_results_are_json_serializable_and_hide_internals(self) -> None:
        context = {"authenticated": True, "buyer_id": self.customer_id}
        results = [
            execute_tool("search_products", {"query": "Rice", "limit": 2}),
            execute_tool("get_product_details", {"sku": self.public_sku}),
            execute_tool("get_price_quote", {"sku": self.public_sku, "quantity": 1}),
            execute_tool("get_my_account", {}, context),
            execute_tool("get_order_status", {"order_id": self.owned_order}, context),
            execute_tool("get_order_history", {"limit": 2}, context),
        ]
        for result in results:
            encoded = json.dumps(result).lower()
            self.assertNotIn("traceback", encoded)
            self.assertNotIn(" select * from ", encoded)
            self.assertNotIn(" from dim_", encoded)
            self.assertNotIn(" from fact_", encoded)
            self.assertNotIn(" from mart_", encoded)
            self.assertNotIn("vendor_ai.db", encoded)
            self.assertEqual(
                set(result),
                {"status", "data", "message", "missing_fields", "candidates", "metadata"},
            )


if __name__ == "__main__":
    unittest.main()
