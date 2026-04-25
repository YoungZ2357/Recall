import logging
from dataclasses import dataclass
from typing import Any

from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

from app.core.exceptions import EmbeddingError, RetrievalError, VectorDBError
from app.core.pipeline_deps import PipelineDeps
from app.core.repository import FTSRepository
from app.retrieval.configs import BM25SearcherConfig, ContextualBM25SearcherConfig, VectorSearcherConfig
from app.retrieval.operators import BaseRetriever, PipelineContext, SearchHit

logger = logging.getLogger(__name__)


@dataclass
class SearchQuery:
    """Internal retrieval request; not part of the public DAG operator interface."""
    text: str
    embedding: list[float] | None = None
    top_k: int = 20
    score_threshold: float = 0.35
    filters: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Normalizer and RRF — stateless functions, usable at any DAG node boundary
# ---------------------------------------------------------------------------

def normalize_scores(hits: list[SearchHit]) -> list[SearchHit]:
    """Min-max normalize SearchHit scores to [0, 1].

    - Empty list → []
    - Single element or all-equal scores → score=1.0
    - Does not change sort order.
    - Breakdown fields (retrieval_score, metadata_score, retention_score)
      are preserved unchanged.
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
                retrieval_score=h.retrieval_score,
                metadata_score=h.metadata_score,
                retention_score=h.retention_score,
            )
            for h in hits
        ]
    else:
        return [
            SearchHit(
                chunk_id=h.chunk_id,
                score=1.0,
                source=h.source,
                retrieval_score=h.retrieval_score,
                metadata_score=h.metadata_score,
                retention_score=h.retention_score,
            )
            for h in hits
        ]


def reciprocal_rank_fusion(
    hit_lists: list[list[SearchHit]],
    k: int = 60,
    weights: list[float] | None = None,
) -> list[SearchHit]:
    """Merge multiple ranked SearchHit lists using Reciprocal Rank Fusion.

    RRF score for a document = sum of w_i/(k + rank_i) across all lists where
    the document appears. Scores are then min-max normalized to [0, 1].

    Acts as both MergeDetector and RRF in the DAG abstraction:
    - 0 lists  → []
    - 1 list   → pass-through (no fusion applied)
    - 2+ lists → RRF fusion with normalized output

    No restriction on the origin of input lists — any ranked data that can be
    projected to SearchHit (chunk_id + score) is a valid input.

    Args:
        hit_lists: Ranked hit lists from different retrieval paths.
        k: RRF smoothing constant (default 60).
        weights: Per-list multipliers aligned to hit_lists by index. None = equal weight (1.0).

    Returns:
        Fused list of SearchHit sorted by descending normalized RRF score,
        with source="rrf".
    """
    if not hit_lists:
        return []
    if len(hit_lists) == 1:
        return hit_lists[0]

    if weights is not None and len(weights) != len(hit_lists):
        raise ValueError(
            f"weights length {len(weights)} != hit_lists length {len(hit_lists)}"
        )

    rrf_scores: dict[str, float] = {}
    for i, hits in enumerate(hit_lists):
        w = weights[i] if weights is not None else 1.0
        sorted_hits = sorted(hits, key=lambda h: h.score, reverse=True)
        for rank, hit in enumerate(sorted_hits, start=1):
            rrf_scores[hit.chunk_id] = rrf_scores.get(hit.chunk_id, 0.0) + w / (k + rank)

    if not rrf_scores:
        return []

    raw_values = list(rrf_scores.values())
    min_score = min(raw_values)
    max_score = max(raw_values)
    score_range = max_score - min_score

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


# ---------------------------------------------------------------------------
# Retriever implementations
# ---------------------------------------------------------------------------

class VectorSearcher(BaseRetriever):
    """ANN vector recall using Qdrant."""

    def __init__(
        self,
        deps: PipelineDeps,
        config: VectorSearcherConfig | None = None,
    ) -> None:
        config = config or VectorSearcherConfig()
        self._qdrant = deps.qdrant_client
        self._embedder = deps.embedder
        self._score_threshold = config.score_threshold
        self._top_k = config.top_k
        self._collection_name = config.collection_name

    async def retrieve(self, context: PipelineContext) -> list[SearchHit]:
        """Implement BaseRetriever: translate PipelineContext to SearchQuery and search."""
        query = SearchQuery(
            text=context.query_text,
            embedding=context.query_embedding,
            top_k=context.top_k * 2,  # wider recall window than final top_k
            score_threshold=self._score_threshold,
            filters=context.filters,
        )
        return await self._search(query)

    async def _search(self, query: SearchQuery) -> list[SearchHit]:
        """Execute ANN search against Qdrant.

        Args:
            query: Internal search parameters.

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


