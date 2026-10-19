"""Coordinate query planning and evidence retrieval for one chat turn."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from vendor_ai_assistant.chat.models import (
    ChatSession,
    QueryPlan,
    ToolExecution,
    ToolLoopResult,
)
from vendor_ai_assistant.chat.query_processor import process_query
from vendor_ai_assistant.chat.tool_runner import run_tool_loop
from vendor_ai_assistant.rag.models import RagEvidence
from vendor_ai_assistant.rag.retrieve import retrieve_rag


OrchestrationStatus = Literal[
    "ready_for_answer", "needs_clarification", "partial", "error"
]
QueryProcessor = Callable[[ChatSession], QueryPlan]
RagRetriever = Callable[..., Sequence[RagEvidence]]
DatabaseRunner = Callable[..., ToolLoopResult]
LOGGER = logging.getLogger(__name__)


class EvidenceBundle(BaseModel):
    """Source-separated evidence passed unchanged to the answer generator."""

    rag: tuple[RagEvidence, ...] = ()
    database: tuple[ToolExecution, ...] = ()

    @property
    def has_evidence(self) -> bool:
        return bool(self.rag) or any(item.executed for item in self.database)

    @property
    def evidence_count(self) -> int:
        return len(self.rag) + sum(item.executed for item in self.database)


class OrchestrationResult(BaseModel):
    """Complete retrieval state for the future answer generator."""

    status: OrchestrationStatus
    query_plan: QueryPlan | None = None
    evidence: EvidenceBundle = Field(default_factory=EvidenceBundle)
    tool_loop_result: ToolLoopResult | None = None
    clarification_question: str | None = None
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_state(self) -> "OrchestrationResult":
        if self.status == "needs_clarification" and not (
            self.clarification_question and self.clarification_question.strip()
        ):
            raise ValueError(
                "needs_clarification orchestration requires a question"
            )
        if self.status != "needs_clarification" and self.clarification_question:
            raise ValueError(
                "only needs_clarification orchestration may include a question"
            )
        if self.status != "error" and self.query_plan is None:
            raise ValueError("successful orchestration requires a query plan")
        return self


def _error_result(warning: str) -> OrchestrationResult:
    return OrchestrationResult(status="error", warnings=(warning,))


def _final_status(
    evidence: EvidenceBundle,
    tool_result: ToolLoopResult | None,
    warnings: Sequence[str],
) -> OrchestrationStatus:
    if warnings:
        return "partial" if evidence.has_evidence else "error"
    if tool_result and tool_result.status in {"error", "max_iterations"}:
        return "partial" if evidence.has_evidence else "error"
    return "ready_for_answer"


def orchestrate_turn(
    session: ChatSession,
    *,
    query_processor: QueryProcessor = process_query,
    rag_retriever: RagRetriever = retrieve_rag,
    database_runner: DatabaseRunner = run_tool_loop,
) -> OrchestrationResult:
    """Plan and retrieve evidence for the latest user message.

    The function deliberately does not generate or store an assistant response.
    The future answer generator will consume this typed result, after which its
    answer can be appended through ``session.add_message("assistant", answer)``.
    """

    current = session.current_message
    if current is None or current.role != "user":
        return _error_result("session_has_no_current_user_message")

    try:
        plan = query_processor(session)
    except Exception:
        LOGGER.exception("Query processing failed")
        return _error_result("query_processing_failed")

    if plan.route == "clarify":
        return OrchestrationResult(
            status="needs_clarification",
            query_plan=plan,
            clarification_question=plan.clarification_question,
        )

    if plan.route == "direct":
        return OrchestrationResult(
            status="ready_for_answer",
            query_plan=plan,
        )

    rag_evidence: tuple[RagEvidence, ...] = ()
    tool_result: ToolLoopResult | None = None
    warnings: list[str] = []

    if plan.route in {"rag", "hybrid"}:
        try:
            rag_evidence = tuple(
                rag_retriever(
                    plan.rag_requests,
                    rewritten_query=plan.rewritten_query,
                    original_query=plan.original_query,
                )
            )
        except Exception:
            LOGGER.exception("RAG retrieval failed")
            warnings.append("rag_retrieval_failed")

    if plan.route in {"database", "hybrid"}:
        try:
            database_plan = plan.tool_calls or plan.database_requests
            tool_result = database_runner(
                database_plan,
                session=session,
                rewritten_query=plan.rewritten_query,
                original_query=plan.original_query,
            )
        except Exception:
            LOGGER.exception("Database retrieval failed")
            warnings.append("database_retrieval_failed")

    database_evidence = tool_result.executions if tool_result else ()
    evidence = EvidenceBundle(
        rag=rag_evidence,
        database=database_evidence,
    )

    if tool_result and tool_result.status == "needs_clarification":
        return OrchestrationResult(
            status="needs_clarification",
            query_plan=plan,
            evidence=evidence,
            tool_loop_result=tool_result,
            clarification_question=tool_result.clarification_question,
            warnings=tuple(warnings),
        )

    if tool_result and tool_result.status == "max_iterations":
        warnings.append("database_retrieval_limit_reached")
    elif tool_result and tool_result.status == "error":
        warnings.append("database_retrieval_failed")

    return OrchestrationResult(
        status=_final_status(evidence, tool_result, warnings),
        query_plan=plan,
        evidence=evidence,
        tool_loop_result=tool_result,
        warnings=tuple(dict.fromkeys(warnings)),
    )
