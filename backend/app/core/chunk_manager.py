"""
Chunk lifecycle manager for SQLite ↔ Qdrant coordination.

This module implements the state machine for Document sync_status transitions
and performs health checks to ensure consistency between SQLite (source of truth)
and Qdrant (derived store).

All methods are class methods to facilitate dependency injection.
The caller must provide database session and Qdrant service instances.
"""

import logging
from typing import Literal, Optional
from uuid import UUID

from qdrant_client.models import FieldCondition, Filter, MatchValue
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ChunkCountMismatchError,
    ChunkIDMismatchError,
    DocumentNotFoundError,
    InvalidSyncStatusTransitionError,
    HealthCheckError,
    SyncError,
)
from app.core.models import Document, Chunk, SyncStatus
from app.core.vectordb import QdrantService

logger = logging.getLogger(__name__)

HealthCheckLevel = Literal["fast", "full"]


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
                    detail=f"Health check failed and status update failed: {e}"
                ) from e
            raise  # Always re-raise original HealthCheckError