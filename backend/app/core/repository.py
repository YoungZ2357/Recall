import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, text, update
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
    async def delete_by_id(cls, session: AsyncSession, chunk_id: UUID) -> None:
        """Delete a single Chunk by chunk_id. ChunkAccess rows cascade automatically."""
        await session.execute(delete(Chunk).where(Chunk.chunk_id == chunk_id))
        await session.flush()

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


    @classmethod
    async def get_all_unique_tags(cls, session: AsyncSession) -> list[str]:
        """Return a sorted list of all unique tag strings across all chunks."""
        result = await session.execute(
            select(Chunk.tags).where(Chunk.tags != "[]").distinct()
        )
        tag_set: set[str] = set()
        for (tags_json,) in result.all():
            if not tags_json:
                continue
            try:
                tags = json.loads(tags_json)
                if isinstance(tags, list):
                    tag_set.update(t for t in tags if isinstance(t, str) and t)
            except (json.JSONDecodeError, TypeError):
                pass
        return sorted(tag_set)

    @classmethod
    async def list_by_document_without_context(
        cls, session: AsyncSession, doc_id: UUID
    ) -> list[Chunk]:
        """Return chunks for a document where context is NULL, ordered by chunk_index."""
        result = await session.execute(
            select(Chunk)
            .where(Chunk.document_id == doc_id, Chunk.context.is_(None))
            .order_by(Chunk.chunk_index.asc())
        )
        return list(result.scalars().all())

    @classmethod
    async def bulk_update_context(
        cls,
        session: AsyncSession,
        updates: list[tuple[UUID, str]],
        sync_status: SyncStatus = SyncStatus.DIRTY,
    ) -> int:
        """Bulk update context field and sync_status for given (chunk_id, context) pairs.

        Args:
            session: Database session.
            updates: List of (chunk_id, context_text) tuples.
            sync_status: Status to set after update (default DIRTY).

        Returns:
            Number of rows updated.
        """
        if not updates:
            return 0
        count = 0
        for chunk_id, context_text in updates:
            result = await session.execute(
                update(Chunk)
                .where(Chunk.chunk_id == chunk_id)
                .values(context=context_text, context_embedded=False, sync_status=sync_status)
            )
            count += result.rowcount
        await session.flush()
        return count

    @classmethod
    async def get_content_by_ids(
        cls, session: AsyncSession, chunk_ids: list[UUID]
    ) -> dict[str, str]:
        """Return {chunk_id_str: content} for given chunk_ids."""
        if not chunk_ids:
            return {}
        result = await session.execute(
            select(Chunk.chunk_id, Chunk.content).where(Chunk.chunk_id.in_(chunk_ids))
        )
        return {str(row.chunk_id): row.content for row in result.all()}

    @classmethod
    async def get_document_titles_by_chunk_ids(
        cls, session: AsyncSession, chunk_ids: list[UUID]
    ) -> dict[str, str | None]:
        """Return {chunk_id_str: document_title} by joining chunks → documents."""
        if not chunk_ids:
            return {}
        result = await session.execute(
            select(Chunk.chunk_id, Document.title)
            .join(Document, Chunk.document_id == Document.document_id)
            .where(Chunk.chunk_id.in_(chunk_ids))
        )
        return {str(row.chunk_id): row.title for row in result.all()}


class FTSRepository:
    """Repository for the FTS5 virtual table (BM25 full-text search)."""

    @staticmethod
    async def bulk_insert(session: AsyncSession, chunks: list[Chunk]) -> None:
        """Insert chunks into the FTS index. Uses INSERT OR IGNORE for idempotency."""
        if not chunks:
            return
        await session.execute(
            text(
                "INSERT OR IGNORE INTO chunks_fts(chunk_id, document_id, content) "
                "VALUES (:cid, :did, :content)"
            ),
            [
                {"cid": str(c.chunk_id), "did": str(c.document_id), "content": c.content}
                for c in chunks
            ],
        )

    @staticmethod
    async def delete_by_document(session: AsyncSession, document_id: UUID) -> None:
        """Remove all FTS rows for a document."""
        await session.execute(
            text("DELETE FROM chunks_fts WHERE document_id = :did"),
            {"did": str(document_id)},
        )

    @staticmethod
    async def delete_by_chunk_id(session: AsyncSession, chunk_id: UUID) -> None:
        """Remove the FTS row for a single chunk."""
        await session.execute(
            text("DELETE FROM chunks_fts WHERE chunk_id = :cid"),
            {"cid": str(chunk_id)},
        )

    @staticmethod
    async def fts_search(
        session: AsyncSession,
        query_text: str,
        top_k: int,
        document_id: str | None = None,
    ) -> list[tuple[str, float]]:
        """Full-text BM25 search.

        Returns:
            List of (chunk_id_str, raw_bm25_score) ordered by relevance ascending
            (SQLite bm25() returns negative values — lower means more relevant).
        """
        safe_query = query_text.replace('"', " ").strip()
        if not safe_query:
            return []

        params: dict = {"q": f'"{safe_query}"', "top_k": top_k}
        filter_clause = ""
        if document_id:
            filter_clause = "AND document_id = :doc_id"
            params["doc_id"] = document_id

        result = await session.execute(
            text(
                f"SELECT chunk_id, bm25(chunks_fts) AS score FROM chunks_fts "
                f"WHERE chunks_fts MATCH :q {filter_clause} "
                f"ORDER BY score LIMIT :top_k"
            ),
            params,
        )
        return [(row.chunk_id, row.score) for row in result]


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