class BM25Searcher(BaseRetriever):
    """SQLite FTS5 sparse recall via BM25 ranking."""

    def __init__(
        self,
        deps: PipelineDeps,
        config: BM25SearcherConfig | None = None,
    ) -> None:
        config = config or BM25SearcherConfig()
        self._session_factory = deps.session_factory
        self._recall_multiplier = config.recall_multiplier
        self._top_k = config.top_k
        self._score_threshold = config.score_threshold

    async def retrieve(self, context: PipelineContext) -> list[SearchHit]:
        """Implement BaseRetriever: translate PipelineContext to SearchQuery and search."""
        query = SearchQuery(
            text=context.query_text,
            top_k=context.top_k * 2,
            filters=context.filters,
        )
        return await self._search(query)

    async def _search(self, query: SearchQuery) -> list[SearchHit]:
        """Execute BM25 full-text search against the FTS5 index.

        Args:
            query: Internal search parameters. Only `text`, `top_k`, and
                   `filters["document_id"]` are used; tag filters are ignored
                   (handled downstream by the reranker).

        Returns:
            List of SearchHit sorted by descending relevance.

        Raises:
            RetrievalError: Database error during FTS search.
        """
        document_id: str | None = None
        if query.filters:
            document_id = query.filters.get("document_id")

        try:
            async with self._session_factory() as session:
                rows = await FTSRepository.fts_search(
                    session,
                    query.text,
                    query.top_k * self._recall_multiplier,
                    document_id=document_id,
                )
        except Exception as e:
            raise RetrievalError(
                message="BM25 search failed",
                detail=str(e),
            ) from e

        if not rows:
            return []

        hits = [
            SearchHit(chunk_id=chunk_id, score=-raw_score, source="bm25")
            for chunk_id, raw_score in rows
        ]
        logger.debug("BM25Searcher returned %d hits for query=%r", len(hits), query.text)
        return hits


class ContextualBM25Searcher(BaseRetriever):
    """SQLite FTS5 sparse recall using Chunk.context (contextualized text).

    Only chunks that have been contextualized (context IS NOT NULL) are indexed
    and can appear in results. Intended to run alongside BM25Searcher and be
    merged via RRF.
    """

    def __init__(
        self,
        deps: PipelineDeps,
        config: ContextualBM25SearcherConfig | None = None,
    ) -> None:
        config = config or ContextualBM25SearcherConfig()
        self._session_factory = deps.session_factory
        self._recall_multiplier = config.recall_multiplier
        self._top_k = config.top_k
        self._score_threshold = config.score_threshold

    async def retrieve(self, context: PipelineContext) -> list[SearchHit]:
        """Implement BaseRetriever: translate PipelineContext to SearchQuery and search."""
        query = SearchQuery(
            text=context.query_text,
            top_k=context.top_k * 2,
            filters=context.filters,
        )
        return await self._search(query)

    async def _search(self, query: SearchQuery) -> list[SearchHit]:
        """Execute BM25 full-text search against the context FTS index.

        Args:
            query: Internal search parameters. Only `text`, `top_k`, and
                   `filters["document_id"]` are used; tag filters are ignored.

        Returns:
            List of SearchHit sorted by descending relevance.

        Raises:
            RetrievalError: Database error during FTS search.
        """
        document_id: str | None = None
        if query.filters:
            document_id = query.filters.get("document_id")

        try:
            async with self._session_factory() as session:
                rows = await FTSRepository.context_fts_search(
                    session,
                    query.text,
                    query.top_k * self._recall_multiplier,
                    document_id=document_id,
                )
        except Exception as e:
            raise RetrievalError(
                message="Contextual BM25 search failed",
                detail=str(e),
            ) from e

        if not rows:
            return []

        hits = [
            SearchHit(chunk_id=chunk_id, score=-raw_score, source="context_bm25")
            for chunk_id, raw_score in rows
        ]
        logger.debug(
            "ContextualBM25Searcher returned %d hits for query=%r", len(hits), query.text
        )
        return hits
