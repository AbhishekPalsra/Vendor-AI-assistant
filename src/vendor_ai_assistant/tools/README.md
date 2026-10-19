# Database retrieval tools

This package contains eight allowlisted, read-only business tools for a future
customer and retailer chatbot. It does not contain an OpenAI client,
orchestrator, conversation loop, RAG system, UI, or database writes.

Definitions in `definitions/` are ready for a future OpenAI `tools` parameter:

```python
from vendor_ai_assistant.tools import load_tool_definitions

tools = load_tool_definitions()
```

Execute an approved handler through the registry while keeping trusted context
separate from model-generated arguments:

```python
from vendor_ai_assistant.tools import execute_tool

result = execute_tool(
    "get_order_history",
    {"limit": 10},
    {"authenticated": True, "buyer_id": "RET-00001"},
)
```

Connections use SQLite read-only mode and parameterized queries. Protected
handlers derive buyer identity, account type, retailer tier, and verified
location exclusively from trusted `request_context`. Result objects use the
shared status/data/message/candidates/metadata structure.

Run the tests from the project root:

```powershell
uv run python -m unittest discover -s tests -v
```

