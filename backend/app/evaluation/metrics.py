"""Pure metric functions for retrieval evaluation.

All functions are stateless and synchronous — no external dependencies.
"""

from __future__ import annotations

import math


def reciprocal_rank(ground_truth_ids: set[str], retrieved_ids: list[str]) -> float:
    """Reciprocal rank: 1/position of the first relevant result.

    Returns 0.0 if no ground truth item appears in retrieved_ids.
    """
    for i, rid in enumerate(retrieved_ids, start=1):
        if rid in ground_truth_ids:
            return 1.0 / i
    return 0.0


def ndcg_at_k(ground_truth_ids: set[str], retrieved_ids: list[str], k: int) -> float:
    """Normalized Discounted Cumulative Gain at K with binary relevance.

    rel_i = 1 if retrieved_ids[i] in ground_truth_ids, else 0.
    Returns 0.0 if ground_truth_ids is empty or k <= 0.
    """
    if not ground_truth_ids or k <= 0:
        return 0.0

    truncated = retrieved_ids[:k]

    # DCG
    dcg = 0.0
    for i, rid in enumerate(truncated, start=1):
        if rid in ground_truth_ids:
            dcg += 1.0 / math.log2(i + 1)

    # IDCG: ideal ordering places all relevant items first
    num_relevant = min(len(ground_truth_ids), k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, num_relevant + 1))

    if idcg == 0.0:
        return 0.0

    return dcg / idcg


def recall_at_k(ground_truth_ids: set[str], retrieved_ids: list[str], k: int) -> float:
    """Recall at K: fraction of ground truth items found in top-k results.

    Returns 0.0 if ground_truth_ids is empty or k <= 0.
    """
    if not ground_truth_ids or k <= 0:
        return 0.0

    hits = sum(1 for rid in retrieved_ids[:k] if rid in ground_truth_ids)
    return hits / len(ground_truth_ids)
