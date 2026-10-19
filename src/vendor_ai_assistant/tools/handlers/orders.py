"""Authenticated order status and history handlers."""

from __future__ import annotations

from typing import Any, Mapping

from vendor_ai_assistant.tools.database import escape_like, fetch_all, fetch_one, read_only_connection
from vendor_ai_assistant.tools.results import access_denied, authentication_required, make_result
from vendor_ai_assistant.tools.validation import (
    authenticated_buyer_id,
    clean_text,
    pagination,
    parse_iso_date,
)


def get_order_status(
    arguments: Mapping[str, Any], request_context: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    buyer_id = authenticated_buyer_id(request_context)
    if not buyer_id:
        return authentication_required(limit=1)
    order_id = clean_text(arguments, "order_id")
    if not order_id:
        return make_result(
            "needs_clarification", message="An order ID is required.",
            missing_fields=["order_id"], limit=1
        )
    with read_only_connection() as connection:
        order = fetch_one(
            connection,
            "SELECT order_id, order_date, order_status, payment_status, "
            "destination_city, destination_state, order_total_inr, "
            "_gold_processed_at FROM fact_orders WHERE order_id = ? AND buyer_id = ?",
            (order_id, buyer_id),
        )
        if order is None:
            return access_denied(limit=1)
        shipments = fetch_all(
            connection,
            "SELECT shipment_id, shipping_method, carrier, tracking_number, "
            "shipment_date, expected_delivery_date, delivery_date "
            "FROM fact_shipments WHERE order_id = ? ORDER BY shipment_id",
            (order_id,),
        )
    data = {
        "order_id": order["order_id"],
        "order_date": order["order_date"],
        "order_status": order["order_status"],
        "payment_status": order["payment_status"],
        "destination_city": order["destination_city"],
        "destination_state": order["destination_state"],
        "order_total_inr": order["order_total_inr"],
        "shipment_status": "not_shipped" if not shipments else "shipment_records_available",
        "shipments": shipments,
    }
    return make_result(
        "success", data=[data], filters_applied={"order_id": order_id}, limit=1,
        data_timestamp=order["_gold_processed_at"]
    )


def get_order_history(
    arguments: Mapping[str, Any], request_context: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    limit, offset = pagination(arguments)
    buyer_id = authenticated_buyer_id(request_context)
    if not buyer_id:
        return authentication_required(limit=limit, offset=offset)
    try:
        date_from = parse_iso_date(arguments.get("date_from"))
        date_to = parse_iso_date(arguments.get("date_to"))
    except ValueError:
        return make_result(
            "invalid_request", message="Dates must use YYYY-MM-DD.",
            limit=limit, offset=offset
        )
    if date_from and date_to and date_from > date_to:
        return make_result(
            "invalid_request", message="date_from cannot be after date_to.",
            limit=limit, offset=offset
        )
    conditions = ["buyer_id = ?"]
    parameters: list[Any] = [buyer_id]
    filters: dict[str, Any] = {}
    if date_from:
        conditions.append("order_date >= ?")
        parameters.append(date_from.isoformat())
        filters["date_from"] = date_from.isoformat()
    if date_to:
        conditions.append("order_date <= ?")
        parameters.append(date_to.isoformat())
        filters["date_to"] = date_to.isoformat()
    for field in ("order_status", "payment_status"):
        value = clean_text(arguments, field)
        if value:
            conditions.append(f"{field} = ? COLLATE NOCASE")
            parameters.append(value)
            filters[field] = value
    product_filter = clean_text(arguments, "product")
    if product_filter:
        conditions.append(
            "(product_id = ? COLLATE NOCASE OR product_name LIKE ? ESCAPE '\\' COLLATE NOCASE)"
        )
        parameters.extend([product_filter, f"%{escape_like(product_filter)}%"])
        filters["product"] = product_filter
    sql = (
        "SELECT order_id, line_item_number, order_date, order_status, payment_status, "
        "product_id, product_name, category, brand, quantity, "
        "historical_unit_price_inr, discount_rate, discount_amount_inr, "
        "taxable_amount_inr, tax_rate, tax_amount_inr, line_total_inr, "
        "destination_city, destination_state, shipment_count, carriers, "
        "tracking_numbers, first_shipment_date, latest_expected_delivery_date, "
        "latest_delivery_date, _gold_processed_at FROM mart_order_history WHERE "
        + " AND ".join(conditions)
        + " ORDER BY order_date DESC, order_id DESC, line_item_number LIMIT ? OFFSET ?"
    )
    parameters.extend([limit + 1, offset])
    with read_only_connection() as connection:
        rows = fetch_all(connection, sql, parameters)
    has_more = len(rows) > limit
    rows = rows[:limit]
    if not rows:
        return make_result(
            "no_results", message="No order history matches these filters.",
            filters_applied=filters, limit=limit, offset=offset
        )
    timestamps = [row.pop("_gold_processed_at") for row in rows]
    for row in rows:
        row["sku"] = row.pop("product_id")
    return make_result(
        "success", data=rows, filters_applied=filters, limit=limit, offset=offset,
        has_more=has_more, data_timestamp=max(timestamps)
    )
