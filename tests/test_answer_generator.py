"""Network-free tests for grounded, Gradio-ready answer generation."""

from __future__ import annotations

import json
import unittest
from typing import Any

from vendor_ai_assistant.chat.answer_generator import (
    ANSWER_MODEL,
    SAFE_ERROR_MESSAGE,
    SYSTEM_PROMPT,
    generate_answer,
    make_answer_messages,
)
from vendor_ai_assistant.chat.models import (
    ChatSession,
    DatabaseRequest,
    QueryPlan,
    RagRequest,
    ToolExecution,
    ToolLoopResult,
)
from vendor_ai_assistant.chat.orchestrator import (
    EvidenceBundle,
    OrchestrationResult,
)
from vendor_ai_assistant.rag.models import RagEvidence


def chat_session() -> ChatSession:
    session = ChatSession(
        role="customer",
        principal_id="CUS-001",
        buyer_id="CUS-001",
    )
    session = session.add_message("user", "Tell me about Fortune oil")
    session = session.add_message("assistant", "What would you like to know?")
    return session.add_message(
        "user", "Can I order one in Jaipur and return it if damaged?"
    )


def hybrid_plan() -> QueryPlan:
    return QueryPlan(
        route="hybrid",
        original_query="Can I order one in Jaipur and return it if damaged?",
        rewritten_query=(
            "Can the previously discussed Fortune oil be ordered in Jaipur, and "
            "what return rules apply if it arrives damaged?"
        ),
        rag_requests=(
            RagRequest(
                query="Return policy for damaged Fortune oil delivered in Jaipur",
                purpose="Explain return requirements",
                source_paths=("policies/return-policy.md",),
            ),
        ),
        database_requests=(
            DatabaseRequest(
                query="Fortune oil availability in Jaipur",
                purpose="Retrieve current stock",
                tool_names=("search_available_products",),
            ),
        ),
    )


def rag_evidence() -> RagEvidence:
    return RagEvidence(
        chunk_id="chunk-1",
        headline="Damaged goods",
        summary="Damaged goods reporting requirements.",
        original_text="Report damaged goods within 48 hours with photographs.",
        source_path="policies/return-policy.md",
        document_type="policies",
        chunk_index=0,
        matched_queries=("Return policy for damaged Fortune oil",),
        retrieval_distance=0.1,
        rerank_score=0.96,
        rerank_reason="Directly relevant.",
    )


def database_execution(status: str = "success") -> ToolExecution:
    if status == "success":
        result = {
            "status": "success",
            "data": [
                {
                    "sku": "SKU-100",
                    "product_name": "Fortune Sunflower Oil",
                    "warehouse_city": "Jaipur",
                    "available_quantity": 25,
                }
            ],
            "message": "",
        }
    else:
        result = {
            "status": "access_denied",
            "data": [],
            "message": "This data is not available for your account.",
        }
    return ToolExecution(
        iteration=1,
        tool_call_id="call-1",
        tool_name="search_available_products",
        arguments={"query": "Fortune oil", "warehouse_city": "Jaipur"},
        result=result,
    )


def orchestration(
    *,
    status: str = "ready_for_answer",
    database_status: str = "success",
    warnings: tuple[str, ...] = (),
) -> OrchestrationResult:
    execution = database_execution(database_status)
    tool_result = ToolLoopResult(
        status="completed",
        executions=(execution,),
        iterations=2,
        stop_reason="model_completed",
    )
    return OrchestrationResult(
        status=status,
        query_plan=hybrid_plan(),
        evidence=EvidenceBundle(
            rag=(rag_evidence(),),
            database=(execution,),
        ),
        tool_loop_result=tool_result,
        warnings=warnings,
    )


