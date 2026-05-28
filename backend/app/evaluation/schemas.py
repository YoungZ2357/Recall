"""Pydantic models for evaluation test sets and reports.

Schema uses graded relevance (0-3) following TREC-style pooled qrels.
Grading rubric: 3 = direct answer, 2 = necessary supporting info,
1 = background only, 0 = irrelevant.
"""

from typing import Literal

from pydantic import BaseModel, Field


class QueryMetadata(BaseModel):
    """Metadata about a synthesized query."""
    query_type: str  # "factual" | "structural" | "comparative"
    generator_model: str
    grader_model: str | None = None  # populated after pool grading


class TestSetEntry(BaseModel):
    """Single entry in the evaluation test set.

    `relevance` maps chunk_id → grade (0-3). The source chunk (the one used
    to synthesize the query) is always present with grade=3.
    """
    query_id: str
    query: str
    relevance: dict[str, int] = Field(default_factory=dict)
    source_document_id: str
    source_chunk_id: str
    metadata: QueryMetadata


class EvalResult(BaseModel):
    """Per-query evaluation result.

    `metrics` is a dynamic dict keyed by ir_measures measure name
    (e.g. "nDCG@10", "R(rel=2)@10", "RR(rel=2)", "AP(rel=2)").
    """
    query_id: str
    query: str
    retrieved_chunk_ids: list[str]
    metrics: dict[str, float] = Field(default_factory=dict)


class RunConfig(BaseModel):
    """Configuration that produced an EvalReport.

    Persisted alongside the report so the frontend can render the historical
    runs table (topology + α/β/γ + mode) without re-deriving from filenames.

    `topology_name` is a free-form label (e.g. "vector" / "bm25" / "v_b_rrf"
    / "custom"); when None, the server's default topology was used.
    `weights` mirrors the reranker config keys (alpha/beta/gamma) when those
    were specified in the run's topology spec.
    `thresholds` captures the retriever and reranker score thresholds:
    {"vector": <VectorSearcher score_threshold>, "reranker": <Reranker score_threshold>}.
    """
    test_set_name: str
    mode: Literal["prefer_recent", "awaken_forgotten"]
    topology_name: str | None = None
    weights: dict[str, float] | None = None
    thresholds: dict[str, float] | None = None


class EvalReport(BaseModel):
    """Aggregate evaluation report."""
    num_queries: int
    top_k: int
    aggregate_metrics: dict[str, float] = Field(default_factory=dict)
    per_query: list[EvalResult]
    run_config: RunConfig | None = None
