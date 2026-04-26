"""SearchService — encapsulates RetrievalPipeline construction and search.

Eliminates the PipelineDeps + RetrievalPipeline manual assembly duplicated
in CLI and MCP entry points.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.pipeline_deps import PipelineDeps
from app.core.schemas import RetrievalResult
from app.core.vectordb import QdrantService
from app.ingestion.embedder import BaseEmbedder
from app.retrieval import workflows
from app.retrieval.engine import instantiate
from app.retrieval.graph import inject_normalizers, validate
from app.retrieval.pipeline import RetrievalPipeline
from app.retrieval.topology import TopologySpecJSON, resolve_topology

logger = logging.getLogger(__name__)


class SearchService:
    """Thin service that owns RetrievalPipeline lifecycle for callers.

    Constructor takes individual components (embedder, qdrant_client, session_factory),
    internally assembles PipelineDeps and retrieves the default topology DAG via
    workflows.build_from_settings(), then creates the RetrievalPipeline.

    Usage::

        svc = SearchService(embedder=..., qdrant_client=..., session_factory=...)
        results = await svc.search("query text", top_k=10)
    """

    def __init__(
        self,
        embedder: BaseEmbedder,
        qdrant_client: QdrantService,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._embedder = embedder
        self._qdrant_client = qdrant_client
        self._session_factory = session_factory
        deps = PipelineDeps(
            embedder=embedder,
            qdrant_client=qdrant_client,
            session_factory=session_factory,
        )
        self._pipeline = RetrievalPipeline(
            dag=workflows.build_from_settings(deps),
            embedder=embedder,
            session_factory=session_factory,
        )

    @property
    def pipeline(self) -> RetrievalPipeline:
        """Expose the internal RetrievalPipeline for evaluation / raw DAG access."""
        return self._pipeline

    async def _build_pipeline_with_topology(
        self,
        topology_spec: TopologySpecJSON | None,
        session: AsyncSession,
        default_topology_name: str,
    ) -> RetrievalPipeline:
        graph_spec = await resolve_topology(topology_spec, default_topology_name, session)
        validate(graph_spec)
        graph_spec = inject_normalizers(graph_spec)
        deps = PipelineDeps(
            embedder=self._embedder,
            qdrant_client=self._qdrant_client,
            session_factory=self._session_factory,
        )
        dag = instantiate(graph_spec, deps)
        return RetrievalPipeline(
            dag=dag,
            embedder=self._embedder,
            session_factory=self._session_factory,
        )

    async def search(
        self,
        query_text: str,
        top_k: int = 10,
        retention_mode: str = "prefer_recent",
        filters: dict[str, Any] | None = None,
        record_access: bool = True,
        topology_spec: TopologySpecJSON | None = None,
        topology_session: AsyncSession | None = None,
        default_topology_name: str = "default",
    ) -> list[RetrievalResult]:
        """Execute retrieval end-to-end.

        If topology_spec and topology_session are provided, a custom pipeline
        is built on-the-fly; otherwise the default pipeline is used.

        Delegates to `RetrievalPipeline.search()`.
        """
        if topology_spec and topology_session:
            pipeline = await self._build_pipeline_with_topology(
                topology_spec, topology_session, default_topology_name,
            )
        else:
            pipeline = self._pipeline

        return await pipeline.search(
            query_text=query_text,
            top_k=top_k,
            filters=filters,
            retention_mode=retention_mode,  # type: ignore[arg-type]
            record_access=record_access,
        )
