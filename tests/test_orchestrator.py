"""Network-free tests for routing and structured evidence orchestration."""

from __future__ import annotations

import unittest
from typing import Any

from vendor_ai_assistant.chat.models import (
    ChatSession,
    DatabaseRequest,
    QueryPlan,
    RagRequest,
    ToolExecution,
    ToolLoopResult,
)
from vendor_ai_assistant.chat.orchestrator import orchestrate_turn
from vendor_ai_assistant.rag.models import RagEvidence


def session_with_message() -> ChatSession:
    session = ChatSession(
        role="customer",
        principal_id="CUS-001",
        buyer_id="CUS-001",
    )
    return session.add_message(
        "user",
        "Which Fortune oils are available in Jaipur and can damaged ones be returned?",
    )


def rag_request() -> RagRequest:
    return RagRequest(
        query="Return rules for damaged Fortune oil delivered in Jaipur",
        purpose="Explain damaged-product return eligibility",
        source_paths=("policies/return-policy.md",),
    )


def database_request() -> DatabaseRequest:
    return DatabaseRequest(
        query="Current Fortune oil availability in Jaipur",
        purpose="Retrieve live stock",
        tool_names=("search_available_products",),
    )


def plan(route: str) -> QueryPlan:
    kwargs: dict[str, Any] = {
        "route": route,
        "original_query": "Original user message",
        "rewritten_query": "Complete rewritten user intent",
        "rag_requests": (),
        "database_requests": (),
        "clarification_question": None,
    }
    if route in {"rag", "hybrid"}:
        kwargs["rag_requests"] = (rag_request(),)
    if route in {"database", "hybrid"}:
        kwargs["database_requests"] = (database_request(),)
    if route == "clarify":
        kwargs["clarification_question"] = "Which product do you mean?"
    return QueryPlan.model_validate(kwargs)


def rag_evidence() -> RagEvidence:
    return RagEvidence(
        chunk_id="chunk-1",
        headline="Return policy",
        summary="Rules for damaged products.",
        original_text="Damaged products must be reported within the stated window.",
        source_path="policies/return-policy.md",
        document_type="policies",
        chunk_index=0,
        matched_queries=("Return rules for damaged Fortune oil delivered in Jaipur",),
        retrieval_distance=0.1,
        rerank_score=0.95,
        rerank_reason="Direct policy evidence.",
    )


def tool_execution() -> ToolExecution:
    return ToolExecution(
        iteration=1,
        tool_call_id="call-1",
        tool_name="search_available_products",
        arguments={"query": "Fortune oil", "warehouse_city": "Jaipur"},
        result={
            "status": "success",
            "data": [{"sku": "SKU-100", "available_quantity": 25}],
        },
    )


def completed_tool_result() -> ToolLoopResult:
    return ToolLoopResult(
        status="completed",
        executions=(tool_execution(),),
        iterations=2,
        assistant_summary="Availability retrieved.",
        stop_reason="model_completed",
    )


