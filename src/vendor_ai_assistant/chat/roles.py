"""Role configuration and guarded access to database tools."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final, cast

from vendor_ai_assistant.chat.models import ChatSession, UserRole
from vendor_ai_assistant.tools.loader import load_tool_definitions
from vendor_ai_assistant.tools.registry import execute_tool
from vendor_ai_assistant.tools.results import access_denied


CUSTOMER_RETAILER_TOOLS: Final[frozenset[str]] = frozenset(
    {
        "search_products",
        "search_available_products",
        "get_product_details",
        "get_price_quote",
        "get_my_account",
        "get_order_status",
        "get_order_history",
        "get_repurchase_suggestions",
    }
)

ADMIN_TOOLS: Final[frozenset[str]] = frozenset(
    {
        "search_products",
        "search_available_products",
        "get_product_details",
        "admin_search_buyers",
        "admin_get_buyer_details",
        "admin_search_orders",
        "admin_get_order_details",
        "admin_search_inventory",
        "admin_search_pricing",
    }
)

ROLE_TOOLS: Final[dict[UserRole, frozenset[str]]] = {
    "customer": CUSTOMER_RETAILER_TOOLS,
    "retailer": CUSTOMER_RETAILER_TOOLS,
    "admin": ADMIN_TOOLS,
}


def normalize_role(role: str) -> UserRole:
    normalized = role.strip().lower()
    if normalized not in ROLE_TOOLS:
        raise ValueError("role must be customer, retailer, or admin")
    return cast(UserRole, normalized)


def allowed_tool_names(role: str) -> frozenset[str]:
    return ROLE_TOOLS[normalize_role(role)]


def tool_definitions_for_role(role: str) -> list[dict[str, Any]]:
    allowed = allowed_tool_names(role)
    return [
        definition
        for definition in load_tool_definitions()
        if definition["function"]["name"] in allowed
    ]


def execute_session_tool(
    session: ChatSession,
    name: str,
    arguments: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute only a tool exposed to this session's trusted role."""

    if name not in allowed_tool_names(session.role):
        return access_denied()
    return execute_tool(name, arguments, session.request_context())


def rag_enabled(role: str) -> bool:
    """The project knowledge base is intentionally open to every chat role."""

    normalize_role(role)
    return True
