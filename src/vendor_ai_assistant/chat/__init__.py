"""Role-aware session helpers for the future Gradio chat interface."""

from vendor_ai_assistant.chat.models import (
    ChatMessage,
    ChatSession,
    DatabaseRequest,
    MessageRole,
    QueryPlan,
    QueryRoute,
    RagRequest,
    ToolExecution,
    ToolLoopResult,
    ToolLoopStatus,
    UserRole,
)
from vendor_ai_assistant.chat.query_processor import process_query
from vendor_ai_assistant.chat.roles import (
    allowed_tool_names,
    execute_session_tool,
    rag_enabled,
    tool_definitions_for_role,
)
from vendor_ai_assistant.chat.session import create_chat_session, list_buyers_for_role
from vendor_ai_assistant.chat.tool_runner import run_tool_loop

__all__ = [
    "ChatMessage",
    "ChatSession",
    "DatabaseRequest",
    "MessageRole",
    "QueryPlan",
    "QueryRoute",
    "RagRequest",
    "ToolExecution",
    "ToolLoopResult",
    "ToolLoopStatus",
    "UserRole",
    "allowed_tool_names",
    "create_chat_session",
    "execute_session_tool",
    "list_buyers_for_role",
    "process_query",
    "rag_enabled",
    "run_tool_loop",
    "tool_definitions_for_role",
]
