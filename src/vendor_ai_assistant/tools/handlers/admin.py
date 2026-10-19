"""Explicit read-only tools available only to an authenticated admin."""

from __future__ import annotations

from typing import Any, Mapping

from vendor_ai_assistant.tools.database import (
    escape_like,
    fetch_all,
    fetch_one,
    read_only_connection,
)
from vendor_ai_assistant.tools.results import access_denied, make_result
from vendor_ai_assistant.tools.validation import (
    clean_text,
    is_authenticated_admin,
    pagination,
    parse_iso_date,
)


def _admin_denied(
    request_context: Mapping[str, Any] | None, limit: int = 20, offset: int = 0
) -> dict[str, Any] | None:
    if not is_authenticated_admin(request_context):
        return access_denied(limit=limit, offset=offset)
    return None


def _paged_result(
    rows: list[dict[str, Any]],
    *,
    filters: Mapping[str, Any],
    limit: int,
    offset: int,
    no_results_message: str,
) -> dict[str, Any]:
    has_more = len(rows) > limit
    rows = rows[:limit]
    if not rows:
        return make_result(
            "no_results",
            message=no_results_message,
            filters_applied=filters,
            limit=limit,
            offset=offset,
        )
    timestamps = [row.pop("_gold_processed_at") for row in rows]
    return make_result(
        "success",
        data=rows,
        filters_applied=filters,
        limit=limit,
        offset=offset,
        has_more=has_more,
        data_timestamp=max(timestamps),
    )


