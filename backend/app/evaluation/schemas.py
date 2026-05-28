"""Pydantic models for evaluation test sets and reports.

Schema uses graded relevance (0-3) following TREC-style pooled qrels.
Grading rubric: 3 = direct answer, 2 = necessary supporting info,
1 = background only, 0 = irrelevant.
"""

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


class EvalReport(BaseModel):
    """Aggregate evaluation report."""
    num_queries: int
    top_k: int
    aggregate_metrics: dict[str, float] = Field(default_factory=dict)
    per_query: list[EvalResult]
