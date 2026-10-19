"""Network-free integration tests for natural product and location resolution."""

from __future__ import annotations

import time
import tempfile
import unittest
from pathlib import Path

from vendor_ai_assistant.chat.models import ChatSession, PlannedToolCall, QueryPlan
from vendor_ai_assistant.chat.orchestrator import orchestrate_turn
from vendor_ai_assistant.chat.query_processor import resolve_planned_tool_calls
from vendor_ai_assistant.database_pipeline.schema import (
    create_schema,
    populate_search_indexes,
)
from vendor_ai_assistant.database_pipeline.sqlite_connection import (
    get_sqlite_connection,
)
from vendor_ai_assistant.tools.product_resolver import (
    resolve_location_query,
    resolve_product_query,
)


class ProductResolverTests(unittest.TestCase):
    def test_natural_product_variations_resolve_from_live_catalogue(self) -> None:
        expected = {
            "fortune rice oil": "SKU-00073",
            "fortun rice oil": "SKU-00073",
            "fortune basmati": "SKU-00001",
            "one kilo fortune basmati rice": "SKU-00001",
        }
        for query, sku in expected.items():
            with self.subTest(query=query):
                resolution = resolve_product_query(query)
                self.assertEqual(resolution.status, "resolved")
                self.assertEqual(resolution.match.sku, sku)

    def test_broad_product_phrase_returns_real_candidates(self) -> None:
        resolution = resolve_product_query("fortune oil")
        self.assertEqual(resolution.status, "ambiguous")
        self.assertEqual(len(resolution.candidates), 5)
        self.assertTrue(
            all(candidate.brand == "Fortune" for candidate in resolution.candidates)
        )

    def test_misspelled_brand_and_product_return_only_close_matches(self) -> None:
        resolution = resolve_product_query("ashirwad aata")
        self.assertEqual(resolution.status, "ambiguous")
        self.assertEqual(
            {candidate.sku for candidate in resolution.candidates},
            {"SKU-00021", "SKU-00025"},
        )

    def test_location_variations_resolve_against_live_warehouses(self) -> None:
        for query in ("Jaipur region", "banglore", "Bangalore", "Bengaluru", "blr"):
            with self.subTest(query=query):
                resolution = resolve_location_query(query)
                self.assertEqual(resolution.status, "resolved")
        self.assertEqual(
            resolve_location_query("banglore").match.warehouse_city,
            "Bengaluru",
        )

    def test_price_and_location_plan_becomes_concrete_calls(self) -> None:
        plan = QueryPlan(
            route="database",
            original_query=(
                "whats the price of 21 units of fortune rice oil in jaipur region"
            ),
            rewritten_query=(
                "Find the retailer price and availability for 21 units of "
                "Fortune rice oil in Jaipur."
            ),
            tool_calls=(
                PlannedToolCall(
                    name="get_price_quote",
                    arguments={"product_name": "fortune rice oil", "quantity": 21},
                    purpose="Retrieve the account price",
                ),
                PlannedToolCall(
                    name="search_available_products",
                    arguments={
                        "query": "fortune rice oil",
                        "warehouse_city": "Jaipur region",
                        "in_stock_only": True,
                    },
                    purpose="Check local availability",
                ),
            ),
        )
        resolved = resolve_planned_tool_calls(plan)
        self.assertEqual(
            resolved.tool_calls[0].argument_values()["sku"], "SKU-00073"
        )
        self.assertEqual(
            resolved.tool_calls[1].argument_values()["query"], "SKU-00073"
        )
        self.assertEqual(
            resolved.tool_calls[1].argument_values()["warehouse_city"], "Jaipur"
        )

    def test_planned_calls_execute_without_tool_model(self) -> None:
        session = ChatSession(
            role="retailer",
            principal_id="RET-00004",
            buyer_id="RET-00004",
        ).add_message(
            "user", "whats the price of 21 units of fortune rice oil in jaipur region"
        )
        unresolved = QueryPlan(
            route="database",
            original_query=session.current_message.content,
            rewritten_query="Price and availability for 21 Fortune rice oils in Jaipur",
            tool_calls=(
                PlannedToolCall(
                    name="get_price_quote",
                    arguments={"product_name": "fortune rice oil", "quantity": 21},
                    purpose="price",
                ),
                PlannedToolCall(
                    name="search_available_products",
                    arguments={"query": "fortune rice oil", "warehouse_city": "Jaipur"},
                    purpose="stock",
                ),
            ),
        )
        plan = resolve_planned_tool_calls(unresolved)
        result = orchestrate_turn(session, query_processor=lambda _: plan)
        self.assertEqual(result.status, "ready_for_answer")
        self.assertEqual(result.tool_loop_result.stop_reason, "planned_calls_completed")
        self.assertEqual(
            [execution.result["status"] for execution in result.evidence.database],
            ["success", "success"],
        )
        quote = result.evidence.database[0].result["data"][0]
        stock = result.evidence.database[1].result["data"][0]
        self.assertEqual(quote["sku"], "SKU-00073")
        self.assertEqual(quote["quantity"], 21)
        self.assertEqual(stock["warehouse_city"], "Jaipur")

    def test_local_resolution_is_fast(self) -> None:
        started = time.perf_counter()
        for query in (
            "fortune rice oil",
            "fortun rice oil",
            "fortune basmati",
            "fortune oil",
        ):
            resolve_product_query(query)
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 1.0)

    def test_rebuilt_database_uses_populated_fts_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "serving.db"
            connection = get_sqlite_connection(database_path)
            create_schema(connection)
            connection.execute(
                "INSERT INTO dim_products VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    "SKU-TEST",
                    "Fortune Rice Bran Oil 500 ml",
                    "Edible Oils",
                    "Fortune",
                    500,
                    "ml",
                    "2026-08-27 00:00:00",
                ),
            )
            populate_search_indexes(connection)
            count = connection.execute(
                "SELECT COUNT(*) FROM product_search_fts"
            ).fetchone()[0]
            connection.close()

            resolution = resolve_product_query(
                "fortune rice oil", database_path=database_path
            )
            self.assertEqual(count, 1)
            self.assertEqual(resolution.status, "resolved")
            self.assertEqual(resolution.match.sku, "SKU-TEST")


if __name__ == "__main__":
    unittest.main()
