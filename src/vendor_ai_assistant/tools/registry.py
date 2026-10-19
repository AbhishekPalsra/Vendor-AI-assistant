"""Allowlisted tool-handler registry and safe execution entry point."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any, Final

from vendor_ai_assistant.tools.handlers.admin import (
    admin_get_buyer_details,
    admin_get_order_details,
    admin_search_buyers,
    admin_search_inventory,
    admin_search_orders,
    admin_search_pricing,
)
from vendor_ai_assistant.tools.handlers.accounts import get_my_account
from vendor_ai_assistant.tools.handlers.orders import get_order_history, get_order_status
from vendor_ai_assistant.tools.handlers.pricing import get_price_quote
from vendor_ai_assistant.tools.handlers.products import (
    get_product_details,
    search_available_products,
    search_products,
)
from vendor_ai_assistant.tools.handlers.recommendations import get_repurchase_suggestions
from vendor_ai_assistant.tools.loader import definitions_by_name
from vendor_ai_assistant.tools.results import make_result
from vendor_ai_assistant.tools.validation import validate_arguments


Handler = Callable[[Mapping[str, Any], Mapping[str, Any] | None], dict[str, Any]]

HANDLERS: Final[dict[str, Handler]] = {
    "admin_search_buyers": admin_search_buyers,
    "admin_get_buyer_details": admin_get_buyer_details,
    "admin_search_orders": admin_search_orders,
    "admin_get_order_details": admin_get_order_details,
    "admin_search_inventory": admin_search_inventory,
    "admin_search_pricing": admin_search_pricing,
    "search_products": search_products,
    "search_available_products": search_available_products,
    "get_product_details": get_product_details,
    "get_price_quote": get_price_quote,
    "get_my_account": get_my_account,
    "get_order_status": get_order_status,
    "get_order_history": get_order_history,
    "get_repurchase_suggestions": get_repurchase_suggestions,
}


def get_registered_tool_names() -> tuple[str, ...]:
    return tuple(HANDLERS)


def validate_registry() -> None:
    definitions = definitions_by_name()
    if set(definitions) != set(HANDLERS):
        missing_handlers = sorted(set(definitions) - set(HANDLERS))
        missing_definitions = sorted(set(HANDLERS) - set(definitions))
        raise RuntimeError(
            f"Tool registry mismatch: missing_handlers={missing_handlers}, "
            f"missing_definitions={missing_definitions}"
        )


def execute_tool(
    name: str,
    arguments: Mapping[str, Any] | None = None,
    request_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    handler = HANDLERS.get(name)
    if handler is None:
        return make_result("invalid_request", message="This tool is not available.")
    definitions = definitions_by_name()
    supplied_arguments: Any = {} if arguments is None else arguments
    normalized, errors = validate_arguments(definitions[name], supplied_arguments)
    if errors:
        return make_result(
            "invalid_request",
            message="Invalid tool arguments: " + "; ".join(errors),
            limit=int(normalized.get("limit", 20)) if isinstance(normalized.get("limit", 20), int) else 20,
            offset=int(normalized.get("offset", 0)) if isinstance(normalized.get("offset", 0), int) else 0,
        )
    try:
        result = handler(normalized, request_context)
        json.dumps(result)
        return result
    except Exception:
        return make_result(
            "error", message="The requested data could not be retrieved safely."
        )


validate_registry()
