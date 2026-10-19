"""Private repurchase suggestions based only on the authenticated buyer."""

from __future__ import annotations

from typing import Any, Mapping

from vendor_ai_assistant.tools.database import fetch_all, read_only_connection
from vendor_ai_assistant.tools.results import authentication_required, make_result
from vendor_ai_assistant.tools.validation import (
    authenticated_buyer_id,
    clean_text,
    pagination,
    parse_iso_date,
    verified_location,
)


def get_repurchase_suggestions(
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
    conditions = ["h.buyer_id = ?", "h.order_status = 'Delivered'"]
    parameters: list[Any] = [buyer_id]
    filters: dict[str, Any] = {}
    category = clean_text(arguments, "category")
    if category:
        conditions.append("h.category = ? COLLATE NOCASE")
        parameters.append(category)
        filters["category"] = category
    if date_from:
        conditions.append("h.order_date >= ?")
        parameters.append(date_from.isoformat())
        filters["date_from"] = date_from.isoformat()
    if date_to:
        conditions.append("h.order_date <= ?")
        parameters.append(date_to.isoformat())
        filters["date_to"] = date_to.isoformat()
    location = verified_location(request_context)
    availability_select = "NULL AS available_quantity, NULL AS availability_updated_at"
    availability_join = ""
    if location:
        filters["verified_location"] = location
        availability_select = "a.available_quantity, a.availability_updated_at"
        availability_join = (
            "LEFT JOIN (SELECT product_id, SUM(available_quantity) AS available_quantity, "
            "MAX(last_updated) AS availability_updated_at "
            "FROM mart_product_availability WHERE warehouse_city = ? COLLATE NOCASE "
            "GROUP BY product_id) a ON a.product_id = h.product_id"
        )
        parameters.append(location)
    sql = (
        "SELECT h.product_id, h.product_name, h.category, h.brand, "
        "COUNT(DISTINCT h.order_id) AS previous_order_count, "
        "SUM(h.quantity) AS previous_quantity, MAX(h.order_date) AS last_purchased_date, "
        "MAX(h._gold_processed_at) AS history_updated_at, "
        f"{availability_select} FROM mart_order_history h {availability_join} WHERE "
        + " AND ".join(conditions)
        + " GROUP BY h.product_id, h.product_name, h.category, h.brand "
        "ORDER BY last_purchased_date DESC, previous_order_count DESC, h.product_id "
        "LIMIT ? OFFSET ?"
    )
    # The availability subquery placeholder precedes WHERE placeholders.
    if location:
        parameters = [location, *parameters[:-1]]
    parameters.extend([limit + 1, offset])
    with read_only_connection() as connection:
        rows = fetch_all(connection, sql, parameters)
    has_more = len(rows) > limit
    rows = rows[:limit]
    if not rows:
        return make_result(
            "no_results", message="No eligible previous purchases were found.",
            filters_applied=filters, limit=limit, offset=offset
        )
    timestamps: list[str] = []
    data: list[dict[str, Any]] = []
    for row in rows:
        timestamps.append(row["history_updated_at"])
        item = {
            "sku": row["product_id"],
            "product_name": row["product_name"],
            "category": row["category"],
            "brand": row["brand"],
            "last_purchased_date": row["last_purchased_date"],
            "previous_order_count": row["previous_order_count"],
            "previous_quantity": row["previous_quantity"],
        }
        if location:
            item["verified_location"] = location
            item["available_quantity"] = row["available_quantity"] or 0
            item["in_stock"] = bool(row["available_quantity"] and row["available_quantity"] > 0)
            if row["availability_updated_at"]:
                timestamps.append(row["availability_updated_at"])
        data.append(item)
    return make_result(
        "success", data=data, filters_applied=filters, limit=limit, offset=offset,
        has_more=has_more, data_timestamp=max(timestamps)
    )
