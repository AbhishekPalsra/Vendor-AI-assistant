"""Product catalog and availability handlers."""

from __future__ import annotations

from typing import Any, Mapping

from vendor_ai_assistant.tools.database import escape_like, fetch_all, read_only_connection
from vendor_ai_assistant.tools.results import make_result
from vendor_ai_assistant.tools.validation import clean_text, pagination, verified_location


PRODUCT_FIELDS = (
    "product_id, product_name, category, brand, pack_size, unit_type, "
    "_gold_processed_at"
)


def resolve_product_candidates(
    connection: object, *, sku: str | None, product_name: str | None, limit: int = 10
) -> list[dict[str, Any]]:
    if sku:
        return fetch_all(
            connection,  # type: ignore[arg-type]
            f"SELECT {PRODUCT_FIELDS} FROM dim_products WHERE product_id = ? COLLATE NOCASE",
            (sku,),
        )
    if not product_name:
        return []
    exact = fetch_all(
        connection,  # type: ignore[arg-type]
        f"SELECT {PRODUCT_FIELDS} FROM dim_products "
        "WHERE product_name = ? COLLATE NOCASE ORDER BY product_id LIMIT ?",
        (product_name, limit + 1),
    )
    if exact:
        return exact
    return fetch_all(
        connection,  # type: ignore[arg-type]
        f"SELECT {PRODUCT_FIELDS} FROM dim_products "
        "WHERE product_name LIKE ? ESCAPE '\\' COLLATE NOCASE "
        "ORDER BY product_name, product_id LIMIT ?",
        (f"%{escape_like(product_name)}%", limit + 1),
    )


def _public_product(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "sku": row["product_id"],
        "product_name": row["product_name"],
        "category": row["category"],
        "brand": row["brand"],
        "pack_size": row["pack_size"],
        "unit_type": row["unit_type"],
    }


