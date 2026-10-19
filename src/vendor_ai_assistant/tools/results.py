"""Common JSON-safe tool result construction."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final, Iterable, Mapping


STATUSES: Final[set[str]] = {
    "success",
    "no_results",
    "ambiguous",
    "needs_clarification",
    "authentication_required",
    "access_denied",
    "invalid_request",
    "error",
}
ACCESS_DENIED_MESSAGE: Final[str] = "This data is not available for your account."


def json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def make_result(
    status: str,
    *,
    data: Iterable[Mapping[str, Any]] | None = None,
    message: str = "",
    missing_fields: Iterable[str] | None = None,
    candidates: Iterable[Mapping[str, Any]] | None = None,
    filters_applied: Mapping[str, Any] | None = None,
    limit: int = 20,
    offset: int = 0,
    has_more: bool = False,
    data_timestamp: str | None = None,
) -> dict[str, Any]:
    if status not in STATUSES:
        raise ValueError(f"Unsupported tool status: {status}")
    safe_data = json_safe(list(data or []))
    safe_candidates = json_safe(list(candidates or []))
    return {
        "status": status,
        "data": safe_data,
        "message": message,
        "missing_fields": list(missing_fields or []),
        "candidates": safe_candidates,
        "metadata": {
            "filters_applied": json_safe(dict(filters_applied or {})),
            "limit": limit,
            "offset": offset,
            "returned_count": len(safe_data),
            "has_more": bool(has_more),
            "data_timestamp": data_timestamp,
        },
    }


def access_denied(*, limit: int = 20, offset: int = 0) -> dict[str, Any]:
    return make_result(
        "access_denied", message=ACCESS_DENIED_MESSAGE, limit=limit, offset=offset
    )


def authentication_required(*, limit: int = 20, offset: int = 0) -> dict[str, Any]:
    return make_result(
        "authentication_required",
        message="Authentication is required to access this data.",
        limit=limit,
        offset=offset,
    )

