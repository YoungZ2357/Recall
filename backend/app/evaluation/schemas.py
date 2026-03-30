"""Pydantic models for evaluation test sets and reports."""

from pydantic import BaseModel


class QueryMetadata(BaseModel):
    """Metadata about a synthesized query."""
    query_type: str  # "factual" | "structural" | "comparative"
    generator_model: str


class TestSetEntry(BaseModel):
    """Single entry in the evaluation test set."""
    query: str
    ground_truth_chunk_ids: list[str]
    source_document_id: str
    metadata: QueryMetadata


class EvalResult(BaseModel):
    """Per-query evaluation result."""
    query: str
    ground_truth_chunk_ids: list[str]
    retrieved_chunk_ids: list[str]
    reciprocal_rank: float
    recall_at_k: float
    ndcg_at_k: float


class EvalReport(BaseModel):
    """Aggregate evaluation report."""
    num_queries: int
    top_k: int
    mrr: float
    mean_ndcg_at_k: float
    mean_recall_at_k: float
    per_query: list[EvalResult]
