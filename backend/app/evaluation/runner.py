"""Evaluation runner: load test set → run retrieval via SearchService → compute metrics.

Metrics are computed via ir_measures using graded qrels. The standard suite is:
    nDCG@k         — graded relevance, exponential gain
    R(rel=2)@k     — binary recall, rel>=2 threshold
    RR(rel=2)      — mean reciprocal rank, rel>=2 threshold
    AP(rel=2)      — mean average precision, rel>=2 threshold
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from typing import TYPE_CHECKING, Literal

import ir_measures
from ir_measures import AP, RR, Measure, R, nDCG

from app.evaluation.schemas import EvalReport, EvalResult, TestSetEntry

if TYPE_CHECKING:
    from app.services.search_service import SearchService

logger = logging.getLogger(__name__)


def _build_measures(top_k: int) -> list[Measure]:
    """Construct the standard ir_measures suite parameterised by top_k."""
    return [
        nDCG @ top_k,
        R(rel=2) @ top_k,
        RR(rel=2),
        AP(rel=2),
    ]


async def run_evaluation(
    search_service: SearchService,
    test_set: list[TestSetEntry],
    top_k: int = 10,
    retention_mode: Literal["prefer_recent", "awaken_forgotten"] = "prefer_recent",
    query_callback: Callable[[int, int], None] | None = None,
) -> EvalReport:
    """Execute evaluation over the full test set.

    For each query, calls search_service.search() (without recording access)
    and computes per-query metrics via ir_measures. Returns an aggregate report.

    Args:
        search_service: Configured SearchService instance.
        test_set: List of test set entries with graded relevance.
        top_k: Number of results to retrieve per query; also the cutoff for
               nDCG@k and R(rel=2)@k.
        retention_mode: Ebbinghaus retention strategy for reranking.

    Returns:
        EvalReport with per-query and aggregate metrics.
    """
    # Filter out entries with empty queries to avoid embedding API errors
    valid_entries = [e for e in test_set if e.query.strip()]
    if len(valid_entries) < len(test_set):
        logger.warning(
            "Skipped %d entries with empty queries", len(test_set) - len(valid_entries)
        )

    # Execute retrieval for each query, build qrels + run as we go
    qrels: dict[str, dict[str, int]] = {}
    run: dict[str, dict[str, float]] = {}
    retrieved_by_query: dict[str, list[str]] = {}
    query_text_by_id: dict[str, str] = {}

    for i, entry in enumerate(valid_entries):
        results = await search_service.search(
            query_text=entry.query,
            top_k=top_k,
            retention_mode=retention_mode,
            record_access=False,
        )
        retrieved_ids = [str(r.chunk_id) for r in results]

        qrels[entry.query_id] = {cid: g for cid, g in entry.relevance.items() if g > 0}
        # ir_measures requires non-empty score values; use final_score directly.
        # Ties are broken by docid string order internally — acceptable for eval.
        run[entry.query_id] = {
            str(r.chunk_id): float(r.final_score) for r in results
        }
        retrieved_by_query[entry.query_id] = retrieved_ids
        query_text_by_id[entry.query_id] = entry.query

        if query_callback is not None:
            query_callback(i + 1, len(valid_entries))

    measures = _build_measures(top_k)

    # Per-query metrics — group by query_id
    per_query_metrics: dict[str, dict[str, float]] = defaultdict(dict)
    for metric in ir_measures.iter_calc(measures, qrels, run):
        per_query_metrics[metric.query_id][str(metric.measure)] = float(metric.value)

    per_query = [
        EvalResult(
            query_id=qid,
            query=query_text_by_id[qid],
            retrieved_chunk_ids=retrieved_by_query[qid],
            metrics=per_query_metrics.get(qid, {}),
        )
        for qid in (e.query_id for e in valid_entries)
    ]

    # Aggregate (mean across queries)
    aggregate_raw = ir_measures.calc_aggregate(measures, qrels, run)
    aggregate_metrics = {str(m): float(v) for m, v in aggregate_raw.items()}

    report = EvalReport(
        num_queries=len(per_query),
        top_k=top_k,
        aggregate_metrics=aggregate_metrics,
        per_query=per_query,
    )

    logger.info(
        "Evaluation complete: %d queries, metrics=%s",
        report.num_queries,
        {k: f"{v:.4f}" for k, v in aggregate_metrics.items()},
    )
    return report