class AnswerGeneratorTests(unittest.TestCase):
    def test_prompt_contains_role_history_plan_and_both_evidence_sources(self) -> None:
        messages = make_answer_messages(chat_session(), orchestration())
        payload = json.loads(messages[1]["content"])

        self.assertEqual(messages[0]["content"], SYSTEM_PROMPT)
        self.assertIn("Lead with the answer or useful matches", SYSTEM_PROMPT)
        self.assertIn("Do not produce procedural menus", SYSTEM_PROMPT)
        self.assertEqual(payload["session_role"], "customer")
        self.assertEqual(len(payload["recent_history"]), 2)
        self.assertEqual(payload["query_plan"]["route"], "hybrid")
        self.assertEqual(payload["rag_evidence"][0]["chunk_id"], "chunk-1")
        self.assertEqual(
            payload["database_evidence"][0]["result"]["data"][0]["sku"],
            "SKU-100",
        )
        self.assertNotIn("buyer_id", payload)
        self.assertNotIn("principal_id", payload)

    def test_litellm_answer_is_returned_without_mutating_session(self) -> None:
        session = chat_session()
        original_messages = session.messages
        calls: list[dict[str, Any]] = []

        def fake_completion(**kwargs):
            calls.append(kwargs)
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                "Fortune Sunflower Oil has 25 units available in "
                                "Jaipur. I cannot place the order here. If it arrives "
                                "damaged, report it within 48 hours with photographs "
                                "(return-policy.md)."
                            )
                        }
                    }
                ]
            }

        answer = generate_answer(
            session,
            orchestration(),
            completion_fn=fake_completion,
        )

        self.assertIn("25 units", answer)
        self.assertIn("cannot place the order", answer)
        self.assertEqual(calls[0]["model"], ANSWER_MODEL)
        self.assertNotIn("tools", calls[0])
        self.assertNotIn("temperature", calls[0])
        self.assertEqual(session.messages, original_messages)

    def test_orchestrator_clarification_bypasses_llm(self) -> None:
        result = OrchestrationResult(
            status="needs_clarification",
            query_plan=QueryPlan(
                route="clarify",
                original_query="What is the price?",
                rewritten_query="What is the price?",
                clarification_question="Which product and quantity do you mean?",
            ),
            clarification_question="Which product and quantity do you mean?",
        )

        answer = generate_answer(
            chat_session(),
            result,
            completion_fn=lambda **kwargs: self.fail("LLM should not be called"),
        )

        self.assertEqual(answer, "Which product and quantity do you mean?")

    def test_unrecoverable_orchestration_error_bypasses_llm(self) -> None:
        result = OrchestrationResult(
            status="error",
            warnings=("query_processing_failed",),
        )

        answer = generate_answer(
            chat_session(),
            result,
            completion_fn=lambda **kwargs: self.fail("LLM should not be called"),
        )

        self.assertEqual(answer, SAFE_ERROR_MESSAGE)

    def test_partial_result_and_restricted_data_are_visible_to_model(self) -> None:
        result = orchestration(
            status="partial",
            database_status="access_denied",
            warnings=("database_retrieval_failed",),
        )
        captured: dict[str, Any] = {}

        def fake_completion(**kwargs):
            captured.update(kwargs)
            return {
                "choices": [
                    {
                        "message": {
                            "content": (
                                "The return policy requires reporting damage within "
                                "48 hours. Availability data is not available for your account."
                            )
                        }
                    }
                ]
            }

        answer = generate_answer(
            chat_session(),
            result,
            completion_fn=fake_completion,
        )
        payload = json.loads(captured["messages"][1]["content"])

        self.assertIn("not available", answer)
        self.assertEqual(payload["orchestration_status"], "partial")
        self.assertEqual(
            payload["database_evidence"][0]["result"]["status"],
            "access_denied",
        )
        self.assertEqual(payload["retrieval_warnings"], ["database_retrieval_failed"])

    def test_empty_or_invalid_model_response_returns_safe_message(self) -> None:
        empty = generate_answer(
            chat_session(),
            orchestration(),
            completion_fn=lambda **kwargs: {
                "choices": [{"message": {"content": None}}]
            },
        )

        self.assertEqual(empty, SAFE_ERROR_MESSAGE)

    def test_history_limit_is_enforced(self) -> None:
        messages = make_answer_messages(
            chat_session(),
            orchestration(),
            history_limit=1,
        )
        payload = json.loads(messages[1]["content"])

        self.assertEqual(len(payload["recent_history"]), 1)
        self.assertEqual(payload["recent_history"][0]["role"], "assistant")


if __name__ == "__main__":
    unittest.main()
