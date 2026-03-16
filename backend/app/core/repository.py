from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import Chunk, Document, SyncStatus
from app.core.schemas import ChunkCreate, DocumentCreate


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
