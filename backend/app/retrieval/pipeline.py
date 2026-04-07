"""Thin orchestration wrapper: embed → DAG execute → hydrate content → record access.

This module is the stable public interface for callers that want the full
search experience (embedding + retrieval + content hydration + access recording)
without wiring up the DAG directly.

The DAG itself is constructed externally (via workflows.*) and injected at
construction time, so each caller can supply whatever topology and deps it needs.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.repository import ChunkAccessRepository, ChunkRepository
from app.core.schemas import RetrievalResult
from app.ingestion.embedder import BaseEmbedder
from app.retrieval.operators import PipelineContext, SearchHit

if TYPE_CHECKING:
    from app.retrieval import engine

logger = logging.getLogger(__name__)


async def hydrate_results(
    hits: list[SearchHit],
    session_factory: async_sessionmaker[AsyncSession],
    record_access: bool = True,
) -> list[RetrievalResult]:
    """Fetch chunk content and document titles for a ranked SearchHit list.

    Optionally records chunk access timestamps for Ebbinghaus decay tracking.

    Args:
        hits: Ranked SearchHit list from the DAG pipeline.
        session_factory: Async SQLAlchemy session factory.
        record_access: Write ChunkAccess rows. Set False for evaluation runs
                       to avoid polluting retention data.

    Returns:
        RetrievalResult list in the same order as hits.
    """
    chunk_ids = [UUID(r.chunk_id) for r in hits]

    async with session_factory() as session:
        content_map = await ChunkRepository.get_content_by_ids(session, chunk_ids)
        title_map = await ChunkRepository.get_document_titles_by_chunk_ids(session, chunk_ids)
        if record_access:
            await ChunkAccessRepository.record_access(session, chunk_ids)
        await session.commit()

    return [
        RetrievalResult(
            chunk_id=UUID(r.chunk_id),
            final_score=r.score,
            retrieval_score=r.retrieval_score or 0.0,
            metadata_score=r.metadata_score or 0.0,
            retention_score=r.retention_score or 0.0,
            content=content_map.get(r.chunk_id, ""),
            document_title=title_map.get(r.chunk_id),
        )
        for r in hits
    ]


class RetrievalPipeline:
    """End-to-end retrieval: embed → DAG execute → hydrate content.

    The DAG is constructed externally (via workflows.*) and injected at init
    time, allowing each caller to supply a different topology with its own deps.
    Only the two resources used directly by this wrapper (embedder for query
    embedding, session_factory for hydration and access recording) are held here.
    """

    def __init__(
        self,
        dag: engine.RetrievalPipeline,
        embedder: BaseEmbedder,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._dag = dag
        self._embedder = embedder
        self._session_factory = session_factory

    async def search(
        self,
        query_text: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
        retention_mode: Literal["prefer_recent", "awaken_forgotten"] = "prefer_recent",
        record_access: bool = True,
    ) -> list[RetrievalResult]:
        """Run the full retrieval pipeline.

        Args:
            query_text: Natural language query.
            top_k: Number of results to return.
            filters: Optional metadata filters forwarded to VectorSearcher.
            retention_mode: Ebbinghaus retention strategy for reranking.
            record_access: Write ChunkAccess rows. Set False for eval runs.

        Returns:
            Top-k RetrievalResult list sorted by final_score descending.
        """
        # 1. Embed query
        vectors = await self._embedder.embed_batch([query_text])
        query_embedding = vectors[0]

        # 2. Build per-query context
        context = PipelineContext(
            query_text=query_text,
            query_embedding=query_embedding,
            session_factory=self._session_factory,
            retention_mode=retention_mode,
            top_k=top_k,
            filters=filters,
        )

        # 3. Execute pre-built DAG
        hits = await self._dag.execute(context)

        if not hits:
            logger.info("No hits from DAG pipeline for query=%r", query_text)
            return []

        # 4. Truncate to top_k, then hydrate
        hits = hits[:top_k]
        results = await hydrate_results(hits, self._session_factory, record_access=record_access)

        logger.info("Pipeline returned %d results for query=%r", len(results), query_text)
        return results
