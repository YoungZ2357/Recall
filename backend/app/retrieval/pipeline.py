"""Retrieval pipeline: query → embed → search → normalize → rerank → output.

Current topology is hardcoded:
    VectorSearcher ─┐
                    ├─ RRF → normalize_scores → Reranker → content hydration → output
    BM25Searcher   ─┘

Future DAG orchestration engine will replace the hardcoded topology
with a configurable graph; see docs/instructions/retrieval/topo_abstract.md.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.core.repository import ChunkAccessRepository, ChunkRepository
from app.core.schemas import RetrievalResult
from app.ingestion.embedder import BaseEmbedder
from app.retrieval.reranker import Reranker
from app.retrieval.searcher import (
    BM25Searcher,
    SearchQuery,
    VectorSearcher,
    normalize_scores,
    reciprocal_rank_fusion,
)

logger = logging.getLogger(__name__)


class RetrievalPipeline:
    """End-to-end retrieval: embed → search → rerank → hydrate content."""

    def __init__(
        self,
        vector_searcher: VectorSearcher,
        bm25_searcher: BM25Searcher,
        reranker: Reranker,
        embedder: BaseEmbedder,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._vector_searcher = vector_searcher
        self._bm25_searcher = bm25_searcher
        self._reranker = reranker
        self._embedder = embedder
        self._session_factory = session_factory
        self._settings = settings

    async def search(
        self,
        query_text: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
        retention_mode: Literal["prefer_recent", "awaken_forgotten"] = "prefer_recent",
    ) -> list[RetrievalResult]:
        """Run the full retrieval pipeline.

        Args:
            query_text: Natural language query.
            top_k: Number of results to return.
            filters: Optional metadata filters for vector search.
            retention_mode: Ebbinghaus retention strategy.

        Returns:
            Top-k results with scores and content, sorted by final_score desc.
        """
        # 1. Embed query
        vectors = await self._embedder.embed_batch([query_text])
        query_embedding = vectors[0]

        # 2. Parallel vector + BM25 search (recall window larger than final top_k)
        search_query = SearchQuery(
            text=query_text,
            embedding=query_embedding,
            top_k=20,
            score_threshold=self._settings.vector_score_threshold,
            filters=filters,
        )
        vector_hits_raw, bm25_hits_raw = await asyncio.gather(
            self._vector_searcher.search(search_query),
            self._bm25_searcher.search(search_query),
            return_exceptions=True,
        )
        if isinstance(vector_hits_raw, Exception):
            logger.warning("Vector search failed, degrading to BM25 only: %s", vector_hits_raw)
            vector_hits_raw = []
        if isinstance(bm25_hits_raw, Exception):
            logger.warning("BM25 search failed, degrading to vector only: %s", bm25_hits_raw)
            bm25_hits_raw = []

        if not vector_hits_raw and not bm25_hits_raw:
            logger.info("No hits from any search path for query=%r", query_text)
            return []

        # 3. Normalize each path independently before fusion
        vector_hits = normalize_scores(vector_hits_raw)
        bm25_hits = normalize_scores(bm25_hits_raw)

        # 4. RRF fusion — guard inside reciprocal_rank_fusion handles single-path pass-through
        active_paths = [h for h in [vector_hits, bm25_hits] if h]
        hits = reciprocal_rank_fusion(active_paths)

        # 5. Rerank (read-only session)
        async with self._session_factory() as session:
            rerank_results = await self._reranker.rerank(
                session, query_embedding, hits, retention_mode
            )
        if not rerank_results:
            logger.info("All hits filtered by reranker threshold for query=%r", query_text)
            return []

        # 6. Truncate to top_k
        rerank_results = rerank_results[:top_k]
        chunk_ids = [UUID(str(r.chunk_id)) for r in rerank_results]

        # 7. Hydrate content + record access (write session)
        async with self._session_factory() as session:
            content_map = await ChunkRepository.get_content_by_ids(session, chunk_ids)
            title_map = await ChunkRepository.get_document_titles_by_chunk_ids(session, chunk_ids)
            await ChunkAccessRepository.record_access(session, chunk_ids)
            await session.commit()

        # 8. Assemble output
        results = [
            RetrievalResult(
                chunk_id=r.chunk_id,
                final_score=r.final_score,
                retrieval_score=r.retrieval_score,
                metadata_score=r.metadata_score,
                retention_score=r.retention_score,
                content=content_map.get(str(r.chunk_id), ""),
                document_title=title_map.get(str(r.chunk_id)),
            )
            for r in rerank_results
        ]

        logger.info(
            "Pipeline returned %d results for query=%r",
            len(results), query_text,
        )
        return results
