"""Network-free tests for Chroma retrieval and in-module LLM reranking."""

from __future__ import annotations

import json
import unittest
from typing import Any

from vendor_ai_assistant.chat.models import RagRequest
from vendor_ai_assistant.rag.ingest import COLLECTION_NAME, EMBEDDING_MODEL
from vendor_ai_assistant.rag.retrieve import (
    DEFAULT_CANDIDATE_COUNT,
    DEFAULT_EVIDENCE_COUNT,
    RERANKING_MODEL,
    retrieve_rag,
)


class FakeCollection:
    def __init__(self, count: int = DEFAULT_CANDIDATE_COUNT) -> None:
        self.records = [
            {
                "id": f"chunk-{index:02d}",
                "document": f"Verbatim policy evidence number {index}.",
                "metadata": {
                    "headline": f"Policy {index}",
                    "summary": f"Summary {index}",
                    "relative_source_path": "policies/return-policy.md"
                    if index % 2 == 0
                    else "help/returns-damage-faq.md",
                    "document_type": "policies",
                    "chunk_index": index,
                },
                "distance": index / 100,
            }
            for index in range(count)
        ]
        self.query_calls: list[dict[str, Any]] = []

    def count(self) -> int:
        return len(self.records)

    def query(self, **kwargs) -> dict[str, Any]:
        self.query_calls.append(kwargs)
        records = self.records[: kwargs["n_results"]]
        return {
            "ids": [[record["id"] for record in records]],
            "documents": [[record["document"] for record in records]],
            "metadatas": [[record["metadata"] for record in records]],
            "distances": [[record["distance"] for record in records]],
        }


class FakeClient:
    def __init__(self, collection: FakeCollection) -> None:
        self.collection = collection
        self.requested_collection: str | None = None

    def get_collection(self, name: str) -> FakeCollection:
        self.requested_collection = name
        return self.collection


class RagRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.requests = (
            RagRequest(
                query="Return rules for damaged Fortune oil delivered in Jaipur",
                purpose="Explain return eligibility and required evidence",
                source_paths=("policies/return-policy.md",),
            ),
        )

    def test_retrieves_fifteen_and_returns_ten_in_reranked_order(self) -> None:
        collection = FakeCollection()
        client = FakeClient(collection)
        embedding_calls = []
        rerank_calls = []

        def fake_embedding(**kwargs):
            embedding_calls.append(kwargs)
            return {"data": [{"index": 0, "embedding": [0.1, 0.2]}]}

        selected_ids = [f"chunk-{index:02d}" for index in range(14, 4, -1)]

        def fake_completion(**kwargs):
            rerank_calls.append(kwargs)
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "results": [
                                        {
                                            "chunk_id": chunk_id,
                                            "relevance_score": 0.95 - index * 0.01,
                                            "reason": "Directly relevant policy evidence.",
                                        }
                                        for index, chunk_id in enumerate(selected_ids)
                                    ]
                                }
                            )
                        }
                    }
                ]
            }

        evidence = retrieve_rag(
            self.requests,
            rewritten_query=(
                "What return rules apply to damaged Fortune oil delivered in Jaipur?"
            ),
            original_query="Can I return damaged Fortune oil from Jaipur?",
            embedding_fn=fake_embedding,
            completion_fn=fake_completion,
            chroma_client=client,
        )

        self.assertEqual(client.requested_collection, COLLECTION_NAME)
        self.assertEqual(collection.query_calls[0]["n_results"], 15)
        self.assertEqual(len(evidence), 10)
        self.assertEqual([item.chunk_id for item in evidence], selected_ids)
        self.assertEqual(
            evidence[0].original_text,
            "Verbatim policy evidence number 14.",
        )
        self.assertEqual(embedding_calls[0]["model"], EMBEDDING_MODEL)
        self.assertEqual(embedding_calls[0]["input"], [self.requests[0].query])
        self.assertEqual(rerank_calls[0]["model"], RERANKING_MODEL)
        self.assertEqual(rerank_calls[0]["response_format"].__name__, "RerankResponse")
        rerank_payload = json.loads(rerank_calls[0]["messages"][1]["content"])
        self.assertEqual(rerank_payload["return_count"], 10)
        self.assertEqual(len(rerank_payload["candidates"]), 15)
        self.assertIn("complete_rewritten_query", rerank_payload)
        self.assertIn("original_query", rerank_payload)

    def test_multiple_queries_are_deduplicated_before_reranking(self) -> None:
        collection = FakeCollection(count=4)
        client = FakeClient(collection)
        requests = (
            self.requests[0],
            RagRequest(
                query="Damaged goods reporting requirements",
                purpose="Find reporting steps",
            ),
        )

        def fake_embedding(**kwargs):
            return {
                "data": [
                    {"index": 0, "embedding": [0.1, 0.2]},
                    {"index": 1, "embedding": [0.2, 0.1]},
                ]
            }

        def fake_completion(**kwargs):
            payload = json.loads(kwargs["messages"][1]["content"])
            self.assertEqual(len(payload["candidates"]), 4)
            self.assertTrue(
                all(len(candidate["matched_queries"]) == 2 for candidate in payload["candidates"])
            )
            return {
                "choices": [
                    {
                        "message": {
                            "parsed": {
                                "results": [
                                    {
                                        "chunk_id": candidate["chunk_id"],
                                        "relevance_score": 0.8,
                                        "reason": "Relevant evidence.",
                                    }
                                    for candidate in payload["candidates"]
                                ]
                            }
                        }
                    }
                ]
            }

        evidence = retrieve_rag(
            requests,
            rewritten_query="Return and reporting rules for damaged Fortune oil",
            candidate_count=15,
            evidence_count=10,
            embedding_fn=fake_embedding,
            completion_fn=fake_completion,
            chroma_client=client,
        )

        self.assertEqual(len(collection.query_calls), 2)
        self.assertEqual(len(evidence), 4)
        self.assertTrue(all(len(item.matched_queries) == 2 for item in evidence))

    def test_invalid_reranker_output_falls_back_to_vector_order(self) -> None:
        collection = FakeCollection(count=3)

        def fake_embedding(**kwargs):
            return {"data": [{"index": 0, "embedding": [0.1, 0.2]}]}

        def fake_completion(**kwargs):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "results": [
                                        {
                                            "chunk_id": "invented-id",
                                            "relevance_score": 1,
                                            "reason": "Invented",
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            }

        evidence = retrieve_rag(
            self.requests,
            rewritten_query="Return rules for damaged oil",
            embedding_fn=fake_embedding,
            completion_fn=fake_completion,
            chroma_client=FakeClient(collection),
        )

        self.assertEqual(
            [item.chunk_id for item in evidence],
            ["chunk-00", "chunk-02", "chunk-01"],
        )
        self.assertTrue(all("fallback" in item.rerank_reason.lower() for item in evidence))

    def test_empty_requests_do_not_open_chroma_or_call_models(self) -> None:
        def forbidden(**kwargs):
            raise AssertionError("External call attempted")

        self.assertEqual(
            retrieve_rag(
                (),
                rewritten_query="No RAG work",
                embedding_fn=forbidden,
                completion_fn=forbidden,
                chroma_client=object(),
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
