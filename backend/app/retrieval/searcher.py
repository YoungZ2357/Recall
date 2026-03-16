import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

from app.core.exceptions import EmbeddingError, RetrievalError, VectorDBError
from app.core.vectordb import QdrantService
from app.ingestion.embedder import BaseEmbedder

logger = logging.getLogger(__name__)


@dataclass
class SearchQuery:
    """Retrieval request."""
    text: str                             # Original query text
    embedding: list[float] | None = None  # Pre-computed vector (HyDE scenario)
    top_k: int = 20
    score_threshold: float | None = None
    filters: dict[str, Any] | None = None


@dataclass
class SearchHit:
    """Single retrieval result, unified format across all retrieval paths."""
    chunk_id: str    # UUID
    score: float     # Raw score from the retrieval path
    source: str      # Path identifier: "vector" / "bm25"


class BaseSearcher(ABC):
    """Base class for a single retrieval path."""

    @abstractmethod
    async def search(self, query: SearchQuery) -> list[SearchHit]:
        """Execute search and return ranked hits."""
        pass


class VectorSearcher(BaseSearcher):
    """ANN vector recall using Qdrant."""

    def __init__(self, qdrant_service: QdrantService, embedder: BaseEmbedder) -> None:
        self._qdrant = qdrant_service
        self._embedder = embedder

    async def search(self, query: SearchQuery) -> list[SearchHit]:
        """Embed query (or reuse pre-computed vector) and run ANN search.

        Args:
            query: Search parameters including text, optional pre-computed embedding,
                   top_k, score_threshold, and metadata filters.

        Returns:
            List of SearchHit sorted by descending score.

        Raises:
            RetrievalError: Embedding or Qdrant operation failed.
        """
        try:
            if query.embedding is not None:
                vector = query.embedding
            else:
                vectors = await self._embedder.embed_batch([query.text])
                vector = vectors[0]

            qdrant_filter = self._build_filter(query.filters)

            scored_points = await self._qdrant.search(
                query_vector=vector,
                top_k=query.top_k,
                score_threshold=query.score_threshold,
                query_filter=qdrant_filter,
            )

            hits = [
                SearchHit(chunk_id=str(p.id), score=p.score, source="vector")
                for p in scored_points
            ]
            logger.debug("VectorSearcher returned %d hits for query=%r", len(hits), query.text)
            return hits

        except (VectorDBError, EmbeddingError) as e:
            raise RetrievalError(
                message="Vector search failed",
                detail=str(e),
            ) from e

    def _build_filter(self, filters: dict[str, Any] | None) -> Filter | None:
        """Convert simple metadata dict to a Qdrant Filter.

        Supported keys:
            "document_id": str  — exact match
            "tags": list[str]   — any-of match

        Unknown keys are silently ignored.

        Args:
            filters: Metadata filter dict, or None.

        Returns:
            Qdrant Filter object, or None if filters is empty/None.
        """
        if not filters:
            return None

        conditions: list[FieldCondition] = []

        if "document_id" in filters:
            conditions.append(
                FieldCondition(
                    key="document_id",
                    match=MatchValue(value=filters["document_id"]),
                )
            )

        if "tags" in filters:
            tag_values = filters["tags"]
            if isinstance(tag_values, str):
                tag_values = [tag_values]
            conditions.append(
                FieldCondition(
                    key="tags",
                    match=MatchAny(any=tag_values),
                )
            )

        if not conditions:
            return None

        return Filter(must=conditions)


class BM25Searcher(BaseSearcher):
    """SQLite FTS5 sparse recall — not yet implemented."""

    async def search(self, query: SearchQuery) -> list[SearchHit]:
        raise NotImplementedError("BM25Searcher is not implemented yet")
