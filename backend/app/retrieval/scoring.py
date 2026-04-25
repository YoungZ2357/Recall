"""Stateless scoring functions: normalization and fusion.

These functions are extracted from searcher.py to break a circular import:
    searcher.py → repository.py → schemas.py → topology.py → graph.py → searcher.py

Placing them here (dependent only on operators.py) breaks the cycle.
"""

import logging

from app.retrieval.operators import SearchHit

logger = logging.getLogger(__name__)


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