def search_products(
    arguments: Mapping[str, Any], request_context: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    del request_context
    limit, offset = pagination(arguments)
    filters = {
        name: value
        for name in ("query", "category", "brand", "pack_size", "unit_type")
        if (value := arguments.get(name)) not in (None, "")
    }
    if not filters:
        return make_result(
            "needs_clarification",
            message="Provide at least one product search field.",
            missing_fields=["query, category, brand, pack_size, or unit_type"],
            limit=limit,
            offset=offset,
        )
    conditions: list[str] = []
    parameters: list[Any] = []
    query = clean_text(arguments, "query")
    if query:
        pattern = f"%{escape_like(query)}%"
        conditions.append(
            "(product_id = ? COLLATE NOCASE OR product_name LIKE ? ESCAPE '\\' COLLATE NOCASE)"
        )
        parameters.extend([query, pattern])
    for field in ("category", "brand", "unit_type"):
        value = clean_text(arguments, field)
        if value:
            conditions.append(f"{field} = ? COLLATE NOCASE")
            parameters.append(value)
    if arguments.get("pack_size") is not None:
        conditions.append("pack_size = ?")
        parameters.append(arguments["pack_size"])
    sql = (
        f"SELECT {PRODUCT_FIELDS} FROM dim_products WHERE "
        + " AND ".join(conditions)
        + " ORDER BY product_name, product_id LIMIT ? OFFSET ?"
    )
    parameters.extend([limit + 1, offset])
    with read_only_connection() as connection:
        rows = fetch_all(connection, sql, parameters)
    has_more = len(rows) > limit
    rows = rows[:limit]
    if not rows:
        return make_result(
            "no_results", message="No matching products were found.",
            filters_applied=filters, limit=limit, offset=offset
        )
    candidates = [_public_product(row) for row in rows]
    timestamp = max(row["_gold_processed_at"] for row in rows)
    if len(rows) > 1:
        return make_result(
            "ambiguous",
            message="Multiple products or pack sizes match. Select a SKU.",
            candidates=candidates,
            filters_applied=filters,
            limit=limit,
            offset=offset,
            has_more=has_more,
            data_timestamp=timestamp,
        )
    return make_result(
        "success", data=candidates, filters_applied=filters, limit=limit,
        offset=offset, has_more=has_more, data_timestamp=timestamp
    )


def search_available_products(
    arguments: Mapping[str, Any], request_context: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    limit, offset = pagination(arguments)
    location = clean_text(arguments, "warehouse_city") or verified_location(request_context)
    if not location:
        return make_result(
            "needs_clarification",
            message="A warehouse city or verified location is required.",
            missing_fields=["warehouse_city"],
            limit=limit,
            offset=offset,
        )
    conditions = ["warehouse_city = ? COLLATE NOCASE"]
    parameters: list[Any] = [location]
    filters: dict[str, Any] = {"warehouse_city": location}
    query = clean_text(arguments, "query")
    if query:
        conditions.append(
            "(product_id = ? COLLATE NOCASE OR product_name LIKE ? ESCAPE '\\' COLLATE NOCASE)"
        )
        parameters.extend([query, f"%{escape_like(query)}%"])
        filters["query"] = query
    for field in ("category", "brand"):
        value = clean_text(arguments, field)
        if value:
            conditions.append(f"{field} = ? COLLATE NOCASE")
            parameters.append(value)
            filters[field] = value
    in_stock_only = arguments.get("in_stock_only", True)
    filters["in_stock_only"] = in_stock_only
    if in_stock_only:
        conditions.append("available_quantity > 0")
    sql = (
        "SELECT product_id, product_name, category, brand, pack_size, unit_type, "
        "warehouse_city, region, available_quantity, is_low_stock, last_updated, "
        "_gold_processed_at FROM mart_product_availability WHERE "
        + " AND ".join(conditions)
        + " ORDER BY product_name, product_id LIMIT ? OFFSET ?"
    )
    parameters.extend([limit + 1, offset])
    with read_only_connection() as connection:
        rows = fetch_all(connection, sql, parameters)
    has_more = len(rows) > limit
    rows = rows[:limit]
    if not rows:
        return make_result(
            "no_results", message="No matching availability was found.",
            filters_applied=filters, limit=limit, offset=offset
        )
    data = [
        {
            "sku": row["product_id"],
            "product_name": row["product_name"],
            "category": row["category"],
            "brand": row["brand"],
            "pack_size": row["pack_size"],
            "unit_type": row["unit_type"],
            "warehouse_city": row["warehouse_city"],
            "region": row["region"],
            "available_quantity": row["available_quantity"],
            "in_stock": row["available_quantity"] > 0,
            "low_stock": bool(row["is_low_stock"]),
            "last_updated": row["last_updated"],
        }
        for row in rows
    ]
    return make_result(
        "success", data=data, filters_applied=filters, limit=limit, offset=offset,
        has_more=has_more,
        data_timestamp=max(row["_gold_processed_at"] for row in rows),
    )


def get_product_details(
    arguments: Mapping[str, Any], request_context: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    del request_context
    sku = clean_text(arguments, "sku")
    product_name = clean_text(arguments, "product_name")
    if not sku and not product_name:
        return make_result(
            "needs_clarification",
            message="Provide a SKU or product name.",
            missing_fields=["sku or product_name"],
            limit=10,
        )
    with read_only_connection() as connection:
        rows = resolve_product_candidates(
            connection, sku=sku, product_name=product_name, limit=10
        )
    if not rows:
        return make_result("no_results", message="No matching product was found.", limit=10)
    candidates = [_public_product(row) for row in rows[:10]]
    timestamp = max(row["_gold_processed_at"] for row in rows[:10])
    if len(rows) > 1:
        return make_result(
            "ambiguous", message="Multiple products match. Select a SKU.",
            candidates=candidates, limit=10, has_more=len(rows) > 10,
            data_timestamp=timestamp
        )
    return make_result("success", data=candidates, limit=10, data_timestamp=timestamp)
