"""Definition, model-argument, context, pagination, and date validation."""

from __future__ import annotations

from datetime import date
from typing import Any, Final, Mapping


DEFAULT_LIMIT: Final[int] = 20
MAX_LIMIT: Final[int] = 50
MAX_TEXT_LENGTH: Final[int] = 200


def validate_tool_definition(definition: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if definition.get("type") != "function":
        errors.append("type must be function")
    function = definition.get("function")
    if not isinstance(function, Mapping):
        return [*errors, "function must be an object"]
    if not isinstance(function.get("name"), str) or not function.get("name"):
        errors.append("function.name must be a non-empty string")
    if not isinstance(function.get("description"), str):
        errors.append("function.description must be a string")
    parameters = function.get("parameters")
    if not isinstance(parameters, Mapping) or parameters.get("type") != "object":
        errors.append("function.parameters must be an object schema")
    elif parameters.get("additionalProperties") is not False:
        errors.append("function.parameters.additionalProperties must be false")
    return errors


def validate_arguments(
    definition: Mapping[str, Any], arguments: Any
) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(arguments, Mapping):
        return {}, ["arguments must be an object"]
    normalized = dict(arguments)
    parameters = definition["function"]["parameters"]
    properties = parameters.get("properties", {})
    required = parameters.get("required", [])
    errors = [f"missing required argument: {name}" for name in required if name not in normalized]
    unknown = sorted(set(normalized) - set(properties))
    if unknown:
        errors.append("unsupported argument(s): " + ", ".join(unknown))
    for name, value in normalized.items():
        schema = properties.get(name)
        if schema is None or value is None:
            continue
        expected = schema.get("type")
        valid_type = {
            "string": isinstance(value, str),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
        }.get(expected, True)
        if not valid_type:
            errors.append(f"{name} must be {expected}")
            continue
        if isinstance(value, str):
            if len(value.strip()) > schema.get("maxLength", MAX_TEXT_LENGTH):
                errors.append(f"{name} is too long")
            if value == "" and schema.get("minLength", 0) > 0:
                errors.append(f"{name} cannot be empty")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in schema and value < schema["minimum"]:
                errors.append(f"{name} is below the minimum")
            if "maximum" in schema and value > schema["maximum"]:
                errors.append(f"{name} exceeds the maximum")
        if "enum" in schema and value not in schema["enum"]:
            errors.append(f"{name} has an unsupported value")
    return normalized, errors


def pagination(arguments: Mapping[str, Any]) -> tuple[int, int]:
    return int(arguments.get("limit", DEFAULT_LIMIT)), int(arguments.get("offset", 0))


def clean_text(arguments: Mapping[str, Any], field: str) -> str | None:
    value = arguments.get(field)
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def parse_iso_date(value: Any) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("date must be an ISO YYYY-MM-DD string")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("date must be an ISO YYYY-MM-DD string") from error


def authenticated_buyer_id(request_context: Mapping[str, Any] | None) -> str | None:
    context = request_context or {}
    authenticated = context.get("authenticated", context.get("is_authenticated", False))
    buyer_id = context.get("buyer_id")
    if authenticated is not True or not isinstance(buyer_id, str) or not buyer_id.strip():
        return None
    return buyer_id.strip()


def is_authenticated_admin(request_context: Mapping[str, Any] | None) -> bool:
    context = request_context or {}
    role = context.get("role")
    return context.get("authenticated") is True and (
        isinstance(role, str) and role.strip().lower() == "admin"
    )


def verified_location(request_context: Mapping[str, Any] | None) -> str | None:
    context = request_context or {}
    value = context.get("verified_location", context.get("warehouse_city"))
    if isinstance(value, Mapping):
        value = value.get("warehouse_city", value.get("city"))
    return value.strip() if isinstance(value, str) and value.strip() else None
