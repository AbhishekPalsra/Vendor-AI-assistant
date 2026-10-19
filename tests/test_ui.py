"""Network-free tests for Gradio session binding and chat callbacks."""

from __future__ import annotations

import unittest
from typing import Any

import gradio as gr

from vendor_ai_assistant.chat.models import ChatSession, QueryPlan
from vendor_ai_assistant.chat.orchestrator import OrchestrationResult
from vendor_ai_assistant.ui.app import (
    DEFAULT_SHARE_USERNAME,
    MAX_MESSAGE_LENGTH,
    begin_buyer_session,
    begin_role,
    build_app,
    buyer_choices,
    chatbot_history,
    launch_app,
    reset_chat,
    share_auth,
    submit_message,
)


class FakeDemo:
    def __init__(self) -> None:
        self.queue_kwargs: dict[str, Any] | None = None
        self.launch_kwargs: dict[str, Any] | None = None

    def queue(self, **kwargs):
        self.queue_kwargs = kwargs
        return self

    def launch(self, **kwargs):
        self.launch_kwargs = kwargs
        return "launched"


class UiTests(unittest.TestCase):
    @staticmethod
    def customer_session() -> ChatSession:
        return ChatSession(
            role="customer",
            principal_id="CUS-001",
            buyer_id="CUS-001",
        )

    def test_admin_role_starts_immediately(self) -> None:
        calls = []

        def factory(role, **kwargs):
            calls.append((role, kwargs))
            return ChatSession(role="admin", principal_id="ADMIN-DEMO")

        session, pending_role, choices = begin_role(
            "Admin",
            session_factory=factory,
        )

        self.assertEqual(session.role, "admin")
        self.assertIsNone(pending_role)
        self.assertEqual(choices, [])
        self.assertEqual(calls, [("admin", {})])

    def test_customer_and_retailer_roles_offer_filtered_buyer_choices(self) -> None:
        def loader(role):
            return [
                {
                    "buyer_id": f"{role[:3].upper()}-001",
                    "buyer_name": f"Example {role.title()}",
                    "city": "Jaipur",
                    "state": "Rajasthan",
                    "retailer_tier": "Gold" if role == "retailer" else None,
                }
            ]

        customer = buyer_choices("customer", buyer_loader=loader)
        session, pending, retailer = begin_role(
            "retailer",
            buyer_loader=loader,
        )

        self.assertIn("Jaipur", customer[0][0])
        self.assertEqual(customer[0][1], "CUS-001")
        self.assertIsNone(session)
        self.assertEqual(pending, "retailer")
        self.assertEqual(retailer[0][1], "RET-001")
        self.assertIn("Gold", retailer[0][0])

    def test_buyer_session_requires_role_and_selected_account(self) -> None:
        calls = []

        def factory(role, **kwargs):
            calls.append((role, kwargs))
            return ChatSession(
                role=role,
                principal_id=kwargs["buyer_id"],
                buyer_id=kwargs["buyer_id"],
            )

        session = begin_buyer_session(
            "customer",
            "CUS-001",
            session_factory=factory,
        )

        self.assertEqual(session.buyer_id, "CUS-001")
        self.assertEqual(calls, [("customer", {"buyer_id": "CUS-001"})])
        with self.assertRaisesRegex(ValueError, "Choose customer or retailer"):
            begin_buyer_session(None, "CUS-001", session_factory=factory)
        with self.assertRaisesRegex(ValueError, "Choose an account"):
            begin_buyer_session("customer", None, session_factory=factory)

    def test_submit_message_runs_complete_turn_and_retains_followup_history(self) -> None:
        orchestration_calls: list[ChatSession] = []
        answer_calls: list[tuple[ChatSession, OrchestrationResult]] = []

        def orchestrator(session):
            orchestration_calls.append(session)
            current = session.current_message.content
            return OrchestrationResult(
                status="ready_for_answer",
                query_plan=QueryPlan(
                    route="direct",
                    original_query=current,
                    rewritten_query=current,
                ),
            )

        def answer_generator(session, result):
            answer_calls.append((session, result))
            return f"Answer to: {session.current_message.content}"

        _, first_history, first_session, _ = submit_message(
            "Hello",
            self.customer_session(),
            orchestrator=orchestrator,
            answer_generator=answer_generator,
        )
        _, second_history, second_session, _ = submit_message(
            "What about Jaipur?",
            first_session,
            orchestrator=orchestrator,
            answer_generator=answer_generator,
        )

        self.assertEqual(len(first_history), 2)
        self.assertEqual(len(second_history), 4)
        self.assertEqual(second_history[-2]["content"], "What about Jaipur?")
        self.assertEqual(second_history[-1]["role"], "assistant")
        self.assertEqual(len(orchestration_calls[1].messages), 3)
        self.assertEqual(answer_calls[1][0].messages, orchestration_calls[1].messages)
        self.assertEqual(chatbot_history(second_session), second_history)

    def test_submit_validation_does_not_call_models_or_mutate_session(self) -> None:
        session = self.customer_session()

        def forbidden(*args, **kwargs):
            raise AssertionError("Model path must not be called")

        _, empty_history, empty_session, empty_status = submit_message(
            "   ",
            session,
            orchestrator=forbidden,
            answer_generator=forbidden,
        )
        too_long = "x" * (MAX_MESSAGE_LENGTH + 1)
        retained, long_history, long_session, long_status = submit_message(
            too_long,
            session,
            orchestrator=forbidden,
            answer_generator=forbidden,
        )
        retained_without_session, _, no_session, no_session_status = submit_message(
            "Hello", None, orchestrator=forbidden, answer_generator=forbidden
        )

        self.assertEqual(empty_history, [])
        self.assertIs(empty_session, session)
        self.assertIn("Enter a message", empty_status)
        self.assertEqual(retained, too_long)
        self.assertEqual(long_history, [])
        self.assertIs(long_session, session)
        self.assertIn("4,000", long_status)
        self.assertEqual(retained_without_session, "Hello")
        self.assertIsNone(no_session)
        self.assertIn("Choose a role", no_session_status)

    def test_unexpected_chat_failure_returns_safe_assistant_message(self) -> None:
        _, history, session, _ = submit_message(
            "Check my order",
            self.customer_session(),
            orchestrator=lambda supplied: (_ for _ in ()).throw(
                RuntimeError("private error")
            ),
        )

        self.assertEqual(len(history), 2)
        self.assertEqual(history[-1]["role"], "assistant")
        self.assertNotIn("private error", history[-1]["content"])
        self.assertEqual(len(session.messages), 2)

    def test_new_chat_discards_session_and_history(self) -> None:
        self.assertEqual(reset_chat(), (None, None, []))

    def test_app_builds_without_launching_or_calling_models(self) -> None:
        demo = build_app()
        try:
            self.assertIsInstance(demo, gr.Blocks)
            self.assertGreater(len(demo.blocks), 0)
        finally:
            demo.close()

    def test_shared_launch_is_always_authenticated(self) -> None:
        self.assertEqual(
            share_auth(
                {"GRADIO_USERNAME": "owner", "GRADIO_PASSWORD": "safe-password"}
            ),
            ("owner", "safe-password"),
        )
        username, generated = share_auth({})
        self.assertEqual(username, DEFAULT_SHARE_USERNAME)
        self.assertGreaterEqual(len(generated), 12)
        with self.assertRaisesRegex(ValueError, "both"):
            share_auth({"GRADIO_USERNAME": "owner"})

        demo = FakeDemo()
        self.assertEqual(launch_app(demo, ("owner", "password")), "launched")
        self.assertEqual(demo.queue_kwargs, {"default_concurrency_limit": 4})
        self.assertIs(demo.launch_kwargs["share"], True)
        self.assertEqual(demo.launch_kwargs["auth"], ("owner", "password"))
        self.assertIs(demo.launch_kwargs["show_error"], False)


if __name__ == "__main__":
    unittest.main()
