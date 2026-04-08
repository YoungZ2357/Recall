"""
Chunk lifecycle manager for SQLite ↔ Qdrant coordination.

This module implements the state machine for Document sync_status transitions
and performs health checks to ensure consistency between SQLite (source of truth)
and Qdrant (derived store).

All methods are class methods to facilitate dependency injection.
The caller must provide database session and Qdrant service instances.
"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal, Optional
from uuid import UUID

if TYPE_CHECKING:
    from app.ingestion.embedder import BaseEmbedder

from qdrant_client.models import FieldCondition, Filter, MatchValue, PointStruct
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ChunkCountMismatchError,
    ChunkIDMismatchError,
    ChunkNotFoundError,
    DocumentNotFoundError,
    InvalidSyncStatusTransitionError,
    HealthCheckError,
    SyncError,
)
from app.core.models import Document, Chunk, SyncStatus
from app.core.repository import ChunkRepository, DocumentRepository, FTSRepository
from app.core.schemas import ChunkCreate, ChunkIngest
from app.core.vectordb import QdrantService

logger = logging.getLogger(__name__)

HealthCheckLevel = Literal["fast", "full"]

@dataclass
class ReindexResult:
    total: int
    succeeded: int
    failed: int
    failed_chunk_ids: list[str]
    health_check_passed: bool
    errors: list[str]



class ChunkManager:
    """Coordinate SQLite ↔ Qdrant chunk lifecycle and consistency."""

    # ============================================================
    # State Transition Management
    # ============================================================

    @classmethod
    async def transition_status(
        cls,
        session: AsyncSession,
        doc_id: str,
        target_status: SyncStatus,
    ) -> None:
        """Validate and execute sync_status transition.

        Updates Document.sync_status to target_status after validating
        the transition is legal according to the state machine.

        Args:
            session: Database session for SQLite operations
            doc_id: Document UUID as string
            target_status: Desired sync_status

        Raises:
            InvalidSyncStatusTransitionError: Illegal state transition
            SyncError: Failed to update sync_status in database
        """
        # 1. Get current document and status
        doc = await cls._get_document(session, doc_id)
        current_status = doc.sync_status

        # 2. Skip if already in target state
        if current_status == target_status:
            logger.debug(f"Document {doc_id} already in {target_status}, skipping transition")
            return

        # 3. Validate transition legality
        cls._validate_transition(current_status, target_status, doc_id)

        # 4. Execute transition
        try:
            doc.sync_status = target_status
            # Document is already in session, changes are tracked automatically
            logger.info(
                f"Transitioned document {doc_id} from {current_status} to {target_status}"
            )
        except Exception as e:
            logger.error(f"Failed to transition document {doc_id}: {e}")
            raise SyncError(
                doc_id=doc_id,
                detail=f"Failed to update sync_status to {target_status}: {e}"
            ) from e

    @staticmethod
    def _validate_transition(
        from_status: SyncStatus,
        to_status: SyncStatus,
        doc_id: Optional[str] = None,
    ) -> None:
        """Validate state transition according to sync_mecanism.md rules.

        Legal transitions:
            Pending → Synced | Failed
            Synced  → Dirty
            Dirty   → Synced | Failed
            Failed  → Pending

        Args:
            from_status: Current sync_status
            to_status: Target sync_status
            doc_id: Optional document ID for error context

        Raises:
            InvalidSyncStatusTransitionError: Illegal transition
        """
        legal_transitions = {
            SyncStatus.PENDING: {SyncStatus.SYNCED, SyncStatus.FAILED},
            SyncStatus.SYNCED: {SyncStatus.DIRTY},
            SyncStatus.DIRTY: {SyncStatus.SYNCED, SyncStatus.FAILED},
            SyncStatus.FAILED: {SyncStatus.PENDING},
        }

        if to_status not in legal_transitions.get(from_status, set()):
            raise InvalidSyncStatusTransitionError(
                doc_id=doc_id,
                from_status=from_status.value,
                to_status=to_status.value,
                detail=f"Illegal transition {from_status} → {to_status}. "
                       f"Allowed from {from_status}: {legal_transitions[from_status]}"
            )

    @staticmethod
    async def _get_document(session: AsyncSession, doc_id: str) -> Document:
        """Get document by ID, raise DocumentNotFoundError if not found."""
        stmt = select(Document).where(Document.document_id == UUID(doc_id))
        result = await session.execute(stmt)
        doc = result.scalar_one_or_none()

        if doc is None:
            raise DocumentNotFoundError(doc_id=doc_id)
        return doc

    # ============================================================
    # Data Operations (Dual-Write / Dual-Delete)
    # ============================================================

    @classmethod
    async def write_chunks(
        cls,
        session: AsyncSession,
        qdrant_service: QdrantService,
        doc_id: str,
        chunks: list[ChunkIngest],
    ) -> list[Chunk]:
        """Write chunks to SQLite and Qdrant, then transition document to SYNCED.

        Caller contract:
            - On success: await session.commit() to persist SYNCED status.
            - On SyncError: await session.commit() to persist FAILED status, then reraise.
            - On other exceptions: await session.rollback().

        Args:
            session: Database session for SQLite operations
            qdrant_service: Qdrant service instance
            doc_id: Document UUID as string (must be in PENDING or DIRTY state)
            chunks: List of ChunkIngest containing content and pre-computed vectors

        Returns:
            List of created Chunk ORM objects

        Raises:
            DocumentNotFoundError: Document does not exist
            SyncError: Qdrant upsert failed; document transitioned to FAILED
        """
        if not chunks:
            return []

        # Validate document exists
        doc = await cls._get_document(session, doc_id)

        # NOTE: This method only appends new chunks; it does NOT remove existing ones.
        # For DIRTY documents (re-embedding after content change), the caller must first
        # delete the old chunks from both stores before calling write_chunks.
        # A dedicated replace_chunks() method should be implemented in Sprint 2 (reindex flow)
        # to encapsulate: delete old SQLite chunks + Qdrant points → write_chunks → SYNCED.
        if doc.sync_status not in (SyncStatus.PENDING, SyncStatus.DIRTY):
            raise SyncError(
                doc_id=doc_id,
                detail=f"write_chunks requires PENDING or DIRTY status, got {doc.sync_status.value}",
            )

        # Defensive assertion: context_embedded=True requires context to be non-None
        for chunk in chunks:
            if chunk.context is None and chunk.context_embedded:
                raise SyncError(
                    doc_id=doc_id,
                    detail=(
                        f"Illegal state: chunk_index={chunk.chunk_index} has "
                        f"context_embedded=True but context is None"
                    ),
                )

        # Insert chunks into SQLite
        chunk_creates = [
            ChunkCreate(
                document_id=chunk.document_id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
            )
            for chunk in chunks
        ]
        orm_chunks = await ChunkRepository.bulk_create(session, chunk_creates)

        # Write tags and context onto each ORM chunk
        for orm_chunk, chunk in zip(orm_chunks, chunks):
            if chunk.tags:
                orm_chunk.tags = json.dumps(chunk.tags, ensure_ascii=False)
            orm_chunk.context = chunk.context

        # Sync to FTS indexes (SQLite is source of truth; FTS mirrors it)
        await FTSRepository.bulk_insert(session, orm_chunks)
        await FTSRepository.context_bulk_insert(session, orm_chunks)

        # Build Qdrant points — use current time for created_at to avoid
        # async lazy-load of server_default attribute after flush
        now_iso = datetime.now(timezone.utc).isoformat()
        points = [
            PointStruct(
                id=str(orm_chunk.chunk_id),
                vector=chunk.vector,
                payload={
                    "document_id": str(orm_chunk.document_id),
                    "chunk_index": orm_chunk.chunk_index,
                    "tags": chunk.tags,
                    "created_at": now_iso,
                },
            )
            for orm_chunk, chunk in zip(orm_chunks, chunks)
        ]

        # Upsert to Qdrant; on failure mark document as FAILED
        try:
            await qdrant_service.upsert(points)
        except Exception as e:
            logger.error(f"Qdrant upsert failed for document {doc_id}: {e}")
            await cls.transition_status(session, doc_id, SyncStatus.FAILED)
            raise SyncError(
                doc_id=doc_id,
                detail=f"Qdrant upsert failed: {e}",
            ) from e

        # Set context_embedded based on the explicit signal from pipeline
        for orm_chunk, chunk in zip(orm_chunks, chunks):
            orm_chunk.context_embedded = chunk.context_embedded

        chunk_ids = [c.chunk_id for c in orm_chunks]
        await ChunkRepository.bulk_update_status(session, chunk_ids, SyncStatus.SYNCED)
        await cls.transition_status(session, doc_id, SyncStatus.SYNCED)
        return orm_chunks

    @classmethod
    async def delete_document(
        cls,
        session: AsyncSession,
        qdrant_service: QdrantService,
        doc_id: str,
    ) -> None:
        """Delete document and all its chunks from both Qdrant and SQLite.

        Deletion order: Qdrant first, then SQLite.
        If Qdrant fails, SQLite is untouched and the operation can be retried.

        Args:
            session: Database session for SQLite operations
            qdrant_service: Qdrant service instance
            doc_id: Document UUID as string

        Raises:
            DocumentNotFoundError: Document does not exist
            VectorDBError: Qdrant deletion failed; SQLite is unchanged
        """
        # Validate document exists
        await cls._get_document(session, doc_id)

        # Collect chunk IDs for Qdrant deletion
        sqlite_chunks = await ChunkRepository.list_by_document(session, UUID(doc_id))
        point_ids = [str(c.chunk_id) for c in sqlite_chunks]

        # Delete from Qdrant first (rebuildable store)
        try:
            await qdrant_service.delete(point_ids)
        except Exception as e:
            logger.error(f"Qdrant delete failed for document {doc_id}: {e}")
            raise  # SQLite untouched; caller can retry

        # Delete from FTS indexes before SQLite rows are removed
        await FTSRepository.delete_by_document(session, UUID(doc_id))
        await FTSRepository.context_delete_by_document(session, UUID(doc_id))

        # Delete document from SQLite (cascades to chunks via ORM relationship)
        await DocumentRepository.delete(session, UUID(doc_id))
        logger.info(f"Deleted document {doc_id} and {len(point_ids)} chunks from both stores")

    @classmethod
    async def delete_chunk(
        cls,
        session: AsyncSession,
        qdrant_service: QdrantService,
        chunk_id: str,
    ) -> None:
        """Delete a single chunk from Qdrant, FTS, and SQLite.

        Deletion order: Qdrant → FTS → SQLite.
        Unlike delete_document, Qdrant failure is non-blocking: a warning is logged
        and deletion continues so the chunk is always removed from SQLite (source of truth).

        Args:
            session: Database session for SQLite operations
            qdrant_service: Qdrant service instance
            chunk_id: Chunk UUID as string

        Raises:
            ChunkNotFoundError: Chunk does not exist in SQLite
        """
        chunk = await ChunkRepository.get_by_id(session, UUID(chunk_id))
        if chunk is None:
            raise ChunkNotFoundError(chunk_id)

        # Delete from Qdrant first (rebuildable store); failure is non-blocking
        try:
            await qdrant_service.delete([chunk_id])
        except Exception as e:
            logger.warning(f"Qdrant delete failed for chunk {chunk_id}: {e}")

        await FTSRepository.delete_by_chunk_id(session, UUID(chunk_id))
        await FTSRepository.context_delete_by_chunk_id(session, UUID(chunk_id))
        await ChunkRepository.delete_by_id(session, UUID(chunk_id))
        await session.commit()
        logger.info(f"Deleted chunk {chunk_id} from all stores")

    # ============================================================
    # Health Check (Consistency Verification)
    # ============================================================

    @classmethod
    async def health_check(
        cls,
        session: AsyncSession,
        qdrant_service: QdrantService,
        doc_id: str,
        level: HealthCheckLevel = "full",
    ) -> None:
        """Perform health check for document consistency between SQLite and Qdrant.

        Layer 1 (fast): Compare chunk counts
        Layer 2 (full): Compare chunk_id/point_id sets for bidirectional diff

        Args:
            session: Database session for SQLite operations
            qdrant_service: Qdrant service instance
            doc_id: Document UUID as string
            level: Check level ("fast" for layer 1 only, "full" for both layers).
                Defaults to "full".

        Raises:
            HealthCheckError: Any health check failure (subclasses contain details)
            DocumentNotFoundError: Document does not exist in SQLite
        """
        if level not in ("fast", "full"):
            raise ValueError('level must be "fast" or "full"')

        # Ensure document exists
        await cls._get_document(session, doc_id)

        # Layer 1: Fast check (chunk count comparison)
        await cls._layer1_fast_check(session, qdrant_service, doc_id)

        # If level="fast", stop here
        if level == "fast":
            logger.info(f"Layer 1 health check passed for document {doc_id}")
            return

        # Layer 2: Full check (bidirectional UUID diff)
        await cls._layer2_full_check(session, qdrant_service, doc_id)

        logger.info(f"Layer 2 health check passed for document {doc_id}")

    @staticmethod
    async def _layer1_fast_check(
        session: AsyncSession,
        qdrant_service: QdrantService,
        doc_id: str,
    ) -> None:
        """Layer 1: Compare SQLite chunk count vs Qdrant point count."""
        # SQLite count
        sqlite_count_stmt = (
            select(func.count())
            .select_from(Chunk)
            .where(Chunk.document_id == UUID(doc_id))
        )
        result = await session.execute(sqlite_count_stmt)
        sqlite_count = result.scalar_one() or 0

        # Qdrant count
        qdrant_filter = Filter(
            must=[
                FieldCondition(key="document_id", match=MatchValue(value=doc_id))
            ]
        )
        try:
            qdrant_count = await qdrant_service.count_by_filter(qdrant_filter)
        except Exception as e:
            logger.error(f"Failed to count Qdrant points for document {doc_id}: {e}")
            raise HealthCheckError(
                doc_id=doc_id,
                detail=f"Qdrant count operation failed: {e}"
            ) from e

        # Compare
        if sqlite_count != qdrant_count:
            raise ChunkCountMismatchError(
                doc_id=doc_id,
                expected=sqlite_count,
                actual=qdrant_count,
                detail=f"Chunk count mismatch: SQLite={sqlite_count}, Qdrant={qdrant_count}"
            )

        logger.debug(
            f"Layer 1 check passed for document {doc_id}: "
            f"SQLite={sqlite_count}, Qdrant={qdrant_count}"
        )

    @staticmethod
    async def _layer2_full_check(
        session: AsyncSession,
        qdrant_service: QdrantService,
        doc_id: str,
    ) -> None:
        """Layer 2: Compare chunk_id vs point_id sets for bidirectional diff."""
        # Get SQLite chunk_id set
        sqlite_ids_stmt = select(Chunk.chunk_id).where(
            Chunk.document_id == UUID(doc_id)
        )
        result = await session.execute(sqlite_ids_stmt)
        sqlite_ids = {str(chunk_id) for chunk_id in result.scalars().all()}

        # Get Qdrant point_id set
        qdrant_filter = Filter(
            must=[
                FieldCondition(key="document_id", match=MatchValue(value=doc_id))
            ]
        )
        try:
            qdrant_ids = await qdrant_service.scroll_ids(qdrant_filter)
        except Exception as e:
            logger.error(f"Failed to scroll Qdrant points for document {doc_id}: {e}")
            raise HealthCheckError(
                doc_id=doc_id,
                detail=f"Qdrant scroll operation failed: {e}"
            ) from e

        # Calculate bidirectional diffs
        missing_in_qdrant = sqlite_ids - qdrant_ids
        orphaned_in_qdrant = qdrant_ids - sqlite_ids

        # Raise error if any mismatch
        if missing_in_qdrant or orphaned_in_qdrant:
            raise ChunkIDMismatchError(
                doc_id=doc_id,
                missing_in_qdrant=missing_in_qdrant,
                orphaned_in_qdrant=orphaned_in_qdrant,
                detail=(
                    f"Chunk ID mismatch: "
                    f"missing_in_qdrant={len(missing_in_qdrant)}, "
                    f"orphaned_in_qdrant={len(orphaned_in_qdrant)}"
                )
            )

        logger.debug(
            f"Layer 2 check passed for document {doc_id}: "
            f"SQLite={len(sqlite_ids)} chunks, Qdrant={len(qdrant_ids)} points"
        )

    # ============================================================
    # Helper: Auto-mark dirty on health check failure
    # ============================================================

    @classmethod
    async def health_check_with_auto_dirty(
        cls,
        session: AsyncSession,
        qdrant_service: QdrantService,
        doc_id: str,
        level: HealthCheckLevel = "full",
    ) -> None:
        """Perform health check and automatically mark dirty on failure.

        This is the recommended wrapper for health checks in production.
        If health check fails, document status is updated according to current state
        and the exception is re-raised for caller handling.

        Args:
            session: Database session for SQLite operations
            qdrant_service: Qdrant service instance
            doc_id: Document UUID as string
            level: Check level ("fast" for layer 1 only, "full" for both layers).
                Defaults to "full".

        Raises:
            HealthCheckError: Health check failed, document status updated
            DocumentNotFoundError: Document does not exist in SQLite
            SyncError: Failed to update document status after health check failure
        """
        try:
            await cls.health_check(session, qdrant_service, doc_id, level)
        except HealthCheckError as e:
            logger.warning(f"Health check failed for document {doc_id}: {e}")
            try:
                doc = await cls._get_document(session, doc_id)
                if doc.sync_status == SyncStatus.SYNCED:
                    await cls.transition_status(session, doc_id, SyncStatus.DIRTY)
                elif doc.sync_status == SyncStatus.PENDING:
                    await cls.transition_status(session, doc_id, SyncStatus.FAILED)
                # DIRTY and FAILED states require no extra transition
            except Exception as transition_error:
                logger.error(
                    f"Failed to update status for document {doc_id} "
                    f"after health check failure: {transition_error}"
                )
                raise SyncError(
                    doc_id=doc_id,
                    detail=f"Health check failed and status update failed: {transition_error}"
                ) from transition_error
            raise  # Always re-raise original HealthCheckError

    # ============================================================
    # Reindex (Re-embed existing chunks)
    # ============================================================

    @classmethod
    async def reindex_document(
        cls,
        session: AsyncSession,
        qdrant_service: QdrantService,
        embedder: "BaseEmbedder",
        doc_id: str,
        batch_size: int = 100,
        chunk_callback: Callable[[int, int], None] | None = None,
    ) -> ReindexResult:
        """Re-embed all chunks for a document, overwriting Qdrant vectors.

        Marks document and all chunks DIRTY before processing, then processes
        in batches. Each batch is committed independently so partial progress
        is preserved on failure. Ends with a full health check.

        Args:
            session: Database session for SQLite operations
            qdrant_service: Qdrant service instance
            embedder: Embedder used to generate new vectors
            doc_id: Document UUID as string
            batch_size: Number of chunks to process per batch

        Returns:
            ReindexResult with counts and health check outcome

        Raises:
            DocumentNotFoundError: Document does not exist
            InvalidSyncStatusTransitionError: Document not in a reindexable state
        """
        # 1. Input validation
        await cls._get_document(session, doc_id)
        all_chunks = await ChunkRepository.list_by_document(session, UUID(doc_id))
        if not all_chunks:
            return ReindexResult(
                total=0,
                succeeded=0,
                failed=0,
                failed_chunk_ids=[],
                health_check_passed=True,
                errors=[],
            )

        # Extract needed data before any commits to avoid expired-object lazy-load issues
        chunk_data = [
            {
                "chunk_id": c.chunk_id,
                "document_id": c.document_id,
                "chunk_index": c.chunk_index,
                "content": c.content,
                "context": c.context,
                "tags": json.loads(c.tags) if c.tags else [],
            }
            for c in all_chunks
        ]
        all_chunk_ids = [d["chunk_id"] for d in chunk_data]

        # 2. Bulk mark DIRTY
        await cls.transition_status(session, doc_id, SyncStatus.DIRTY)
        await ChunkRepository.bulk_update_status(session, all_chunk_ids, SyncStatus.DIRTY)
        await session.commit()

        # 3. Batch processing
        failed_chunk_ids: list[str] = []
        errors: list[str] = []
        succeeded = 0
        total_chunks = len(chunk_data)

        for i in range(0, len(chunk_data), batch_size):
            batch = chunk_data[i : i + batch_size]
            batch_chunk_ids = [d["chunk_id"] for d in batch]

            try:
                # Build embed texts: use context + content when context exists
                embed_texts = [
                    d["context"] + "\n\n" + d["content"] if d["context"] else d["content"]
                    for d in batch
                ]
                vectors = await embedder.embed_batch(embed_texts)
                now_iso = datetime.now(timezone.utc).isoformat()
                points = [
                    PointStruct(
                        id=str(d["chunk_id"]),
                        vector=vector,
                        payload={
                            "document_id": str(d["document_id"]),
                            "chunk_index": d["chunk_index"],
                            "tags": d["tags"],
                            "created_at": now_iso,
                        },
                    )
                    for d, vector in zip(batch, vectors)
                ]
                await qdrant_service.upsert(points)

                # Set context_embedded per chunk based on whether context was used
                for d in batch:
                    chunk = await ChunkRepository.get_by_id(session, d["chunk_id"])
                    if chunk is not None:
                        chunk.context_embedded = d["context"] is not None

                await ChunkRepository.bulk_update_status(session, batch_chunk_ids, SyncStatus.SYNCED)
                await session.commit()
                succeeded += len(batch)
                if chunk_callback is not None:
                    chunk_callback(succeeded, total_chunks)
            except Exception as e:
                logger.error(
                    f"Batch reindex failed for document {doc_id}, "
                    f"batch offset {i}: {e}"
                )
                await ChunkRepository.bulk_update_status(session, batch_chunk_ids, SyncStatus.FAILED)
                await session.commit()
                failed_chunk_ids.extend(str(cid) for cid in batch_chunk_ids)
                errors.append(str(e))
                if chunk_callback is not None:
                    chunk_callback(succeeded, total_chunks)

        # 4. Health check
        health_check_passed = False
        try:
            await cls.health_check(session, qdrant_service, doc_id, level="full")
            await cls.transition_status(session, doc_id, SyncStatus.SYNCED)
            await session.commit()
            health_check_passed = True
        except HealthCheckError as e:
            logger.error(f"Health check failed after reindex for document {doc_id}: {e}")
            await cls.transition_status(session, doc_id, SyncStatus.FAILED)
            await session.commit()
            errors.append(str(e))

        return ReindexResult(
            total=len(chunk_data),
            succeeded=succeeded,
            failed=len(failed_chunk_ids),
            failed_chunk_ids=failed_chunk_ids,
            health_check_passed=health_check_passed,
            errors=errors,
        )