"""ReindexService — encapsulates ChunkManager.reindex_document() and document selection."""

from __future__ import annotations

import logging
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.chunk_manager import ChunkManager, ReindexResult
from app.core.models import Document, SyncStatus
from app.core.repository import DocumentRepository
from app.core.vectordb import QdrantService
from app.ingestion.embedder import BaseEmbedder

logger = logging.getLogger(__name__)


class ReindexService:
    """Service that owns reindex logic for callers.

    All three reindex methods manage their own database sessions internally,
    so callers never interact with SQLAlchemy directly.

    Usage::

        svc = ReindexService(session_factory=..., qdrant_client=..., embedder=...)
        result = await svc.reindex_document("abc123")
        results = await svc.reindex_dirty()
        results = await svc.reindex_all()
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        qdrant_client: QdrantService,
        embedder: BaseEmbedder,
    ) -> None:
        self._session_factory = session_factory
        self._qdrant_client = qdrant_client
        self._embedder = embedder

    async def reindex_document(
        self,
        doc_id: str,
        *,
        batch_size: int = 100,
        chunk_callback: Callable[[int, int], None] | None = None,
    ) -> ReindexResult:
        """Re-embed all chunks for a single document.

        Args:
            doc_id: Document UUID as string.
            batch_size: Number of chunks per embedding batch.
            chunk_callback: Optional progress callback (current, total).

        Returns:
            ReindexResult with per-chunk counts and health check outcome.

        Raises:
            DocumentNotFoundError: Document does not exist.
            InvalidSyncStatusTransitionError: Document not in a reindexable state.
        """
        async with self._session_factory() as session:
            return await ChunkManager.reindex_document(
                session,
                self._qdrant_client,
                self._embedder,
                doc_id,
                batch_size=batch_size,
                chunk_callback=chunk_callback,
            )

    async def reindex_dirty(self) -> list[ReindexResult]:
        """Reindex all documents with DIRTY or FAILED sync status.

        Returns:
            One ReindexResult per document processed.
        """
        async with self._session_factory() as session:
            all_docs = await DocumentRepository.list_all(session)
            docs = [
                d for d in all_docs
                if d.sync_status in (SyncStatus.DIRTY, SyncStatus.FAILED)
            ]
            return await self._reindex_docs(docs)

    async def reindex_all(self) -> list[ReindexResult]:
        """Reindex every document regardless of sync status.

        Returns:
            One ReindexResult per document processed.
        """
        async with self._session_factory() as session:
            docs = await DocumentRepository.list_all(session)
            return await self._reindex_docs(docs)

    async def _reindex_docs(self, docs: list[Document]) -> list[ReindexResult]:
        """Internal helper: reindex a list of documents sequentially.

        Each document gets its own session for isolation.
        """
        results: list[ReindexResult] = []
        for doc in docs:
            doc_id_str = str(doc.document_id)
            try:
                result = await self.reindex_document(doc_id_str)
                results.append(result)
            except Exception as exc:
                logger.error("Failed to reindex document %s: %s", doc_id_str, exc)
                results.append(ReindexResult(
                    total=0,
                    succeeded=0,
                    failed=0,
                    failed_chunk_ids=[],
                    health_check_passed=False,
                    errors=[str(exc)],
                ))
        return results
