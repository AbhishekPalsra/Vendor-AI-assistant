"""Authenticated account retrieval handler."""

from __future__ import annotations

from typing import Any, Mapping

from vendor_ai_assistant.tools.database import fetch_one, read_only_connection
from vendor_ai_assistant.tools.results import access_denied, authentication_required, make_result
from vendor_ai_assistant.tools.validation import authenticated_buyer_id


def get_my_account(
    arguments: Mapping[str, Any], request_context: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    del arguments
    buyer_id = authenticated_buyer_id(request_context)
    if not buyer_id:
        return authentication_required(limit=1)
    with read_only_connection() as connection:
        row = fetch_one(
            connection,
            "SELECT buyer_id, buyer_type, buyer_name, city, state, retailer_tier, "
            "credit_limit_inr, payment_terms, discount_group, status, "
            "_gold_processed_at FROM dim_buyers WHERE buyer_id = ?",
            (buyer_id,),
        )
    if row is None:
        return access_denied(limit=1)
    data = {
        "buyer_id": row["buyer_id"],
        "buyer_type": row["buyer_type"],
        "name": row["buyer_name"],
        "city": row["city"],
        "state": row["state"],
        "retailer_tier": row["retailer_tier"],
        "credit_limit_inr": row["credit_limit_inr"],
        "payment_terms": row["payment_terms"],
        "discount_group": row["discount_group"],
        "status": row["status"],
    }
    return make_result(
        "success", data=[data], limit=1, data_timestamp=row["_gold_processed_at"]
    )