def admin_search_buyers(
    arguments: Mapping[str, Any], request_context: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    limit, offset = pagination(arguments)
    denied = _admin_denied(request_context, limit, offset)
    if denied:
        return denied

    conditions = ["1 = 1"]
    parameters: list[Any] = []
    filters: dict[str, Any] = {}
    query = clean_text(arguments, "query")
    if query:
        conditions.append(
            "(buyer_id = ? COLLATE NOCASE OR buyer_name LIKE ? ESCAPE '\\' COLLATE NOCASE)"
        )
        parameters.extend([query, f"%{escape_like(query)}%"])
        filters["query"] = query
    for field in ("buyer_type", "city", "state", "retailer_tier", "status"):
        value = clean_text(arguments, field)
        if value:
            conditions.append(f"{field} = ? COLLATE NOCASE")
            parameters.append(value)
            filters[field] = value
    parameters.extend([limit + 1, offset])
    sql = (
        "SELECT buyer_id, buyer_type, buyer_name, city, state, retailer_tier, "
        "credit_limit_inr, payment_terms, discount_group, status, _gold_processed_at "
        "FROM dim_buyers WHERE "
        + " AND ".join(conditions)
        + " ORDER BY buyer_type, buyer_name, buyer_id LIMIT ? OFFSET ?"
    )
    with read_only_connection() as connection:
        rows = fetch_all(connection, sql, parameters)
    return _paged_result(
        rows,
        filters=filters,
        limit=limit,
        offset=offset,
        no_results_message="No buyers match these filters.",
    )


def admin_get_buyer_details(
    arguments: Mapping[str, Any], request_context: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    denied = _admin_denied(request_context, limit=1)
    if denied:
        return denied
    buyer_id = clean_text(arguments, "buyer_id")
    if not buyer_id:
        return make_result(
            "needs_clarification",
            message="A buyer ID is required.",
            missing_fields=["buyer_id"],
            limit=1,
        )
    with read_only_connection() as connection:
        buyer = fetch_one(
            connection,
            "SELECT buyer_id, buyer_type, buyer_name, city, state, retailer_tier, "
            "credit_limit_inr, payment_terms, discount_group, status, "
            "_gold_processed_at FROM dim_buyers WHERE buyer_id = ? COLLATE NOCASE",
            (buyer_id,),
        )
        summary = fetch_one(
            connection,
            "SELECT COUNT(*) AS order_count, COALESCE(SUM(order_total_inr), 0) AS "
            "lifetime_order_value_inr, MAX(order_date) AS latest_order_date "
            "FROM fact_orders WHERE buyer_id = ? COLLATE NOCASE",
            (buyer_id,),
        )
    if buyer is None:
        return make_result(
            "no_results", message="No buyer matches that ID.", limit=1
        )
    timestamp = buyer.pop("_gold_processed_at")
    buyer["order_summary"] = summary
    return make_result(
        "success",
        data=[buyer],
        filters_applied={"buyer_id": buyer_id},
        limit=1,
        data_timestamp=timestamp,
    )


def admin_search_orders(
    arguments: Mapping[str, Any], request_context: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    limit, offset = pagination(arguments)
    denied = _admin_denied(request_context, limit, offset)
    if denied:
        return denied
    try:
        date_from = parse_iso_date(arguments.get("date_from"))
        date_to = parse_iso_date(arguments.get("date_to"))
    except ValueError:
        return make_result(
            "invalid_request",
            message="Dates must use YYYY-MM-DD.",
            limit=limit,
            offset=offset,
        )
    if date_from and date_to and date_from > date_to:
        return make_result(
            "invalid_request",
            message="date_from cannot be after date_to.",
            limit=limit,
            offset=offset,
        )

    conditions = ["1 = 1"]
    parameters: list[Any] = []
    filters: dict[str, Any] = {}
    for field, column in (
        ("order_id", "o.order_id"),
        ("buyer_id", "o.buyer_id"),
        ("order_status", "o.order_status"),
        ("payment_status", "o.payment_status"),
    ):
        value = clean_text(arguments, field)
        if value:
            conditions.append(f"{column} = ? COLLATE NOCASE")
            parameters.append(value)
            filters[field] = value
    buyer_name = clean_text(arguments, "buyer_name")
    if buyer_name:
        conditions.append("b.buyer_name LIKE ? ESCAPE '\\' COLLATE NOCASE")
        parameters.append(f"%{escape_like(buyer_name)}%")
        filters["buyer_name"] = buyer_name
    if date_from:
        conditions.append("o.order_date >= ?")
        parameters.append(date_from.isoformat())
        filters["date_from"] = date_from.isoformat()
    if date_to:
        conditions.append("o.order_date <= ?")
        parameters.append(date_to.isoformat())
        filters["date_to"] = date_to.isoformat()
    parameters.extend([limit + 1, offset])
    sql = (
        "SELECT o.order_id, o.buyer_id, b.buyer_name, o.buyer_type, "
        "o.warehouse_id, w.warehouse_city, o.order_date, o.order_status, "
        "o.payment_status, o.destination_city, o.destination_state, "
        "o.gross_amount_inr, o.discount_amount_inr, o.taxable_amount_inr, "
        "o.tax_amount_inr, o.order_total_inr, o._gold_processed_at "
        "FROM fact_orders o JOIN dim_buyers b ON b.buyer_id = o.buyer_id "
        "LEFT JOIN dim_warehouses w ON w.warehouse_id = o.warehouse_id WHERE "
        + " AND ".join(conditions)
        + " ORDER BY o.order_date DESC, o.order_id DESC LIMIT ? OFFSET ?"
    )
    with read_only_connection() as connection:
        rows = fetch_all(connection, sql, parameters)
    return _paged_result(
        rows,
        filters=filters,
        limit=limit,
        offset=offset,
        no_results_message="No orders match these filters.",
    )


def admin_get_order_details(
    arguments: Mapping[str, Any], request_context: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    denied = _admin_denied(request_context, limit=1)
    if denied:
        return denied
    order_id = clean_text(arguments, "order_id")
    if not order_id:
        return make_result(
            "needs_clarification",
            message="An order ID is required.",
            missing_fields=["order_id"],
            limit=1,
        )
    with read_only_connection() as connection:
        order = fetch_one(
            connection,
            "SELECT o.*, b.buyer_name, b.city AS buyer_city, b.state AS buyer_state, "
            "b.retailer_tier, w.warehouse_city, w.region FROM fact_orders o "
            "JOIN dim_buyers b ON b.buyer_id = o.buyer_id "
            "LEFT JOIN dim_warehouses w ON w.warehouse_id = o.warehouse_id "
            "WHERE o.order_id = ? COLLATE NOCASE",
            (order_id,),
        )
        if order is None:
            return make_result(
                "no_results", message="No order matches that ID.", limit=1
            )
        items = fetch_all(
            connection,
            "SELECT i.line_item_number, i.product_id, p.product_name, p.category, "
            "p.brand, i.quantity, i.historical_unit_price_inr, i.gross_amount_inr, "
            "i.discount_rate, i.discount_amount_inr, i.taxable_amount_inr, "
            "i.tax_rate, i.tax_amount_inr, i.line_total_inr FROM fact_order_items i "
            "JOIN dim_products p ON p.product_id = i.product_id "
            "WHERE i.order_id = ? ORDER BY i.line_item_number",
            (order_id,),
        )
        shipments = fetch_all(
            connection,
            "SELECT shipment_id, warehouse_id, shipping_method, carrier, "
            "tracking_number, shipment_date, expected_delivery_date, delivery_date, "
            "destination_city, destination_state FROM fact_shipments "
            "WHERE order_id = ? ORDER BY shipment_id",
            (order_id,),
        )
    timestamp = order.pop("_gold_processed_at")
    order["items"] = items
    order["shipments"] = shipments
    return make_result(
        "success",
        data=[order],
        filters_applied={"order_id": order_id},
        limit=1,
        data_timestamp=timestamp,
    )


def admin_search_inventory(
    arguments: Mapping[str, Any], request_context: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    limit, offset = pagination(arguments)
    denied = _admin_denied(request_context, limit, offset)
    if denied:
        return denied
    conditions = ["1 = 1"]
    parameters: list[Any] = []
    filters: dict[str, Any] = {}
    query = clean_text(arguments, "query")
    if query:
        conditions.append(
            "(product_id = ? COLLATE NOCASE OR product_name LIKE ? ESCAPE '\\' "
            "COLLATE NOCASE)"
        )
        parameters.extend([query, f"%{escape_like(query)}%"])
        filters["query"] = query
    for field in ("warehouse_city", "region"):
        value = clean_text(arguments, field)
        if value:
            conditions.append(f"{field} = ? COLLATE NOCASE")
            parameters.append(value)
            filters[field] = value
    if arguments.get("low_stock_only") is True:
        conditions.append("is_low_stock = 1")
        filters["low_stock_only"] = True
    parameters.extend([limit + 1, offset])
    sql = (
        "SELECT product_id, product_name, category, brand, pack_size, unit_type, "
        "warehouse_id, warehouse_city, region, quantity_on_hand, reserved_quantity, "
        "available_quantity, reorder_level, is_low_stock, last_updated, "
        "_gold_processed_at FROM mart_product_availability WHERE "
        + " AND ".join(conditions)
        + " ORDER BY is_low_stock DESC, available_quantity, product_id, warehouse_id "
        "LIMIT ? OFFSET ?"
    )
    with read_only_connection() as connection:
        rows = fetch_all(connection, sql, parameters)
    return _paged_result(
        rows,
        filters=filters,
        limit=limit,
        offset=offset,
        no_results_message="No inventory records match these filters.",
    )


def admin_search_pricing(
    arguments: Mapping[str, Any], request_context: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    limit, offset = pagination(arguments)
    denied = _admin_denied(request_context, limit, offset)
    if denied:
        return denied
    conditions = ["1 = 1"]
    parameters: list[Any] = []
    filters: dict[str, Any] = {}
    query = clean_text(arguments, "query")
    if query:
        conditions.append(
            "(product_id = ? COLLATE NOCASE OR product_name LIKE ? ESCAPE '\\' "
            "COLLATE NOCASE)"
        )
        parameters.extend([query, f"%{escape_like(query)}%"])
        filters["query"] = query
    for field in ("buyer_type", "retailer_tier", "status"):
        value = clean_text(arguments, field)
        if value:
            conditions.append(f"{field} = ? COLLATE NOCASE")
            parameters.append(value)
            filters[field] = value
    if arguments.get("current_only") is True:
        conditions.append("is_current = 1")
        filters["current_only"] = True
    parameters.extend([limit + 1, offset])
    sql = (
        "SELECT pricing_id, product_id, product_name, category, brand, pack_size, "
        "unit_type, buyer_type, retailer_tier, minimum_quantity, maximum_quantity, "
        "quantity_slab, base_price_inr, discount_rate, net_unit_price_inr, "
        "valid_from, valid_to, status, is_current, _gold_processed_at "
        "FROM mart_pricing_catalog WHERE "
        + " AND ".join(conditions)
        + " ORDER BY product_id, buyer_type, retailer_tier, minimum_quantity "
        "LIMIT ? OFFSET ?"
    )
    with read_only_connection() as connection:
        rows = fetch_all(connection, sql, parameters)
    return _paged_result(
        rows,
        filters=filters,
        limit=limit,
        offset=offset,
        no_results_message="No pricing records match these filters.",
    )
