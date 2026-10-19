"""Create verified role sessions for a future Gradio interface."""

from __future__ import annotations

from typing import Any

from vendor_ai_assistant.chat.models import ChatSession
from vendor_ai_assistant.chat.roles import normalize_role
from vendor_ai_assistant.tools.database import fetch_all, fetch_one, read_only_connection


def list_buyers_for_role(role: str) -> list[dict[str, Any]]:
    """Return active accounts suitable for a local Gradio account selector."""

    normalized_role = normalize_role(role)
    if normalized_role == "admin":
        return []
    buyer_type = normalized_role.title()
    with read_only_connection() as connection:
        return fetch_all(
            connection,
            "SELECT buyer_id, buyer_name, buyer_type, city, state, retailer_tier "
            "FROM dim_buyers WHERE buyer_type = ? AND status = 'Active' "
            "ORDER BY buyer_name, buyer_id",
            (buyer_type,),
        )


def create_chat_session(
    role: str,
    *,
    buyer_id: str | None = None,
    admin_principal_id: str = "ADMIN-DEMO",
) -> ChatSession:
    """Verify the selected identity and return state ready for ``gr.State``."""

    normalized_role = normalize_role(role)
    if normalized_role == "admin":
        if buyer_id is not None:
            raise ValueError("admin sessions do not accept a buyer_id")
        if not admin_principal_id.strip():
            raise ValueError("admin_principal_id is required")
        return ChatSession(
            role="admin",
            principal_id=admin_principal_id.strip(),
        )

    selected_buyer_id = buyer_id.strip() if isinstance(buyer_id, str) else ""
    if not selected_buyer_id:
        raise ValueError("a buyer_id is required for customer and retailer sessions")
    with read_only_connection() as connection:
        account = fetch_one(
            connection,
            "SELECT buyer_id, buyer_type, status FROM dim_buyers "
            "WHERE buyer_id = ? COLLATE NOCASE",
            (selected_buyer_id,),
        )
    if account is None:
        raise ValueError("the selected buyer account does not exist")
    if account["status"] != "Active":
        raise ValueError("the selected buyer account is not active")
    if account["buyer_type"].lower() != normalized_role:
        raise ValueError("the selected buyer account does not match the chosen role")

    verified_buyer_id = account["buyer_id"]
    return ChatSession(
        role=normalized_role,
        principal_id=verified_buyer_id,
        buyer_id=verified_buyer_id,
    )
