import logging
import math
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

import numpy as np

from app.core.pipeline_deps import PipelineDeps
from app.core.repository import AccessSummary, ChunkAccessRepository, ChunkRepository
from app.retrieval.configs import RerankerConfig
from app.retrieval.operators import BaseReranker, PipelineContext, SearchHit

logger = logging.getLogger(__name__)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors, returned in [-1, 1]."""
    va = np.array(a, dtype=np.float64)
    vb = np.array(b, dtype=np.float64)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    if denom == 0:
        return 0.0
    return float(np.dot(va, vb) / denom)


class Reranker(BaseReranker):
    """Weighted-score reranker: final = α·retrieval_score + β·metadata + γ·retention.

    Implements BaseReranker. Returns list[SearchHit] where:
        - score          = final weighted score
        - source         = "rerank"
        - retrieval_score, metadata_score, retention_score are populated
    """

    def __init__(self, deps: PipelineDeps, config: RerankerConfig | None = None) -> None:
        config = config or RerankerConfig()
        self._embedder = deps.embedder
        self._session_factory = deps.session_factory
        self._alpha = config.alpha
        self._beta = config.beta
        self._gamma = config.gamma
        self._s_base = config.s_base
        self._tag_fallback = config.tag_fallback
        self._score_threshold = config.score_threshold
        self._retention_mode = config.retention_mode

    async def rerank(
        self,
        hits: list[SearchHit],
        context: PipelineContext,
    ) -> list[SearchHit]:
        """Rerank search hits using weighted scoring.

        Opens its own database session from context.session_factory.

        Args:
            hits: Raw search results from retrieval stage.
            context: Per-query pipeline state (query_embedding, retention_mode,
                     session_factory).

        Returns:
            Sorted list of SearchHit with source="rerank". Each hit has
            score=final_score and breakdown fields populated.
            Hits below score_threshold are filtered out.
        """
        if not hits:
            return []

        query_embedding = context.rerank_query_embedding or context.query_embedding
        retention_mode = context.retention_mode
        chunk_ids = [UUID(h.chunk_id) for h in hits]

        async with context.session_factory() as session:
            tags_map = await ChunkRepository.get_tags_by_ids(session, chunk_ids)
            access_map = await ChunkAccessRepository.get_access_summary(session, chunk_ids)
            weight_map = await ChunkRepository.get_document_weights_by_chunk_ids(session, chunk_ids)

        metadata_scores = await self._compute_metadata_scores(
            query_embedding, tags_map, weight_map
        )
        retention_scores = self._compute_retention_scores(access_map, retention_mode)

        results: list[SearchHit] = []
        for hit in hits:
            cid = hit.chunk_id
            ret_score = hit.score
            meta = metadata_scores.get(cid, self._tag_fallback)
            ret = retention_scores.get(cid, 0.0 if retention_mode == "prefer_recent" else 1.0)

            final = self._alpha * ret_score + self._beta * meta + self._gamma * ret

            results.append(SearchHit(
                chunk_id=cid,
                score=round(final, 6),
                source="rerank",
                retrieval_score=round(ret_score, 6),
                metadata_score=round(meta, 6),
                retention_score=round(ret, 6),
            ))

        results.sort(key=lambda r: r.score, reverse=True)
        results = [r for r in results if r.score >= self._score_threshold]

        logger.debug(
            "Reranker: %d hits → %d results (threshold=%.2f)",
            len(hits), len(results), self._score_threshold,
        )
        return results

    async def _compute_metadata_scores(
        self,
        query_embedding: list[float],
        chunk_tags_map: dict[str, list[str]],
        document_weights: dict[str, float],
    ) -> dict[str, float]:
        """Compute metadata score per chunk via tag-query cosine similarity.

        For each chunk:
          score = max(cosine(query, tag_emb) for tag in tags), normalized to [0,1]
          score *= document_weight
        Chunks with no tags get fallback * document_weight.
        """
        unique_tags: list[str] = list({
            tag for tags in chunk_tags_map.values() for tag in tags
        })

        tag_embeddings: dict[str, list[float]] = {}
        if unique_tags:
            vectors = await self._embedder.embed_batch(unique_tags)
            tag_embeddings = dict(zip(unique_tags, vectors, strict=False))

        scores: dict[str, float] = {}
        for chunk_id, tags in chunk_tags_map.items():
            doc_weight = document_weights.get(chunk_id, 1.0)

            if not tags or not tag_embeddings:
                scores[chunk_id] = self._tag_fallback * doc_weight
                continue

            max_sim = max(
                _cosine_similarity(query_embedding, tag_embeddings[tag])
                for tag in tags
                if tag in tag_embeddings
            ) if tags else 0.0
            normalized = (max_sim + 1.0) / 2.0
            scores[chunk_id] = normalized * doc_weight

        return scores

    def _compute_retention_scores(
        self,
        access_summaries: dict[str, AccessSummary],
        retention_mode: Literal["prefer_recent", "awaken_forgotten"],
    ) -> dict[str, float]:
        """Compute Ebbinghaus retention score per chunk.

        R = exp(-t / S), where:
          t = hours since last access
          S = S_BASE * (1 + ln(1 + access_count))

        prefer_recent → R (higher for recent)
        awaken_forgotten → 1 - R (higher for forgotten)
        """
        now = datetime.now(UTC)
        scores: dict[str, float] = {}

        for chunk_id, summary in access_summaries.items():
            if summary.last_accessed_at is None:
                scores[chunk_id] = 0.0 if retention_mode == "prefer_recent" else 1.0
                continue

            last = summary.last_accessed_at
            if last.tzinfo is None:
                last = last.replace(tzinfo=UTC)

            t_hours = (now - last).total_seconds() / 3600.0
            s = self._s_base * (1.0 + math.log(1.0 + summary.access_count))
            r = math.exp(-t_hours / s) if s > 0 else 0.0

            scores[chunk_id] = r if retention_mode == "prefer_recent" else 1.0 - r

        return scores
