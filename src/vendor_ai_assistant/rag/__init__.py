"""Knowledge-base ingestion and retrieval for the vendor AI assistant."""

from vendor_ai_assistant.rag.models import Chunk, RagEvidence
from vendor_ai_assistant.rag.retrieve import retrieve_rag

__all__ = ["Chunk", "RagEvidence", "retrieve_rag"]
