"""Account-scoped price quote handler."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from vendor_ai_assistant.tools.database import fetch_all, fetch_one, read_only_connection
from vendor_ai_assistant.tools.handlers.products import resolve_product_candidates
from vendor_ai_assistant.tools.results import access_denied, make_result
from vendor_ai_assistant.tools.validation import (
    authenticated_buyer_id,
    clean_text,
    parse_iso_date,
)


def get_price_quote(
    arguments: Mapping[str, Any], request_context: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    sku = clean_text(arguments, "sku")
    product_name = clean_text(arguments, "product_name")
    missing: list[str] = []
    if not sku and not product_name:
        missing.append("sku or product_name")
    quantity = arguments.get("quantity")
    if quantity is None:
        missing.append("quantity")
    if missing:
        return make_result(
            "needs_clarification",
            message="Additional information is required for a price quote.",
            missing_fields=missing,
            limit=1,
        )
    try:
        effective_date = parse_iso_date(arguments.get("effective_date")) or date.today()
    except ValueError:
        return make_result(
            "invalid_request", message="effective_date must use YYYY-MM-DD.", limit=1
        )

    buyer_id = authenticated_buyer_id(request_context)
    with read_only_connection() as connection:
        candidates = resolve_product_candidates(
            connection, sku=sku, product_name=product_name, limit=10
        )
        if not candidates:
            return make_result("no_results", message="No matching product was found.", limit=1)
        if len(candidates) > 1:
            public_candidates = [
                {
                    "sku": row["product_id"],
                    "product_name": row["product_name"],
                    "pack_size": row["pack_size"],
                    "unit_type": row["unit_type"],
                }
                for row in candidates[:10]
            ]
            return make_result(
                "ambiguous", message="Multiple products match. Select a SKU.",
                candidates=public_candidates, limit=10, has_more=len(candidates) > 10
            )

        if buyer_id:
            account = fetch_one(
                connection,
                "SELECT buyer_type, retailer_tier, status FROM dim_buyers WHERE buyer_id = ?",
                (buyer_id,),
            )
            if account is None:
                return access_denied(limit=1)
            if account["status"] != "Active":
                return access_denied(limit=1)
            buyer_type = account["buyer_type"]
            retailer_tier = account["retailer_tier"]
        else:
            buyer_type = "Customer"
            retailer_tier = "Not Applicable"

        product = candidates[0]
        pricing_rows = fetch_all(
            connection,
            "SELECT pricing_id, product_id, product_name, buyer_type, retailer_tier, "
            "minimum_quantity, maximum_quantity, quantity_slab, base_price_inr, "
            "discount_rate, net_unit_price_inr, valid_from, valid_to, "
            "_gold_processed_at FROM mart_pricing_catalog "
            "WHERE product_id = ? AND buyer_type = ? AND retailer_tier = ? "
            "AND status = 'Active' AND minimum_quantity <= ? "
            "AND (maximum_quantity IS NULL OR maximum_quantity >= ?) "
            "AND valid_from <= ? AND valid_to >= ? "
            "ORDER BY minimum_quantity DESC LIMIT 2",
            (
                product["product_id"], buyer_type, retailer_tier, quantity, quantity,
                effective_date.isoformat(), effective_date.isoformat(),
            ),
        )
    if not pricing_rows:
        return make_result(
            "no_results",
            message="No applicable price is available for the requested quantity and date.",
            filters_applied={
                "sku": product["product_id"], "quantity": quantity,
                "effective_date": effective_date.isoformat(),
            },
            limit=1,
        )
    if len(pricing_rows) > 1:
        return make_result(
            "error", message="A price quote could not be determined safely.", limit=1
        )
    row = pricing_rows[0]
    quote = {
        "sku": row["product_id"],
        "product_name": row["product_name"],
        "buyer_type": row["buyer_type"],
        "retailer_tier": row["retailer_tier"],
        "quantity": quantity,
        "quantity_slab": row["quantity_slab"],
        "base_price_inr": row["base_price_inr"],
        "discount_rate": row["discount_rate"],
        "net_unit_price_inr": row["net_unit_price_inr"],
        "valid_from": row["valid_from"],
        "valid_to": row["valid_to"],
        "subtotal_inr": round(float(row["net_unit_price_inr"]) * int(quantity), 2),
    }
    return make_result(
        "success",
        data=[quote],
        filters_applied={
            "sku": product["product_id"], "quantity": quantity,
            "effective_date": effective_date.isoformat(),
        },
        limit=1,
        data_timestamp=row["_gold_processed_at"],
    )
