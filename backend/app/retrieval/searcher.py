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
    score_threshold: float = 0.35         # Default from VECTOR_SCORE_THRESHOLD
    filters: dict[str, Any] | None = None


@dataclass
class SearchHit:
    """Single retrieval result, unified format across all retrieval paths.

    Attributes:
        chunk_id: UUID string.
        score: Ranking score at the current stage — may be cosine similarity,
               BM25 score, or normalized RRF fused score.
        source: Path identifier: "vector" / "bm25" / "rrf".
    """
    chunk_id: str
    score: float
    source: str


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


def normalize_scores(hits: list[SearchHit]) -> list[SearchHit]:
    """Min-max normalize SearchHit scores to [0, 1].

    - Empty list → []
    - Single element or all-equal scores → score=1.0
    - Does not change sort order.
    """
    if not hits:
        return []

    scores = [h.score for h in hits]
    min_s = min(scores)
    max_s = max(scores)
    score_range = max_s - min_s

    if score_range > 0:
        return [
            SearchHit(
                chunk_id=h.chunk_id,
                score=round((h.score - min_s) / score_range, 6),
                source=h.source,
            )
            for h in hits
        ]
    else:
        return [
            SearchHit(chunk_id=h.chunk_id, score=1.0, source=h.source)
            for h in hits
        ]


class BM25Searcher(BaseSearcher):
    """SQLite FTS5 sparse recall — not yet implemented."""

    async def search(self, query: SearchQuery) -> list[SearchHit]:
        raise NotImplementedError("BM25Searcher is not implemented yet")


def reciprocal_rank_fusion(
    hit_lists: list[list[SearchHit]],
    k: int = 60,
) -> list[SearchHit]:
    """Merge multiple ranked SearchHit lists using Reciprocal Rank Fusion.

    RRF score for a document = sum of 1/(k + rank_i) across all lists where
    the document appears. Scores are then min-max normalized to [0, 1].

    Requires at least 2 lists to trigger fusion; with 0 or 1 list the input
    is returned as-is (no fusion applied).

    No restriction on the origin of input lists — any ranked data that can be
    projected to SearchHit (chunk_id + score) is a valid input. For example,
    mixing retrieve results with rerank results (converted to SearchHit) in a
    single RRF call is allowed.

    Args:
        hit_lists: Ranked hit lists from different retrieval paths.
        k: RRF smoothing constant (default 60).

    Returns:
        Fused list of SearchHit sorted by descending normalized RRF score,
        with source="rrf".
    """
    if not hit_lists:
        return []
    if len(hit_lists) == 1:
        return hit_lists[0]

    # Accumulate raw RRF scores
    rrf_scores: dict[str, float] = {}
    for hits in hit_lists:
        # Defensive sort — lists should already be sorted desc by score
        sorted_hits = sorted(hits, key=lambda h: h.score, reverse=True)
        for rank, hit in enumerate(sorted_hits, start=1):
            rrf_scores[hit.chunk_id] = rrf_scores.get(hit.chunk_id, 0.0) + 1.0 / (k + rank)

    # Min-max normalization to [0, 1]
    if not rrf_scores:
        return []

    raw_values = list(rrf_scores.values())
    min_score = min(raw_values)
    max_score = max(raw_values)
    score_range = max_score - min_score

    normalized: dict[str, float] = {}
    if score_range > 0:
        normalized = {
            cid: (s - min_score) / score_range for cid, s in rrf_scores.items()
        }
    else:
        normalized = {cid: 1.0 for cid in rrf_scores}

    results = [
        SearchHit(chunk_id=cid, score=round(s, 6), source="rrf")
        for cid, s in normalized.items()
    ]
    results.sort(key=lambda h: h.score, reverse=True)

    logger.debug("RRF merged %d lists → %d unique hits", len(hit_lists), len(results))
    return results
