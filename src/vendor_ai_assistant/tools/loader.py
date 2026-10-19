"""Load validated OpenAI-compatible function-tool definitions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

from vendor_ai_assistant.tools.validation import validate_tool_definition


DEFINITIONS_DIR: Final[Path] = Path(__file__).resolve().parent / "definitions"


def load_tool_definitions() -> list[dict[str, Any]]:
    definitions: list[dict[str, Any]] = []
    names: set[str] = set()
    for path in sorted(DEFINITIONS_DIR.glob("*.json")):
        definition = json.loads(path.read_text(encoding="utf-8"))
        errors = validate_tool_definition(definition)
        if errors:
            raise ValueError(f"Invalid tool definition {path.name}: {'; '.join(errors)}")
        name = definition["function"]["name"]
        if name in names:
            raise ValueError(f"Duplicate tool definition: {name}")
        names.add(name)
        definitions.append(definition)
    return definitions


def definitions_by_name() -> dict[str, dict[str, Any]]:
    return {definition["function"]["name"]: definition for definition in load_tool_definitions()}
