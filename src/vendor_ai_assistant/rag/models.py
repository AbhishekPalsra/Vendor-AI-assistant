"""Models returned by the document preprocessing LLM."""

from pydantic import BaseModel, Field


class Chunk(BaseModel):
    headline: str = Field(description="A short, searchable heading for the chunk")
    summary: str = Field(description="A concise summary of the chunk")
    original_text: str = Field(
        description="Verbatim text copied from the source document"
    )


class Chunks(BaseModel):
    chunks: list[Chunk]


class RagEvidence(BaseModel):
    """One immutable knowledge-base excerpt selected for answer generation."""

    chunk_id: str
    headline: str
    summary: str
    original_text: str
    source_path: str
    document_type: str
    chunk_index: int
    matched_queries: tuple[str, ...] = ()
    retrieval_distance: float | None = None
    rerank_score: float = Field(ge=0, le=1)
    rerank_reason: str
