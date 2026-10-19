"""Preprocess Markdown documents and save their embeddings in local Chroma."""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import os
import re
from collections.abc import Callable, Sequence
from functools import partial
from pathlib import Path
from typing import Any

from chromadb import PersistentClient
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential

from vendor_ai_assistant.rag.models import Chunk, Chunks

PROJECT_ROOT = Path(__file__).resolve().parents[3]
KNOWLEDGE_BASE_PATH = PROJECT_ROOT / "data" / "knowledge-base"
CHROMA_PATH = PROJECT_ROOT / "data" / "vector_store" / "chroma"
COLLECTION_NAME = "vendor_knowledge_base"

load_dotenv(PROJECT_ROOT / ".env")
PREPROCESSING_MODEL = os.getenv("PREPROCESSING_MODEL", "openai/gpt-5-nano")
EMBEDDING_MODEL = "text-embedding-3-large"
MIN_CHUNK_CHARS = 800
MAX_CHUNK_CHARS = 1_400
OVERLAP_CHARS = 180

SYSTEM_PROMPT = """You prepare Markdown documents for a company knowledge base.

Split the document into useful semantic chunks by following its headings,
paragraphs, lists, and topic changes. Aim for roughly 200-350 tokens per chunk
with about 30-50 tokens of overlap. Group related short sections together instead
of creating one tiny chunk per heading. Short documents can remain as one chunk.

For every chunk return:
- headline: a short heading useful for search
- summary: a concise factual summary
- original_text: text copied verbatim from the document

Together the chunks must cover the complete document. Never rewrite, correct, or
invent original_text. Return only the requested structured output.
"""

Document = dict[str, str]
CompletionFunction = Callable[..., Any]
EmbeddingFunction = Callable[..., Any]


def _litellm_completion(**kwargs: Any) -> Any:
    from litellm import completion

    return completion(**kwargs)


def _litellm_embedding(**kwargs: Any) -> Any:
    from litellm import embedding

    return embedding(**kwargs)


def load_documents(path: Path = KNOWLEDGE_BASE_PATH) -> list[Document]:
    """Recursively load all Markdown documents."""

    root = path.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Knowledge base not found: {root}")

    documents = []
    for file_path in sorted(root.rglob("*.md")):
        relative_path = file_path.relative_to(root).as_posix()
        parts = Path(relative_path).parts
        documents.append(
            {
                "source": relative_path,
                "type": parts[0] if len(parts) > 1 else "root",
                "text": file_path.read_text(encoding="utf-8"),
            }
        )
    return documents


def make_messages(document: Document) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Document type: {document['type']}\n"
                f"Source: {document['source']}\n\n"
                f"{document['text']}"
            ),
        },
    ]


def _response_chunks(response: Any) -> list[Chunk]:
    if isinstance(response, dict):
        message = response["choices"][0]["message"]
        parsed = message.get("parsed")
        content = message.get("content")
    else:
        message = response.choices[0].message
        parsed = getattr(message, "parsed", None)
        content = message.content

    if parsed is not None:
        return (parsed if isinstance(parsed, Chunks) else Chunks.model_validate(parsed)).chunks
    return Chunks.model_validate_json(content).chunks


def chunks_cover_source(source: str, chunks: Sequence[Chunk]) -> bool:
    """Check that chunk text is verbatim and covers every non-whitespace character."""

    if not source:
        return not chunks

    covered_until = 0
    for chunk in chunks:
        if not chunk.headline.strip() or not chunk.summary.strip() or not chunk.original_text:
            return False

        best_end = -1
        start = source.find(chunk.original_text)
        while start >= 0 and (
            start <= covered_until or source[covered_until:start].isspace()
        ):
            best_end = max(best_end, start + len(chunk.original_text))
            start = source.find(chunk.original_text, start + 1)
        if best_end < 0:
            return False
        covered_until = max(covered_until, best_end)
    remainder = source[covered_until:]
    return not remainder or remainder.isspace()