class OrchestratorTests(unittest.TestCase):
    def test_rag_route_calls_only_rag_and_preserves_context(self) -> None:
        session = session_with_message()
        calls: list[tuple[Any, ...]] = []

        def retrieve(requests, **kwargs):
            calls.append((requests, kwargs))
            return [rag_evidence()]

        result = orchestrate_turn(
            session,
            query_processor=lambda supplied: plan("rag"),
            rag_retriever=retrieve,
            database_runner=lambda *args, **kwargs: self.fail(
                "database runner should not be called"
            ),
        )

        self.assertEqual(result.status, "ready_for_answer")
        self.assertEqual(result.evidence.rag, (rag_evidence(),))
        self.assertEqual(result.evidence.database, ())
        self.assertEqual(calls[0][0], (rag_request(),))
        self.assertEqual(calls[0][1]["rewritten_query"], plan("rag").rewritten_query)
        self.assertEqual(calls[0][1]["original_query"], plan("rag").original_query)
        self.assertEqual(len(session.messages), 1)

    def test_database_route_calls_only_role_aware_tool_runner(self) -> None:
        session = session_with_message()
        received: dict[str, Any] = {}

        def run_database(requests, **kwargs):
            received["requests"] = requests
            received.update(kwargs)
            return completed_tool_result()

        result = orchestrate_turn(
            session,
            query_processor=lambda supplied: plan("database"),
            rag_retriever=lambda *args, **kwargs: self.fail(
                "RAG retriever should not be called"
            ),
            database_runner=run_database,
        )

        self.assertEqual(result.status, "ready_for_answer")
        self.assertEqual(result.evidence.database, (tool_execution(),))
        self.assertIs(received["session"], session)
        self.assertEqual(received["requests"], (database_request(),))

    def test_hybrid_route_merges_without_flattening_source_evidence(self) -> None:
        result = orchestrate_turn(
            session_with_message(),
            query_processor=lambda supplied: plan("hybrid"),
            rag_retriever=lambda *args, **kwargs: [rag_evidence()],
            database_runner=lambda *args, **kwargs: completed_tool_result(),
        )

        self.assertEqual(result.status, "ready_for_answer")
        self.assertEqual(result.evidence.evidence_count, 2)
        self.assertTrue(result.evidence.has_evidence)
        self.assertIsInstance(result.evidence.rag[0], RagEvidence)
        self.assertIsInstance(result.evidence.database[0], ToolExecution)
        self.assertEqual(result.query_plan.route, "hybrid")

    def test_direct_and_clarify_routes_skip_all_retrieval(self) -> None:
        def forbidden(*args, **kwargs):
            raise AssertionError("retrieval should not run")

        direct = orchestrate_turn(
            session_with_message(),
            query_processor=lambda supplied: plan("direct"),
            rag_retriever=forbidden,
            database_runner=forbidden,
        )
        clarify = orchestrate_turn(
            session_with_message(),
            query_processor=lambda supplied: plan("clarify"),
            rag_retriever=forbidden,
            database_runner=forbidden,
        )

        self.assertEqual(direct.status, "ready_for_answer")
        self.assertFalse(direct.evidence.has_evidence)
        self.assertEqual(clarify.status, "needs_clarification")
        self.assertEqual(clarify.clarification_question, "Which product do you mean?")

    def test_tool_clarification_is_propagated_with_existing_rag_evidence(self) -> None:
        tool_result = ToolLoopResult(
            status="needs_clarification",
            iterations=1,
            clarification_question="Which Jaipur warehouse location?",
            stop_reason="model_requested_clarification",
        )

        result = orchestrate_turn(
            session_with_message(),
            query_processor=lambda supplied: plan("hybrid"),
            rag_retriever=lambda *args, **kwargs: [rag_evidence()],
            database_runner=lambda *args, **kwargs: tool_result,
        )

        self.assertEqual(result.status, "needs_clarification")
        self.assertEqual(
            result.clarification_question, "Which Jaipur warehouse location?"
        )
        self.assertEqual(result.evidence.rag, (rag_evidence(),))

    def test_one_failed_hybrid_branch_preserves_other_branch_as_partial(self) -> None:
        def failing_rag(*args, **kwargs):
            raise RuntimeError("private internal failure")

        result = orchestrate_turn(
            session_with_message(),
            query_processor=lambda supplied: plan("hybrid"),
            rag_retriever=failing_rag,
            database_runner=lambda *args, **kwargs: completed_tool_result(),
        )

        self.assertEqual(result.status, "partial")
        self.assertEqual(result.evidence.database, (tool_execution(),))
        self.assertEqual(result.warnings, ("rag_retrieval_failed",))
        self.assertNotIn("private internal failure", result.model_dump_json())

    def test_query_processing_failure_is_safe_and_structured(self) -> None:
        def failing_processor(session):
            raise RuntimeError("secret model failure")

        result = orchestrate_turn(
            session_with_message(),
            query_processor=failing_processor,
        )

        self.assertEqual(result.status, "error")
        self.assertIsNone(result.query_plan)
        self.assertEqual(result.warnings, ("query_processing_failed",))
        self.assertNotIn("secret model failure", result.model_dump_json())

    def test_session_without_current_user_message_fails_before_processing(self) -> None:
        empty = ChatSession(
            role="customer",
            principal_id="CUS-001",
            buyer_id="CUS-001",
        )

        result = orchestrate_turn(
            empty,
            query_processor=lambda supplied: self.fail(
                "query processor should not be called"
            ),
        )

        self.assertEqual(result.status, "error")
        self.assertEqual(result.warnings, ("session_has_no_current_user_message",))


if __name__ == "__main__":
    unittest.main()
