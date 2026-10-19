"""Network-free tests for the knowledge-base ingestion flow."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from vendor_ai_assistant.rag.ingest import (
    COLLECTION_NAME,
    EMBEDDING_MODEL,
    MAX_CHUNK_CHARS,
    PREPROCESSING_MODEL,
    chunks_cover_source,
    create_chunks,
    create_embeddings,
    deterministic_chunks,
    ingest,
    load_documents,
    save_to_chroma,
)


class FakeCollection:
    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}

    def upsert(self, *, ids, documents, embeddings, metadatas) -> None:
        for chunk_id, document, vector, metadata in zip(
            ids, documents, embeddings, metadatas, strict=True
        ):
            self.records[chunk_id] = {
                "document": document,
                "embedding": vector,
                "metadata": metadata,
            }

    def get(self, *, where) -> dict[str, list[str]]:
        key, value = next(iter(where.items()))
        return {
            "ids": [
                chunk_id
                for chunk_id, record in self.records.items()
                if record["metadata"].get(key) == value
            ]
        }

    def delete(self, *, ids) -> None:
        for chunk_id in ids:
            self.records.pop(chunk_id, None)

    def count(self) -> int:
        return len(self.records)


class FakeClient:
    def __init__(self) -> None:
        self.collection = FakeCollection()
        self.deleted = False

    def list_collections(self) -> list[Any]:
        return []

    def delete_collection(self, name: str) -> None:
        self.deleted = name == COLLECTION_NAME
        self.collection = FakeCollection()

    def get_or_create_collection(self, name: str) -> FakeCollection:
        return self.collection


class RagIngestionTests(unittest.TestCase):
    def test_loads_markdown_recursively(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "policies").mkdir()
            (root / "policies" / "returns.md").write_text(
                "# Returns\n", encoding="utf-8"
            )
            (root / "README.md").write_text("# Read me\n", encoding="utf-8")
            (root / "ignore.txt").write_text("ignored", encoding="utf-8")

            documents = load_documents(root)

        self.assertEqual(len(documents), 2)
        self.assertEqual(
            {document["source"] for document in documents},
            {"README.md", "policies/returns.md"},
        )

    def test_chat_completion_creates_verbatim_chunks(self) -> None:
        text = "# Shipping\n\nOrders ship after payment confirmation.\n"
        document = {"source": "operations/shipping.md", "type": "operations", "text": text}
        calls = []

        def fake_completion(**kwargs):
            calls.append(kwargs)
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "chunks": [
                                        {
                                            "headline": "Shipping orders",
                                            "summary": "When orders ship.",
                                            "original_text": text,
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            }

        records = create_chunks([document], workers=2, completion_fn=fake_completion)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["model"], PREPROCESSING_MODEL)
        self.assertEqual(calls[0]["messages"][0]["role"], "system")
        self.assertEqual(records[0]["document"], text)
        self.assertEqual(
            records[0]["embedding_text"],
            f"Shipping orders\n\nWhen orders ship.\n\n{text}",
        )

    def test_deterministic_fallback_covers_long_source(self) -> None:
        text = "# Long document\n\n" + ("Inventory guidance. " * 500)
        document = {"source": "operations/inventory.md", "type": "operations", "text": text}

        chunks = deterministic_chunks(document)

        self.assertGreater(len(chunks), 1)
        self.assertLessEqual(max(len(chunk.original_text) for chunk in chunks), MAX_CHUNK_CHARS)
        self.assertTrue(chunks_cover_source(text, chunks))

    def test_embeddings_are_batched_with_exact_model(self) -> None:
        records = [
            {"embedding_text": f"headline {index}\n\nsummary\n\ntext"}
            for index in range(3)
        ]
        calls = []

        def fake_embedding(**kwargs):
            calls.append(kwargs)
            return {
                "data": [
                    {"index": index, "embedding": [float(index), 1.0]}
                    for index, _ in enumerate(kwargs["input"])
                ]
            }

        vectors = create_embeddings(records, batch_size=2, embedding_fn=fake_embedding)

        self.assertEqual([len(call["input"]) for call in calls], [2, 1])
        self.assertTrue(all(call["model"] == EMBEDDING_MODEL for call in calls))
        self.assertEqual(len(vectors), 3)

    def test_chroma_upsert_is_idempotent(self) -> None:
        document = {"source": "help/faq.md", "type": "help", "text": "# FAQ\n\nAnswer.\n"}

        def fake_completion(**kwargs):
            text = document["text"]
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "chunks": [
                                        {
                                            "headline": "FAQ",
                                            "summary": "An answer.",
                                            "original_text": text,
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ]
            }

        records = create_chunks([document], workers=1, completion_fn=fake_completion)
        vectors = [[1.0, 0.0]]
        client = FakeClient()

        first_count = save_to_chroma(records, vectors, Path("unused"), client=client)
        second_count = save_to_chroma(records, vectors, Path("unused"), client=client)

        self.assertEqual(first_count, 1)
        self.assertEqual(second_count, 1)
        stored = next(iter(client.collection.records.values()))
        self.assertEqual(stored["document"], document["text"])
        self.assertEqual(stored["metadata"]["embedding_model"], EMBEDDING_MODEL)

    def test_dry_run_has_no_model_embedding_or_chroma_calls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "doc.md").write_text("# Local\n\nDry run.\n", encoding="utf-8")

            def forbidden(**kwargs):
                raise AssertionError("External call attempted")

            report = ingest(
                knowledge_base_path=root,
                chroma_path=root / "chroma",
                dry_run=True,
                completion_fn=forbidden,
                embedding_fn=forbidden,
                chroma_client=object(),
            )

            self.assertFalse((root / "chroma").exists())

        self.assertEqual(report["document_count"], 1)
        self.assertEqual(report["chunk_count"], 1)
        self.assertEqual(report["stored_count"], 0)


if __name__ == "__main__":
    unittest.main()
