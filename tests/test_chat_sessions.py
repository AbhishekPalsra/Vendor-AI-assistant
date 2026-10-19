"""Tests for verified Gradio-ready sessions and role-scoped tools."""

from __future__ import annotations

import hashlib
import sqlite3
import unittest
from pathlib import Path

from vendor_ai_assistant.chat import (
    ChatMessage,
    ChatSession,
    allowed_tool_names,
    create_chat_session,
    execute_session_tool,
    list_buyers_for_role,
    rag_enabled,
    tool_definitions_for_role,
)
from vendor_ai_assistant.tools.results import ACCESS_DENIED_MESSAGE


DB_PATH = Path(__file__).resolve().parents[1] / "data" / "vendor_ai.db"


class ChatSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        connection = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
        cls.customer_id = connection.execute(
            "SELECT buyer_id FROM dim_buyers WHERE buyer_type='Customer' "
            "AND status='Active' LIMIT 1"
        ).fetchone()[0]
        cls.retailer_id = connection.execute(
            "SELECT buyer_id FROM dim_buyers WHERE buyer_type='Retailer' "
            "AND status='Active' LIMIT 1"
        ).fetchone()[0]
        connection.close()
        cls.hash_before = hashlib.sha256(DB_PATH.read_bytes()).hexdigest()

    @classmethod
    def tearDownClass(cls) -> None:
        if hashlib.sha256(DB_PATH.read_bytes()).hexdigest() != cls.hash_before:
            raise AssertionError("Serving database changed during session tests")

    def test_buyer_lists_are_filtered_for_gradio_selection(self) -> None:
        customers = list_buyers_for_role("customer")
        retailers = list_buyers_for_role("retailer")

        self.assertGreater(len(customers), 0)
        self.assertGreater(len(retailers), 0)
        self.assertTrue(all(row["buyer_type"] == "Customer" for row in customers))
        self.assertTrue(all(row["buyer_type"] == "Retailer" for row in retailers))
        self.assertEqual(list_buyers_for_role("admin"), [])

    def test_customer_and_retailer_sessions_use_verified_buyer_identity(self) -> None:
        customer = create_chat_session("Customer", buyer_id=self.customer_id.lower())
        retailer = create_chat_session("retailer", buyer_id=self.retailer_id)

        self.assertEqual(customer.role, "customer")
        self.assertEqual(customer.buyer_id, self.customer_id)
        self.assertEqual(customer.principal_id, self.customer_id)
        self.assertEqual(retailer.role, "retailer")
        self.assertEqual(retailer.buyer_id, self.retailer_id)
        self.assertEqual(customer.request_context()["buyer_id"], self.customer_id)

    def test_role_and_buyer_mismatches_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "required"):
            create_chat_session("customer")
        with self.assertRaisesRegex(ValueError, "does not match"):
            create_chat_session("retailer", buyer_id=self.customer_id)
        with self.assertRaisesRegex(ValueError, "does not exist"):
            create_chat_session("customer", buyer_id="BUYER-DOES-NOT-EXIST")
        with self.assertRaisesRegex(ValueError, "role must be"):
            create_chat_session("unknown", buyer_id=self.customer_id)

    def test_admin_session_has_no_buyer_identity(self) -> None:
        admin = create_chat_session("admin", admin_principal_id="ADMIN-LOCAL")

        self.assertEqual(admin.role, "admin")
        self.assertEqual(admin.principal_id, "ADMIN-LOCAL")
        self.assertIsNone(admin.buyer_id)
        self.assertNotIn("buyer_id", admin.request_context())
        with self.assertRaisesRegex(ValueError, "do not accept"):
            create_chat_session("admin", buyer_id=self.customer_id)

    def test_session_round_trips_as_gradio_state(self) -> None:
        session = create_chat_session("customer", buyer_id=self.customer_id)
        session = session.add_message("user", "  Where is my latest order?  ")
        session = session.add_message("assistant", "I will check that for you.")

        restored = ChatSession.model_validate(session.model_dump())

        self.assertEqual(restored, session)
        self.assertEqual(restored.session_id, session.session_id)
        self.assertEqual(restored.conversation_id, session.conversation_id)
        self.assertEqual(restored.messages, session.messages)

    def test_message_history_supports_future_orchestration(self) -> None:
        original = create_chat_session("customer", buyer_id=self.customer_id)
        updated = original.add_message("user", "  Show available dairy products.  ")
        updated = updated.add_message("assistant", "Here are the available products.")
        updated = updated.add_message("user", "Which are available in Jaipur?")

        self.assertEqual(original.messages, ())
        self.assertEqual(len(updated.messages), 3)
        self.assertIsInstance(updated.current_message, ChatMessage)
        self.assertEqual(
            updated.current_message.content,
            "Which are available in Jaipur?",
        )
        self.assertEqual(len(updated.recent_messages(2)), 2)
        self.assertEqual(updated.recent_messages(2)[0].role, "assistant")

    def test_empty_messages_and_invalid_history_limits_are_rejected(self) -> None:
        session = create_chat_session("customer", buyer_id=self.customer_id)

        with self.assertRaisesRegex(ValueError, "content is required"):
            session.add_message("user", "   ")
        with self.assertRaisesRegex(ValueError, "at least 1"):
            session.recent_messages(0)

    def test_tool_definitions_are_filtered_by_role(self) -> None:
        customer_names = {
            item["function"]["name"] for item in tool_definitions_for_role("customer")
        }
        retailer_names = {
            item["function"]["name"] for item in tool_definitions_for_role("retailer")
        }
        admin_names = {
            item["function"]["name"] for item in tool_definitions_for_role("admin")
        }

        self.assertEqual(customer_names, set(allowed_tool_names("customer")))
        self.assertEqual(retailer_names, customer_names)
        self.assertTrue(all(not name.startswith("admin_") for name in customer_names))
        self.assertIn("admin_search_buyers", admin_names)
        self.assertNotIn("get_my_account", admin_names)

    def test_guarded_executor_blocks_tools_outside_the_role(self) -> None:
        customer = create_chat_session("customer", buyer_id=self.customer_id)
        admin = create_chat_session("admin")

        own_account = execute_session_tool(customer, "get_my_account", {})
        blocked_admin = execute_session_tool(customer, "admin_search_buyers", {})
        admin_buyers = execute_session_tool(
            admin, "admin_search_buyers", {"limit": 2}
        )
        blocked_customer = execute_session_tool(admin, "get_my_account", {})

        self.assertEqual(own_account["status"], "success")
        self.assertEqual(own_account["data"][0]["buyer_id"], self.customer_id)
        self.assertEqual(blocked_admin["status"], "access_denied")
        self.assertEqual(blocked_admin["message"], ACCESS_DENIED_MESSAGE)
        self.assertEqual(admin_buyers["status"], "success")
        self.assertEqual(blocked_customer["status"], "access_denied")

    def test_rag_is_open_to_every_supported_role(self) -> None:
        self.assertTrue(rag_enabled("customer"))
        self.assertTrue(rag_enabled("retailer"))
        self.assertTrue(rag_enabled("admin"))


if __name__ == "__main__":
    unittest.main()