def _fallback_headline(text: str, source: str) -> str:
    heading = re.search(r"(?m)^#{1,6}\s+(.+?)\s*$", text)
    if heading:
        return heading.group(1).strip()
    return Path(source).stem.replace("-", " ").title()


def deterministic_chunks(document: Document) -> list[Chunk]:
    """Simple no-API fallback using approximately 200-350 token windows."""

    source = document["text"]
    if not source:
        return []

    chunks = []
    start = 0
    while start < len(source):
        end = min(start + MAX_CHUNK_CHARS, len(source))
        if end < len(source):
            paragraph_end = source.rfind("\n\n", start + MIN_CHUNK_CHARS, end)
            if paragraph_end > start:
                end = paragraph_end + 2

        original_text = source[start:end]
        plain_text = re.sub(r"\s+", " ", original_text).strip()
        summary = plain_text[:240].rsplit(" ", 1)[0]
        if len(plain_text) > 240:
            summary += "..."
        chunks.append(
            Chunk(
                headline=_fallback_headline(original_text, document["source"]),
                summary=summary or "Knowledge-base content",
                original_text=original_text,
            )
        )

        if end == len(source):
            break
        start = max(start + 1, end - OVERLAP_CHARS)

    return chunks


@retry(
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(2),
    reraise=True,
)
def _call_chunking_model(
    document: Document,
    model: str,
    completion_fn: CompletionFunction,
) -> list[Chunk]:
    response = completion_fn(
        model=model,
        messages=make_messages(document),
        response_format=Chunks,
        reasoning_effort="minimal",
        timeout=90,
    )
    chunks = _response_chunks(response)
    if not chunks_cover_source(document["text"], chunks):
        raise ValueError("Model chunks did not preserve and cover the source document")
    return chunks


def process_document(
    document: Document,
    model: str = PREPROCESSING_MODEL,
    completion_fn: CompletionFunction | None = None,
) -> tuple[Document, list[Chunk]]:
    completion_fn = completion_fn or _litellm_completion
    try:
        return document, _call_chunking_model(document, model, completion_fn)
    except Exception as error:
        print(f"Using fallback chunking for {document['source']}: {error}")
        return document, deterministic_chunks(document)


def create_chunks(
    documents: Sequence[Document],
    workers: int,
    model: str = PREPROCESSING_MODEL,
    completion_fn: CompletionFunction | None = None,
    use_llm: bool = True,
) -> list[dict[str, Any]]:
    """Chunk documents in a process pool and attach storage metadata."""

    processor = partial(process_document, model=model, completion_fn=completion_fn)
    if not use_llm:
        results = [(document, deterministic_chunks(document)) for document in documents]
    elif workers == 1 or completion_fn is not None:
        results = []
        for index, document in enumerate(documents, start=1):
            results.append(processor(document))
            print(f"Processed {index}/{len(documents)}: {document['source']}", flush=True)
    else:
        with multiprocessing.Pool(processes=workers) as pool:
            results = pool.map(processor, documents)

    records = []
    for document, chunks in results:
        for index, chunk in enumerate(chunks):
            content_hash = hashlib.sha256(chunk.original_text.encode("utf-8")).hexdigest()
            chunk_id = hashlib.sha256(
                f"{document['source']}:{index}".encode("utf-8")
            ).hexdigest()
            records.append(
                {
                    "id": chunk_id,
                    "document": chunk.original_text,
                    "embedding_text": (
                        f"{chunk.headline}\n\n{chunk.summary}\n\n{chunk.original_text}"
                    ),
                    "metadata": {
                        "headline": chunk.headline,
                        "summary": chunk.summary,
                        "relative_source_path": document["source"],
                        "document_type": document["type"],
                        "chunk_index": index,
                        "content_hash": content_hash,
                        "preprocessing_model": model,
                        "embedding_model": EMBEDDING_MODEL,
                    },
                }
            )
    return records


