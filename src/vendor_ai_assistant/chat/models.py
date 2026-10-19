"""Small, Gradio-serializable models for role-aware chat sessions."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from collections.abc import Mapping
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


UserRole = Literal["customer", "retailer", "admin"]
MessageRole = Literal["user", "assistant"]
QueryRoute = Literal["direct", "clarify", "rag", "database", "hybrid"]
ToolLoopStatus = Literal[
    "completed", "needs_clarification", "max_iterations", "error"
]


class ChatMessage(BaseModel):
    """One user or assistant turn stored in conversation history."""

    model_config = ConfigDict(frozen=True)

    message_id: str = Field(default_factory=lambda: str(uuid4()))
    role: MessageRole
    content: str
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        content = value.strip()
        if not content:
            raise ValueError("message content is required")
        return content


class ChatSession(BaseModel):
    """Trusted state kept in ``gr.State`` for one browser session."""

    model_config = ConfigDict(frozen=True)

    session_id: str = Field(default_factory=lambda: str(uuid4()))
    conversation_id: str = Field(default_factory=lambda: str(uuid4()))
    role: UserRole
    principal_id: str
    buyer_id: str | None = None
    authenticated: bool = True
    messages: tuple[ChatMessage, ...] = ()

    @model_validator(mode="after")
    def validate_role_identity(self) -> "ChatSession":
        if not self.authenticated:
            raise ValueError("chat sessions must be authenticated")
        if not self.principal_id.strip():
            raise ValueError("principal_id is required")
        if self.role in {"customer", "retailer"} and not self.buyer_id:
            raise ValueError("customer and retailer sessions require a buyer_id")
        if self.role == "admin" and self.buyer_id is not None:
            raise ValueError("admin sessions do not use buyer_id")
        return self

    def request_context(self) -> dict[str, str | bool]:
        context: dict[str, str | bool] = {
            "authenticated": True,
            "role": self.role,
            "principal_id": self.principal_id,
        }
        if self.buyer_id:
            context["buyer_id"] = self.buyer_id
        return context

    def add_message(self, role: MessageRole, content: str) -> "ChatSession":
        """Return a new session containing one additional conversation turn."""

        message = ChatMessage(role=role, content=content)
        return self.model_copy(update={"messages": (*self.messages, message)})

    def recent_messages(self, limit: int = 8) -> tuple[ChatMessage, ...]:
        """Return the most recent turns for query processing or answer generation."""

        if limit < 1:
            raise ValueError("history limit must be at least 1")
        return self.messages[-limit:]

    @property
    def current_message(self) -> ChatMessage | None:
        """Return the latest conversation turn, if the chat has started."""

        return self.messages[-1] if self.messages else None


class RagRequest(BaseModel):
    """One self-contained semantic question for the knowledge base."""

    query: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    source_paths: tuple[str, ...] = Field(
        default=(),
        description="Likely knowledge-base files; retrieval treats these as hints.",
    )


class DatabaseRequest(BaseModel):
    """One self-contained database need mapped to permitted tools."""

    query: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    tool_names: tuple[str, ...] = Field(min_length=1)


class PlannedToolCall(BaseModel):
    """One concrete, role-validated database call produced during planning."""

    name: str = Field(min_length=1)
    arguments: str = Field(
        default="{}",
        description="JSON-encoded object containing arguments for the selected tool.",
    )
    purpose: str = Field(min_length=1)

    @field_validator("arguments", mode="before")
    @classmethod
    def validate_arguments(cls, value: Any) -> str:
        if isinstance(value, Mapping):
            return json.dumps(dict(value), ensure_ascii=False, sort_keys=True)
        if not isinstance(value, str):
            raise ValueError("tool arguments must be a JSON object string")
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError("tool arguments must contain valid JSON") from error
        if not isinstance(parsed, dict):
            raise ValueError("tool arguments must encode a JSON object")
        return json.dumps(parsed, ensure_ascii=False, sort_keys=True)

    def argument_values(self) -> dict[str, Any]:
        """Return validated arguments as a fresh mutable mapping."""

        return json.loads(self.arguments)


class QueryPlan(BaseModel):
    """Structured routing decision consumed by the future orchestrator."""

    route: QueryRoute
    original_query: str = Field(min_length=1)
    rewritten_query: str = Field(
        min_length=1,
        description="Complete user intent with relevant follow-up context resolved.",
    )
    rag_requests: tuple[RagRequest, ...] = ()
    tool_calls: tuple[PlannedToolCall, ...] = ()
    # Kept temporarily for compatibility with saved/test plans created before
    # concrete planned calls were introduced. New query plans use tool_calls.
    database_requests: tuple[DatabaseRequest, ...] = ()
    clarification_question: str | None = None

    @model_validator(mode="after")
    def validate_route_contents(self) -> "QueryPlan":
        has_rag = bool(self.rag_requests)
        has_database = bool(self.tool_calls or self.database_requests)
        expected = {
            (False, False): {"direct", "clarify"},
            (True, False): {"rag"},
            (False, True): {"database"},
            (True, True): {"hybrid"},
        }[(has_rag, has_database)]
        if self.route not in expected:
            raise ValueError(
                "route does not match the included RAG and database requests"
            )
        if self.route == "clarify" and not (
            self.clarification_question and self.clarification_question.strip()
        ):
            raise ValueError("clarify plans require a clarification question")
        if self.route != "clarify" and self.clarification_question is not None:
            raise ValueError("only clarify plans may include a clarification question")
        return self


class ToolExecution(BaseModel):
    """One attempted tool call and its JSON-safe result."""

    iteration: int = Field(ge=1)
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    executed: bool = True


class ToolLoopResult(BaseModel):
    """Database evidence and stop state returned to the orchestrator."""

    status: ToolLoopStatus
    executions: tuple[ToolExecution, ...] = ()
    iterations: int = Field(ge=0)
    assistant_summary: str | None = None
    clarification_question: str | None = None
    stop_reason: str

    @model_validator(mode="after")
    def validate_clarification(self) -> "ToolLoopResult":
        if self.status == "needs_clarification" and not (
            self.clarification_question and self.clarification_question.strip()
        ):
            raise ValueError(
                "needs_clarification results require a clarification question"
            )
        if self.status != "needs_clarification" and self.clarification_question:
            raise ValueError(
                "only needs_clarification results may include a question"
            )
        return self
