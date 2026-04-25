"""Core types and abstract operator interfaces for the retrieval DAG system.

This module is the single source of truth for shared data structures and
operator contracts. Both searcher.py and reranker.py import from here.

Dependency order (no circular imports):
    operators.py  ←  searcher.py  ←  reranker.py  ←  pipeline.py
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Literal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# ---------------------------------------------------------------------------
# Intermediate data structures
# ---------------------------------------------------------------------------

@dataclass
class SearchHit:
    """Single retrieval result, unified format across all pipeline stages.

    Attributes:
        chunk_id: UUID string.
        score: Ranking score at the current stage.
               - After retrieval: cosine similarity or BM25 score.
               - After RRF:       normalized fused score.
               - After Reranker:  final weighted score (= retrieval_score * α
                                  + metadata_score * β + retention_score * γ).
        source: Path identifier — "vector" / "bm25" / "rrf" / "rerank".
        retrieval_score: Pre-rerank retrieval score. Populated by Reranker only.
        metadata_score:  Tag-semantic sub-score.   Populated by Reranker only.
        retention_score: Ebbinghaus sub-score.     Populated by Reranker only.
    """
    chunk_id: str
    score: float
    source: str
    retrieval_score: float | None = None
    metadata_score: float | None = None
    retention_score: float | None = None


@dataclass
class PipelineContext:
    """Per-query state flowing through the pipeline."""

    query_text: str
    query_embedding: list[float]
    session_factory: async_sessionmaker[AsyncSession]
    retention_mode: Literal["prefer_recent", "awaken_forgotten"] = "prefer_recent"
    top_k: int = 10
    filters: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Node type classification
# ---------------------------------------------------------------------------

class NodeType(Enum):
    SOURCE = "source"
    TRANSFORM = "transform"
    MERGE = "merge"
    NORMALIZER = "normalizer"  # internal only; injected automatically by DAG engine


# ---------------------------------------------------------------------------
# Abstract operator interfaces
# ---------------------------------------------------------------------------

class BaseRetriever(ABC):
    """Retriever operator: PipelineContext → list[SearchHit]."""

    node_type: ClassVar[NodeType] = NodeType.SOURCE

    @abstractmethod
    async def retrieve(self, context: PipelineContext) -> list[SearchHit]: ...


class BaseReranker(ABC):
    """Reranker operator: list[SearchHit] × PipelineContext → list[SearchHit].

    The returned SearchHit instances have source="rerank" and their score
    field set to the final weighted score. The retrieval_score,
    metadata_score, and retention_score breakdown fields are also populated.
    """

    node_type: ClassVar[NodeType] = NodeType.TRANSFORM

    @abstractmethod
    async def rerank(
        self, hits: list[SearchHit], context: PipelineContext
    ) -> list[SearchHit]: ...


class BaseMerger(ABC):
    """Merger operator: list[list[SearchHit]] × PipelineContext → list[SearchHit].

    In-degree ≥ 2. Fuses multiple ranked hit lists into a single list.
    """

    node_type: ClassVar[NodeType] = NodeType.MERGE

    @abstractmethod
    async def merge(
        self, hits_list: list[list[SearchHit]], context: PipelineContext
    ) -> list[SearchHit]: ...