def create_embeddings(
    records: Sequence[dict[str, Any]],
    batch_size: int,
    embedding_fn: EmbeddingFunction | None = None,
) -> list[list[float]]:
    embedding_fn = embedding_fn or _litellm_embedding
    vectors = []
    for start in range(0, len(records), batch_size):
        batch = records[start : start + batch_size]
        response = embedding_fn(
            model=EMBEDDING_MODEL,
            input=[record["embedding_text"] for record in batch],
        )
        data = response["data"] if isinstance(response, dict) else response.data
        data = sorted(
            data,
            key=lambda item: item.get("index", 0)
            if isinstance(item, dict)
            else item.index,
        )
        vectors.extend(
            item["embedding"] if isinstance(item, dict) else item.embedding
            for item in data
        )
    return vectors


def save_to_chroma(
    records: Sequence[dict[str, Any]],
    vectors: Sequence[Sequence[float]],
    path: Path = CHROMA_PATH,
    batch_size: int = 32,
    rebuild: bool = False,
    client: Any | None = None,
) -> int:
    """Upsert records into the persistent local collection."""

    if len(records) != len(vectors):
        raise ValueError("Record and embedding counts do not match")

    if client is None:
        path.mkdir(parents=True, exist_ok=True)
        chroma = PersistentClient(path=str(path))
    else:
        chroma = client
    existing = [
        item if isinstance(item, str) else item.name
        for item in chroma.list_collections()
    ]
    if rebuild and COLLECTION_NAME in existing:
        chroma.delete_collection(COLLECTION_NAME)

    collection = chroma.get_or_create_collection(COLLECTION_NAME)
    for start in range(0, len(records), batch_size):
        batch = records[start : start + batch_size]
        collection.upsert(
            ids=[record["id"] for record in batch],
            documents=[record["document"] for record in batch],
            embeddings=[list(vector) for vector in vectors[start : start + batch_size]],
            metadatas=[record["metadata"] for record in batch],
        )

    current_ids = {record["id"] for record in records}
    current_sources = {
        record["metadata"]["relative_source_path"] for record in records
    }
    for source in current_sources:
        stored = collection.get(where={"relative_source_path": source})["ids"]
        stale_ids = [chunk_id for chunk_id in stored if chunk_id not in current_ids]
        if stale_ids:
            collection.delete(ids=stale_ids)
    return collection.count()


def ingest(
    knowledge_base_path: Path = KNOWLEDGE_BASE_PATH,
    chroma_path: Path = CHROMA_PATH,
    workers: int = 3,
    batch_size: int = 32,
    model: str = PREPROCESSING_MODEL,
    dry_run: bool = False,
    rebuild: bool = False,
    completion_fn: CompletionFunction | None = None,
    embedding_fn: EmbeddingFunction | None = None,
    chroma_client: Any | None = None,
) -> dict[str, Any]:
    if workers < 1 or batch_size < 1:
        raise ValueError("workers and batch_size must be at least 1")

    documents = load_documents(knowledge_base_path)
    if dry_run:
        records = create_chunks(documents, workers=1, model=model, use_llm=False)
        stored_count = 0
    else:
        records = create_chunks(documents, workers, model, completion_fn)
        vectors = create_embeddings(records, batch_size, embedding_fn)
        stored_count = save_to_chroma(
            records,
            vectors,
            chroma_path,
            batch_size,
            rebuild,
            chroma_client,
        )

    return {
        "document_count": len(documents),
        "chunk_count": len(records),
        "stored_count": stored_count,
        "chroma_path": str(chroma_path.resolve()),
        "collection": COLLECTION_NAME,
        "dry_run": dry_run,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--knowledge-base-path", type=Path, default=KNOWLEDGE_BASE_PATH)
    parser.add_argument("--chroma-path", type=Path, default=CHROMA_PATH)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--model", default=PREPROCESSING_MODEL)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    arguments = parser.parse_args()

    result = ingest(
        knowledge_base_path=arguments.knowledge_base_path,
        chroma_path=arguments.chroma_path,
        workers=arguments.workers,
        batch_size=arguments.batch_size,
        model=arguments.model,
        dry_run=arguments.dry_run,
        rebuild=arguments.rebuild,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
