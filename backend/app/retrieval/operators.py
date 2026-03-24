"""Abstract operator interfaces for the retrieval DAG system.

These base classes define the type contract for future DAG orchestration.
Current pipeline uses concrete types directly; operators.py prepares
for runtime-configurable topologies.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.retrieval.searcher import SearchHit


@dataclass
class PipelineContext:
    """Per-query state flowing through the pipeline."""

    query_text: str
    query_embedding: list[float]
    session_factory: async_sessionmaker[AsyncSession]
    retention_mode: Literal["prefer_recent", "awaken_forgotten"] = "prefer_recent"
    top_k: int = 10
    filters: dict[str, Any] | None = None


class BaseRetriever(ABC):
    """Retriever operator: context → list[SearchHit]."""

    @abstractmethod
    async def retrieve(self, context: PipelineContext) -> list[SearchHit]: ...


class BaseReranker(ABC):
    """Reranker operator: list[SearchHit] → list[SearchHit]."""

    @abstractmethod
    async def rerank(
        self, hits: list[SearchHit], context: PipelineContext
    ) -> list[SearchHit]: ...
