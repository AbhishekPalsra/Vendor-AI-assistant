"""Network-free tests for the role-scoped database tool loop."""

from __future__ import annotations

import json
import unittest
from typing import Any

from vendor_ai_assistant.chat.models import ChatSession, DatabaseRequest
from vendor_ai_assistant.chat.tool_runner import TOOL_CALLING_MODEL, run_tool_loop
from vendor_ai_assistant.tools.results import make_result


def tool_response(*calls: tuple[str, str, Any]) -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": arguments},
                        }
                        for call_id, name, arguments in calls
                    ],
                }
            }
        ]
    }


def stop_response(content: str) -> dict[str, Any]:
    return {"choices": [{"message": {"content": content, "tool_calls": []}}]}


class SequencedCompletion:
    def __init__(self, *responses: dict[str, Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.responses.pop(0)


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[ChatSession, str, dict[str, Any]]] = []

    def __call__(
        self,
        session: ChatSession,
        name: str,
        arguments: dict[str, Any] | None,
    ) -> dict[str, Any]:
        normalized = dict(arguments or {})
        self.calls.append((session, name, normalized))
        if name == "search_products":
            return make_result(
                "success",
                data=[{"sku": "SKU-100", "product_name": "Fortune Sunflower Oil"}],
            )
        if name == "admin_search_buyers":
            return make_result(
                "success", data=[{"buyer_id": "BUY-100", "buyer_name": "A Store"}]
            )
        return make_result("success", data=[{"available_quantity": 25}])


class ToolRunnerTests(unittest.TestCase):
    @staticmethod
    def customer_session() -> ChatSession:
        return ChatSession(
            role="customer",
            principal_id="CUS-001",
            buyer_id="CUS-001",
        )

    @staticmethod
    def admin_session() -> ChatSession:
        return ChatSession(role="admin", principal_id="ADMIN-001")

    def test_customer_loop_chains_tools_until_model_stops(self) -> None:
        requests = (
            DatabaseRequest(
                query="Find Fortune oils currently available in Jaipur",
                purpose="Return current product availability",
                tool_names=("search_products", "search_available_products"),
            ),
        )
        completion = SequencedCompletion(
            tool_response(
                ("call-1", "search_products", json.dumps({"query": "Fortune oil"}))
            ),
            tool_response(
                (
                    "call-2",
                    "search_available_products",
                    json.dumps({"query": "SKU-100", "warehouse_city": "Jaipur"}),
                )
            ),
            stop_response("COMPLETE: Product identity and Jaipur stock were retrieved."),
        )
        executor = RecordingExecutor()

        result = run_tool_loop(
            requests,
            session=self.customer_session(),
            rewritten_query="Which Fortune oils are currently available in Jaipur?",
            original_query="fortune oil available here?",
            completion_fn=completion,
            executor=executor,
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.iterations, 3)
        self.assertEqual(len(result.executions), 2)
        self.assertTrue(all(item.executed for item in result.executions))
        self.assertEqual(
            [call[1] for call in executor.calls],
            ["search_products", "search_available_products"],
        )
        exposed = {
            item["function"]["name"] for item in completion.calls[0]["tools"]
        }
        self.assertEqual(
            exposed, {"search_products", "search_available_products"}
        )
        self.assertNotIn("admin_search_buyers", exposed)
        self.assertEqual(completion.calls[0]["model"], TOOL_CALLING_MODEL)
        second_messages = completion.calls[1]["messages"]
        self.assertEqual(second_messages[-1]["role"], "tool")
        self.assertIn("SKU-100", second_messages[-1]["content"])

    def test_admin_loop_uses_admin_tools_without_separate_runner(self) -> None:
        requests = (
            DatabaseRequest(
                query="Find buyer A Store and inspect its orders",
                purpose="Retrieve cross-buyer admin data",
                tool_names=("admin_search_buyers", "admin_search_orders"),
            ),
        )
        completion = SequencedCompletion(
            tool_response(
                (
                    "admin-1",
                    "admin_search_buyers",
                    json.dumps({"query": "A Store"}),
                ),
                (
                    "admin-2",
                    "admin_search_orders",
                    json.dumps({"buyer_id": "BUY-100"}),
                ),
            ),
            stop_response("COMPLETE: Buyer and order evidence were retrieved."),
        )
        executor = RecordingExecutor()

        result = run_tool_loop(
            requests,
            session=self.admin_session(),
            rewritten_query="Show A Store and its orders",
            completion_fn=completion,
            executor=executor,
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(len(result.executions), 2)
        self.assertTrue(
            all(execution.tool_name.startswith("admin_") for execution in result.executions)
        )
        self.assertTrue(all(call[0].role == "admin" for call in executor.calls))

    def test_customer_cannot_expose_admin_tool_from_request(self) -> None:
        requests = (
            DatabaseRequest(
                query="Show another buyer",
                purpose="Attempt cross-account access",
                tool_names=("admin_search_buyers",),
            ),
        )

        with self.assertRaisesRegex(ValueError, "unavailable to this role"):
            run_tool_loop(
                requests,
                session=self.customer_session(),
                rewritten_query="Show another buyer",
                completion_fn=lambda **kwargs: (_ for _ in ()).throw(
                    AssertionError("model must not be called")
                ),
            )

    def test_model_invented_tool_is_not_executed(self) -> None:
        request = DatabaseRequest(
            query="Find Fortune oil",
            purpose="Resolve a product",
            tool_names=("search_products",),
        )
        completion = SequencedCompletion(
            tool_response(("invented", "admin_search_buyers", "{}")),
            stop_response("COMPLETE: The unavailable call was rejected."),
        )
        executor = RecordingExecutor()

        result = run_tool_loop(
            (request,),
            session=self.customer_session(),
            rewritten_query="Find Fortune oil",
            completion_fn=completion,
            executor=executor,
        )

        self.assertEqual(executor.calls, [])
        self.assertFalse(result.executions[0].executed)
        self.assertEqual(result.executions[0].result["status"], "access_denied")

    def test_total_tool_call_limit_bounds_multi_call_response(self) -> None:
        request = DatabaseRequest(
            query="Find products",
            purpose="Test total tool-call limit",
            tool_names=("search_products",),
        )
        completion = SequencedCompletion(
            tool_response(
                ("first", "search_products", json.dumps({"query": "Oil"})),
                ("second", "search_products", json.dumps({"query": "Rice"})),
            )
        )
        executor = RecordingExecutor()

        result = run_tool_loop(
            (request,),
            session=self.customer_session(),
            rewritten_query="Find products",
            max_tool_calls=1,
            completion_fn=completion,
            executor=executor,
        )

        self.assertEqual(result.status, "max_iterations")
        self.assertEqual(result.stop_reason, "max_tool_calls_reached")
        self.assertEqual(len(executor.calls), 1)

    def test_empty_database_requests_skip_model_and_tools(self) -> None:
        def forbidden(*args, **kwargs):
            raise AssertionError("No model or tool call expected")

        result = run_tool_loop(
            (),
            session=self.customer_session(),
            rewritten_query="Only RAG is needed",
            completion_fn=forbidden,
            executor=forbidden,
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.iterations, 0)
        self.assertEqual(result.stop_reason, "no_database_requests")

    def test_malformed_arguments_are_returned_to_model_for_correction(self) -> None:
        requests = (
            DatabaseRequest(
                query="Find Fortune oil",
                purpose="Resolve the product",
                tool_names=("search_products",),
            ),
        )
        completion = SequencedCompletion(
            tool_response(("bad", "search_products", "{not-json")),
            tool_response(
                ("fixed", "search_products", json.dumps({"query": "Fortune oil"}))
            ),
            stop_response("COMPLETE: Product evidence was retrieved."),
        )
        executor = RecordingExecutor()

        result = run_tool_loop(
            requests,
            session=self.customer_session(),
            rewritten_query="Find Fortune oil",
            completion_fn=completion,
            executor=executor,
        )

        self.assertEqual(result.status, "completed")
        self.assertEqual(len(result.executions), 2)
        self.assertFalse(result.executions[0].executed)
        self.assertEqual(result.executions[0].result["status"], "invalid_request")
        self.assertTrue(result.executions[1].executed)
        self.assertEqual(len(executor.calls), 1)
        correction_messages = completion.calls[1]["messages"]
        self.assertIn("not valid JSON", correction_messages[-1]["content"])

    def test_duplicate_call_is_not_executed_twice(self) -> None:
        request = DatabaseRequest(
            query="Find Fortune oil",
            purpose="Resolve product",
            tool_names=("search_products",),
        )
        arguments = json.dumps({"query": "Fortune oil"})
        completion = SequencedCompletion(
            tool_response(("first", "search_products", arguments)),
            tool_response(("duplicate", "search_products", arguments)),
            stop_response("COMPLETE: Existing product evidence is sufficient."),
        )
        executor = RecordingExecutor()

        result = run_tool_loop(
            (request,),
            session=self.customer_session(),
            rewritten_query="Find Fortune oil",
            completion_fn=completion,
            executor=executor,
        )

        self.assertEqual(len(executor.calls), 1)
        self.assertEqual(len(result.executions), 2)
        self.assertFalse(result.executions[1].executed)
        self.assertIn("already executed", result.executions[1].result["message"])

    def test_iteration_limit_stops_runaway_loop(self) -> None:
        request = DatabaseRequest(
            query="Search products",
            purpose="Test bounded calls",
            tool_names=("search_products",),
        )
        completion = SequencedCompletion(
            tool_response(
                ("one", "search_products", json.dumps({"query": "Oil"}))
            ),
            tool_response(
                ("two", "search_products", json.dumps({"query": "Rice"}))
            ),
        )

        result = run_tool_loop(
            (request,),
            session=self.customer_session(),
            rewritten_query="Search products",
            max_iterations=2,
            completion_fn=completion,
            executor=RecordingExecutor(),
        )

        self.assertEqual(result.status, "max_iterations")
        self.assertEqual(result.stop_reason, "max_iterations_reached")
        self.assertEqual(len(result.executions), 2)

    def test_no_initial_tool_call_becomes_clarification(self) -> None:
        request = DatabaseRequest(
            query="Get the price",
            purpose="Retrieve a quote",
            tool_names=("get_price_quote",),
        )

        result = run_tool_loop(
            (request,),
            session=self.customer_session(),
            rewritten_query="Get the price",
            completion_fn=SequencedCompletion(
                stop_response("NEEDS_CLARIFICATION: Which product and quantity?")
            ),
        )

        self.assertEqual(result.status, "needs_clarification")
        self.assertEqual(
            result.clarification_question, "Which product and quantity?"
        )
        self.assertEqual(result.executions, ())

    def test_handler_exception_is_sanitized(self) -> None:
        request = DatabaseRequest(
            query="Find oil",
            purpose="Retrieve product",
            tool_names=("search_products",),
        )
        completion = SequencedCompletion(
            tool_response(
                ("failure", "search_products", json.dumps({"query": "Oil"}))
            ),
            stop_response("COMPLETE: The tool failure was recorded."),
        )

        def failing_executor(*args, **kwargs):
            raise RuntimeError("secret database detail")

        result = run_tool_loop(
            (request,),
            session=self.customer_session(),
            rewritten_query="Find oil",
            completion_fn=completion,
            executor=failing_executor,
        )

        encoded = result.model_dump_json()
        self.assertEqual(result.executions[0].result["status"], "error")
        self.assertNotIn("secret database detail", encoded)


if __name__ == "__main__":
    unittest.main()
