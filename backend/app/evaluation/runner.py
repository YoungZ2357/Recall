"""Evaluation runner: load test set → run retrieval pipeline → compute metrics."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Literal

from app.evaluation.metrics import ndcg_at_k, recall_at_k, reciprocal_rank
from app.evaluation.schemas import EvalReport, EvalResult, TestSetEntry
from app.retrieval.pipeline import RetrievalPipeline

logger = logging.getLogger(__name__)


async def run_evaluation(
    pipeline: RetrievalPipeline,
    test_set: list[TestSetEntry],
    top_k: int = 10,
    retention_mode: Literal["prefer_recent", "awaken_forgotten"] = "prefer_recent",
    query_callback: Callable[[int, int], None] | None = None,
) -> EvalReport:
    """Execute evaluation over the full test set.

    For each query, calls the retrieval pipeline (without recording access)
    and computes per-query metrics. Returns an aggregate report.

    Args:
        pipeline: Configured RetrievalPipeline instance.
        test_set: List of test set entries with queries and ground truth.
        top_k: Number of results to retrieve per query.
        retention_mode: Ebbinghaus retention strategy for reranking.

    Returns:
        EvalReport with per-query and aggregate metrics.
    """
    per_query: list[EvalResult] = []

    # Filter out entries with empty queries to avoid embedding API errors
    valid_entries = [e for e in test_set if e.query.strip()]
    if len(valid_entries) < len(test_set):
        logger.warning(
            "Skipped %d entries with empty queries", len(test_set) - len(valid_entries)
        )

    for i, entry in enumerate(valid_entries):
        results = await pipeline.search(
            query_text=entry.query,
            top_k=top_k,
            retention_mode=retention_mode,
            record_access=False,
        )
        retrieved_ids = [str(r.chunk_id) for r in results]
        gt_set = set(entry.ground_truth_chunk_ids)

        rr = reciprocal_rank(gt_set, retrieved_ids)
        ndcg = ndcg_at_k(gt_set, retrieved_ids, top_k)
        recall = recall_at_k(gt_set, retrieved_ids, top_k)

        per_query.append(EvalResult(
            query=entry.query,
            ground_truth_chunk_ids=entry.ground_truth_chunk_ids,
            retrieved_chunk_ids=retrieved_ids,
            reciprocal_rank=rr,
            recall_at_k=recall,
            ndcg_at_k=ndcg,
        ))

        logger.debug(
            "Query %d/%d: RR=%.3f nDCG=%.3f Recall=%.3f — %r",
            i + 1, len(valid_entries), rr, ndcg, recall, entry.query[:60],
        )
        if query_callback is not None:
            query_callback(i + 1, len(valid_entries))

    n = len(per_query)
    mrr = sum(r.reciprocal_rank for r in per_query) / n if n else 0.0
    mean_ndcg = sum(r.ndcg_at_k for r in per_query) / n if n else 0.0
    mean_recall = sum(r.recall_at_k for r in per_query) / n if n else 0.0

    report = EvalReport(
        num_queries=n,
        top_k=top_k,
        mrr=mrr,
        mean_ndcg_at_k=mean_ndcg,
        mean_recall_at_k=mean_recall,
        per_query=per_query,
    )

    logger.info(
        "Evaluation complete: %d queries, MRR=%.4f, nDCG@%d=%.4f, Recall@%d=%.4f",
        n, mrr, top_k, mean_ndcg, top_k, mean_recall,
    )
    return report
