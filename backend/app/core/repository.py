import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import Chunk, ChunkAccess, Document, SyncStatus
from app.core.schemas import ChunkCreate, DocumentCreate


@dataclass
class AccessSummary:
    """Aggregated access stats for a single chunk."""
    last_accessed_at: datetime | None
    access_count: int


class DocumentRepository:

    @classmethod
    async def create(cls, session: AsyncSession, data: DocumentCreate) -> Document:
        """Insert a new Document, auto-generate UUID and set sync_status=PENDING."""
        doc = Document(
            document_id=uuid4(),
            title=data.title,
            source_path=data.source_path,
            file_hash=data.file_hash,
            sync_status=SyncStatus.PENDING,
        )
        session.add(doc)
        await session.flush()
        return doc

    @classmethod
    async def get_by_id(cls, session: AsyncSession, doc_id: UUID) -> Document | None:
        """Return Document or None."""
        result = await session.execute(
            select(Document).where(Document.document_id == doc_id)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def get_by_file_hash(cls, session: AsyncSession, file_hash: str) -> Document | None:
        """Return existing Document with matching file_hash, or None (dedup check)."""
        result = await session.execute(
            select(Document).where(Document.file_hash == file_hash)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def list_all(cls, session: AsyncSession) -> list[Document]:
        """Return all Documents ordered by created_at DESC."""
        result = await session.execute(
            select(Document).order_by(Document.created_at.desc())
        )
        return list(result.scalars().all())

    @classmethod
    async def delete(cls, session: AsyncSession, doc_id: UUID) -> bool:
        """Delete Document by ID. Returns True if deleted, False if not found.
        Cascade deletes associated Chunks via ORM relationship."""
        doc = await cls.get_by_id(session, doc_id)
        if doc is None:
            return False
        await session.delete(doc)
        await session.flush()
        return True


class ChunkRepository:

    @classmethod
    async def bulk_create(
        cls, session: AsyncSession, chunks: list[ChunkCreate]
    ) -> list[Chunk]:
        """Insert multiple Chunks in one flush, auto-generate UUIDs."""
        orm_chunks = [
            Chunk(
                chunk_id=uuid4(),
                document_id=chunk.document_id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
            )
            for chunk in chunks
        ]
        session.add_all(orm_chunks)
        await session.flush()
        return orm_chunks

    @classmethod
    async def get_by_id(cls, session: AsyncSession, chunk_id: UUID) -> Chunk | None:
        """Return Chunk or None."""
        result = await session.execute(
            select(Chunk).where(Chunk.chunk_id == chunk_id)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def list_by_document(cls, session: AsyncSession, doc_id: UUID) -> list[Chunk]:
        """Return all Chunks for a Document, ordered by chunk_index ASC."""
        result = await session.execute(
            select(Chunk)
            .where(Chunk.document_id == doc_id)
            .order_by(Chunk.chunk_index.asc())
        )
        return list(result.scalars().all())

    @classmethod
    async def delete_by_document(cls, session: AsyncSession, doc_id: UUID) -> int:
        """Delete all Chunks belonging to doc_id. Returns deleted count."""
        result = await session.execute(
            delete(Chunk).where(Chunk.document_id == doc_id)
        )
        await session.flush()
        return result.rowcount

    @classmethod
    async def list_by_document_and_status(
        cls,
        session: AsyncSession,
        doc_id: UUID,
        status: SyncStatus,
    ) -> list[Chunk]:
        """Return Chunks for a Document with given sync_status, ordered by chunk_index ASC."""
        result = await session.execute(
            select(Chunk)
            .where(Chunk.document_id == doc_id, Chunk.sync_status == status)
            .order_by(Chunk.chunk_index.asc())
        )
        return list(result.scalars().all())

    @classmethod
    async def bulk_update_status(
        cls,
        session: AsyncSession,
        chunk_ids: list[UUID],
        status: SyncStatus,
    ) -> int:
        """Bulk UPDATE sync_status for given chunk_ids. Returns updated row count."""
        if not chunk_ids:
            return 0
        result = await session.execute(
            update(Chunk)
            .where(Chunk.chunk_id.in_(chunk_ids))
            .values(sync_status=status)
        )
        await session.flush()
        return result.rowcount

    @classmethod
    async def get_tags_by_ids(
        cls, session: AsyncSession, chunk_ids: list[UUID]
    ) -> dict[str, list[str]]:
        """Return {chunk_id_str: [tag, ...]} for given chunk_ids.

        Tags are stored as JSON-encoded list[str] in the `tags` column.
        """
        if not chunk_ids:
            return {}
        result = await session.execute(
            select(Chunk.chunk_id, Chunk.tags).where(Chunk.chunk_id.in_(chunk_ids))
        )
        return {
            str(row.chunk_id): json.loads(row.tags) if row.tags else []
            for row in result.all()
        }

    @classmethod
    async def get_document_weights_by_chunk_ids(
        cls, session: AsyncSession, chunk_ids: list[UUID]
    ) -> dict[str, float]:
        """Return {chunk_id_str: document_weight} by joining chunks → documents."""
        if not chunk_ids:
            return {}
        result = await session.execute(
            select(Chunk.chunk_id, Document.weight)
            .join(Document, Chunk.document_id == Document.document_id)
            .where(Chunk.chunk_id.in_(chunk_ids))
        )
        return {str(row.chunk_id): row.weight for row in result.all()}


class ChunkAccessRepository:
    """Repository for append-only chunk access logs."""

    @classmethod
    async def record_access(
        cls, session: AsyncSession, chunk_ids: list[UUID]
    ) -> None:
        """Batch insert access records for the given chunk_ids."""
        if not chunk_ids:
            return
        accesses = [
            ChunkAccess(access_id=uuid4(), chunk_id=cid)
            for cid in chunk_ids
        ]
        session.add_all(accesses)
        await session.flush()

    @classmethod
    async def get_access_summary(
        cls, session: AsyncSession, chunk_ids: list[UUID]
    ) -> dict[str, AccessSummary]:
        """Return aggregated access stats for each chunk_id.

        Returns:
            {chunk_id_str: AccessSummary} — chunks with no access records are omitted.
        """
        if not chunk_ids:
            return {}
        result = await session.execute(
            select(
                ChunkAccess.chunk_id,
                func.max(ChunkAccess.accessed_at).label("last_accessed_at"),
                func.count(ChunkAccess.access_id).label("access_count"),
            )
            .where(ChunkAccess.chunk_id.in_(chunk_ids))
            .group_by(ChunkAccess.chunk_id)
        )
        return {
            str(row.chunk_id): AccessSummary(
                last_accessed_at=row.last_accessed_at,
                access_count=row.access_count,
            )
            for row in result.all()
        }
