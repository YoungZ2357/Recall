"""Retrieval pipeline: query → embed → search → normalize → rerank → output.

Current hardcoded topology:
    retriever[0] ─┐
    retriever[1] ─┼─ normalize → RRF → normalize → Reranker → hydrate → output
    ...          ─┘

Operators implement BaseRetriever / BaseReranker from operators.py.
The DAG orchestration engine described in docs/instructions/retrieval/topo_abstract.md
will replace this hardcoded topology; the current wiring becomes the default configuration.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.repository import ChunkAccessRepository, ChunkRepository
from app.core.schemas import RetrievalResult
from app.ingestion.embedder import BaseEmbedder
from app.retrieval.operators import BaseReranker, BaseRetriever, PipelineContext, SearchHit
from app.retrieval.searcher import normalize_scores, reciprocal_rank_fusion

logger = logging.getLogger(__name__)


class RetrievalPipeline:
    """End-to-end retrieval: embed → search → rerank → hydrate content."""

    def __init__(
        self,
        retrievers: list[BaseRetriever],
        reranker: BaseReranker,
        embedder: BaseEmbedder,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._retrievers = retrievers
        self._reranker = reranker
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
            filters: Optional metadata filters for vector search.
            retention_mode: Ebbinghaus retention strategy.
            record_access: Whether to write ChunkAccess logs. Set False for
                evaluation runs to avoid polluting Ebbinghaus decay data.

        Returns:
            Top-k results with scores and content, sorted by final_score desc.
        """
        # 1. Embed query
        vectors = await self._embedder.embed_batch([query_text])
        query_embedding = vectors[0]

        # 2. Build shared context for all operators
        context = PipelineContext(
            query_text=query_text,
            query_embedding=query_embedding,
            session_factory=self._session_factory,
            retention_mode=retention_mode,
            top_k=top_k,
            filters=filters,
        )

        # 3. Parallel retrieval across all registered retrievers
        raw_results = await asyncio.gather(
            *[r.retrieve(context) for r in self._retrievers],
            return_exceptions=True,
        )

        hits_per_path: list[list[SearchHit]] = []
        for i, result in enumerate(raw_results):
            if isinstance(result, Exception):
                logger.warning("Retriever[%d] failed, skipping: %s", i, result)
            else:
                hits_per_path.append(result)

        if not hits_per_path:
            logger.info("No hits from any search path for query=%r", query_text)
            return []

        # 4. Normalize each path independently before fusion
        normalized_paths = [normalize_scores(hits) for hits in hits_per_path]

        # 5. RRF fusion (MergeDetector guard is built into reciprocal_rank_fusion)
        active_paths = [h for h in normalized_paths if h]
        fused_hits = reciprocal_rank_fusion(active_paths)
        fused_hits = normalize_scores(fused_hits)

        # 6. Rerank — session lifecycle managed internally by Reranker
        reranked = await self._reranker.rerank(fused_hits, context)
        if not reranked:
            logger.info("All hits filtered by reranker threshold for query=%r", query_text)
            return []

        # 7. Truncate to top_k
        reranked = reranked[:top_k]
        chunk_ids = [UUID(r.chunk_id) for r in reranked]

        # 8. Hydrate content + optionally record access
        async with self._session_factory() as session:
            content_map = await ChunkRepository.get_content_by_ids(session, chunk_ids)
            title_map = await ChunkRepository.get_document_titles_by_chunk_ids(session, chunk_ids)
            if record_access:
                await ChunkAccessRepository.record_access(session, chunk_ids)
            await session.commit()

        # 9. Assemble output — SearchHit.score is final_score after rerank stage
        results = [
            RetrievalResult(
                chunk_id=UUID(r.chunk_id),
                final_score=r.score,
                retrieval_score=r.retrieval_score or 0.0,
                metadata_score=r.metadata_score or 0.0,
                retention_score=r.retention_score or 0.0,
                content=content_map.get(r.chunk_id, ""),
                document_title=title_map.get(r.chunk_id),
            )
            for r in reranked
        ]

        logger.info(
            "Pipeline returned %d results for query=%r",
            len(results), query_text,
        )
        return results
