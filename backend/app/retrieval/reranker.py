import logging
import math
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.repository import AccessSummary, ChunkAccessRepository, ChunkRepository
from app.core.schemas import RerankResult
from app.ingestion.embedder import BaseEmbedder
from app.retrieval.searcher import SearchHit

logger = logging.getLogger(__name__)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors, returned in [-1, 1]."""
    va = np.array(a, dtype=np.float64)
    vb = np.array(b, dtype=np.float64)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    if denom == 0:
        return 0.0
    return float(np.dot(va, vb) / denom)


class Reranker:
    """Weighted-score reranker: final = α·vector_sim + β·metadata + γ·retention."""

    def __init__(self, embedder: BaseEmbedder, settings: Settings) -> None:
        self._embedder = embedder
        self._alpha = settings.reranker_alpha
        self._beta = settings.reranker_beta
        self._gamma = settings.reranker_gamma
        self._s_base = settings.reranker_s_base
        self._tag_fallback = settings.reranker_tag_fallback
        self._score_threshold = settings.reranker_score_threshold

    async def rerank(
        self,
        session: AsyncSession,
        query_embedding: list[float],
        hits: list[SearchHit],
        retention_mode: Literal["prefer_recent", "awaken_forgotten"] = "prefer_recent",
    ) -> list[RerankResult]:
        """Rerank search hits using weighted scoring.

        Args:
            session: Active database session.
            query_embedding: Query vector for tag similarity.
            hits: Raw search results from searcher.
            retention_mode: "prefer_recent" boosts recently accessed chunks,
                            "awaken_forgotten" boosts long-unseen chunks.

        Returns:
            Sorted list of RerankResult, filtered by score threshold.
        """
        if not hits:
            return []

        chunk_ids = [UUID(h.chunk_id) for h in hits]

        # Parallel DB fetches
        tags_map = await ChunkRepository.get_tags_by_ids(session, chunk_ids)
        access_map = await ChunkAccessRepository.get_access_summary(session, chunk_ids)
        weight_map = await ChunkRepository.get_document_weights_by_chunk_ids(session, chunk_ids)

        # Compute sub-scores
        metadata_scores = await self._compute_metadata_scores(
            query_embedding, tags_map, weight_map
        )
        retention_scores = self._compute_retention_scores(access_map, retention_mode)

        # Weighted merge
        results: list[RerankResult] = []
        for hit in hits:
            cid = hit.chunk_id
            retrieval_score = hit.score
            meta = metadata_scores.get(cid, self._tag_fallback)
            ret = retention_scores.get(cid, 0.0 if retention_mode == "prefer_recent" else 1.0)

            final = self._alpha * retrieval_score + self._beta * meta + self._gamma * ret

            results.append(RerankResult(
                chunk_id=UUID(cid),
                final_score=round(final, 6),
                retrieval_score=round(retrieval_score, 6),
                metadata_score=round(meta, 6),
                retention_score=round(ret, 6),
            ))

        # Sort descending by final_score
        results.sort(key=lambda r: r.final_score, reverse=True)

        # Filter below threshold
        results = [r for r in results if r.final_score >= self._score_threshold]

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
        # Collect all unique tags
        unique_tags: list[str] = list({
            tag for tags in chunk_tags_map.values() for tag in tags
        })

        tag_embeddings: dict[str, list[float]] = {}
        if unique_tags:
            vectors = await self._embedder.embed_batch(unique_tags)
            tag_embeddings = dict(zip(unique_tags, vectors))

        scores: dict[str, float] = {}
        for chunk_id, tags in chunk_tags_map.items():
            doc_weight = document_weights.get(chunk_id, 1.0)

            if not tags or not tag_embeddings:
                scores[chunk_id] = self._tag_fallback * doc_weight
                continue

            # Max cosine similarity, normalized from [-1,1] to [0,1]
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
                if retention_mode == "prefer_recent":
                    scores[chunk_id] = 0.0
                else:
                    scores[chunk_id] = 1.0
                continue

            last = summary.last_accessed_at
            # Ensure timezone-aware comparison
            if last.tzinfo is None:
                last = last.replace(tzinfo=UTC)

            t_hours = (now - last).total_seconds() / 3600.0
            s = self._s_base * (1.0 + math.log(1.0 + summary.access_count))
            r = math.exp(-t_hours / s) if s > 0 else 0.0

            if retention_mode == "prefer_recent":
                scores[chunk_id] = r
            else:
                scores[chunk_id] = 1.0 - r

        return scores
