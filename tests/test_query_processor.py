"""Focused, network-free tests for query rewriting and evidence routing."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from vendor_ai_assistant.chat.models import ChatSession, QueryPlan
from vendor_ai_assistant.chat.query_processor import (
    QUERY_PROCESSING_MODEL,
    build_rag_catalogue,
    build_tool_catalogue,
    make_query_messages,
    process_query,
)


class QueryProcessorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.knowledge_base = Path(self.temp_dir.name)
        policies = self.knowledge_base / "policies"
        operations = self.knowledge_base / "operations"
        policies.mkdir()
        operations.mkdir()
        (policies / "returns.md").write_text(
            "# Return Policy\n\nRules for damaged products and return windows.",
            encoding="utf-8",
        )
        (operations / "warehouses.md").write_text(
            "# Warehouse Operations\n\nGeneral warehouse operating guidance.",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @staticmethod
    def session() -> ChatSession:
        session = ChatSession(
            role="customer",
            principal_id="CUS-001",
            buyer_id="CUS-001",
        )
        session = session.add_message("user", "Show me Amul milk products")
        session = session.add_message("assistant", "I found several products.")
        return session.add_message(
            "user",
            "Which are available in Jaipur and can damaged ones be returned?",
        )

    def test_catalogues_come_from_live_files_and_role_tools(self) -> None:
        rag = build_rag_catalogue(self.knowledge_base)
        customer_tools = build_tool_catalogue("customer")
        admin_tools = build_tool_catalogue("admin")

        self.assertEqual(len(rag), 2)
        self.assertEqual(rag[1]["source_path"], "policies/returns.md")
        self.assertEqual(rag[1]["title"], "Return Policy")
        self.assertIn(
            "search_available_products",
            {item["name"] for item in customer_tools},
        )
        self.assertNotIn(
            "admin_search_orders",
            {item["name"] for item in customer_tools},
        )
        self.assertIn(
            "admin_search_orders",
            {item["name"] for item in admin_tools},
        )

    def test_planned_arguments_use_openai_compatible_string_schema(self) -> None:
        schema = QueryPlan.model_json_schema()
        arguments = schema["$defs"]["PlannedToolCall"]["properties"]["arguments"]
        self.assertEqual(arguments["type"], "string")

    def test_prompt_uses_current_message_history_role_and_catalogues(self) -> None:
        messages = make_query_messages(
            self.session(),
            history_limit=2,
            knowledge_base_path=self.knowledge_base,
        )
        payload = json.loads(messages[1]["content"])

        self.assertEqual(payload["session_role"], "customer")
        self.assertEqual(len(payload["recent_history"]), 2)
        self.assertEqual(
            payload["current_message"],
            "Which are available in Jaipur and can damaged ones be returned?",
        )
        self.assertNotIn("buyer_id", payload)
        self.assertTrue(payload["available_database_tools"])
        self.assertEqual(len(payload["rag_knowledge_catalogue"]), 2)

    def test_hybrid_plan_preserves_full_intent_and_routes_each_part(self) -> None:
        calls = []

        def fake_completion(**kwargs):
            calls.append(kwargs)
            return {
                "choices": [
                    {
                        "message": {
                            "parsed": {
                                "route": "hybrid",
                                "original_query": "model echo is not trusted",
                                "rewritten_query": (
                                    "Which previously discussed Amul milk products are "
                                    "currently available in Jaipur, and can any damaged "
                                    "products be returned under the return policy?"
                                ),
                                "rag_requests": [
                                    {
                                        "query": "Return rules for damaged Amul milk products",
                                        "purpose": "Determine whether damaged products qualify",
                                        "source_paths": ["policies/returns.md"],
                                    }
                                ],
                                "database_requests": [
                                    {
                                        "query": (
                                            "Current availability in Jaipur for the Amul "
                                            "milk products discussed in the conversation"
                                        ),
                                        "purpose": "Find currently available matching products",
                                        "tool_names": ["search_available_products"],
                                    }
                                ],
                                "clarification_question": None,
                            }
                        }
                    }
                ]
            }

        plan = process_query(
            self.session(),
            knowledge_base_path=self.knowledge_base,
            completion_fn=fake_completion,
        )

        self.assertEqual(plan.route, "hybrid")
        self.assertIn("Amul milk", plan.rewritten_query)
        self.assertIn("Jaipur", plan.rewritten_query)
        self.assertIn("damaged", plan.rewritten_query)
        self.assertEqual(
            plan.original_query,
            "Which are available in Jaipur and can damaged ones be returned?",
        )
        self.assertEqual(calls[0]["model"], QUERY_PROCESSING_MODEL)
        self.assertEqual(calls[0]["response_format"].__name__, "QueryPlan")

    def test_unavailable_tool_reference_is_rejected(self) -> None:
        def fake_completion(**kwargs):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "route": "database",
                                    "original_query": "Show every buyer",
                                    "rewritten_query": "Show every buyer account",
                                    "rag_requests": [],
                                    "database_requests": [
                                        {
                                            "query": "Search all buyer accounts",
                                            "purpose": "Access cross-account data",
                                            "tool_names": ["admin_search_buyers"],
                                        }
                                    ],
                                    "clarification_question": None,
                                }
                            )
                        }
                    }
                ]
            }

        with self.assertRaisesRegex(ValueError, "unavailable tool"):
            process_query(
                self.session(),
                knowledge_base_path=self.knowledge_base,
                completion_fn=fake_completion,
            )

    def test_natural_price_request_is_resolved_to_concrete_calls(self) -> None:
        session = ChatSession(
            role="retailer",
            principal_id="RET-00004",
            buyer_id="RET-00004",
        ).add_message(
            "user",
            "whats the price of 21 units of fortune rice oil in jaipur region",
        )

        def fake_completion(**kwargs):
            return {
                "choices": [
                    {
                        "message": {
                            "parsed": {
                                "route": "database",
                                "original_query": "model echo",
                                "rewritten_query": (
                                    "Find the price and Jaipur availability for 21 "
                                    "units of Fortune rice oil."
                                ),
                                "rag_requests": [],
                                "tool_calls": [
                                    {
                                        "name": "get_price_quote",
                                        "arguments": {
                                            "product_name": "fortune rice oil",
                                            "quantity": 21,
                                        },
                                        "purpose": "Retrieve retailer pricing",
                                    },
                                    {
                                        "name": "search_available_products",
                                        "arguments": {
                                            "query": "fortune rice oil",
                                            "warehouse_city": "Jaipur region",
                                        },
                                        "purpose": "Check local stock",
                                    },
                                ],
                                "database_requests": [],
                                "clarification_question": None,
                            }
                        }
                    }
                ]
            }

        plan = process_query(
            session,
            knowledge_base_path=self.knowledge_base,
            completion_fn=fake_completion,
        )

        self.assertEqual(
            plan.tool_calls[0].argument_values(),
            {"sku": "SKU-00073", "quantity": 21},
        )
        self.assertEqual(
            plan.tool_calls[1].argument_values(),
            {"query": "SKU-00073", "warehouse_city": "Jaipur"},
        )

    def test_inconsistent_clarify_route_searches_products_before_asking(self) -> None:
        session = ChatSession(
            role="retailer",
            principal_id="RET-00004",
            buyer_id="RET-00004",
        ).add_message("user", "what is the price of ashirwad aata")

        def fake_completion(**kwargs):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "route": "hybrid",
                                    "original_query": "echo",
                                    "rewritten_query": "Price for Aashirvaad atta",
                                    "rag_requests": [],
                                    "tool_calls": [],
                                    "database_requests": [],
                                    "clarification_question": (
                                        "Which product and quantity do you want?"
                                    ),
                                }
                            )
                        }
                    }
                ]
            }

        plan = process_query(
            session,
            knowledge_base_path=self.knowledge_base,
            completion_fn=fake_completion,
        )
        self.assertEqual(plan.route, "database")
        self.assertGreaterEqual(len(plan.tool_calls), 2)
        self.assertTrue(all(call.name == "search_products" for call in plan.tool_calls))
        self.assertIsNone(plan.clarification_question)


if __name__ == "__main__":
    unittest.main()
