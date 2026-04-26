"""DocumentService — wraps DocumentRepository CRUD and ChunkManager.delete_document().

Provides a single entry point for document operations, unifing the API and CLI
document management paths.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.chunk_manager import ChunkManager
from app.core.models import Document
from app.core.repository import DocumentRepository
from app.core.schemas import DocumentCreate

if TYPE_CHECKING:
    from app.core.vectordb import QdrantService


class DocumentService:

    @classmethod
    async def create(cls, session: AsyncSession, data: DocumentCreate) -> Document:
        return await DocumentRepository.create(session, data)

    @classmethod
    async def get_by_id(cls, session: AsyncSession, doc_id: UUID) -> Document | None:
        return await DocumentRepository.get_by_id(session, doc_id)

    @classmethod
    async def get_by_file_hash(cls, session: AsyncSession, file_hash: str) -> Document | None:
        return await DocumentRepository.get_by_file_hash(session, file_hash)

    @classmethod
    async def list_all(cls, session: AsyncSession) -> list[Document]:
        return await DocumentRepository.list_all(session)

    @classmethod
    async def delete(cls, session: AsyncSession, doc_id: UUID) -> bool:
        return await DocumentRepository.delete(session, doc_id)

    @classmethod
    async def delete_document(
        cls,
        session: AsyncSession,
        qdrant: QdrantService,
        doc_id: str,
    ) -> None:
        await ChunkManager.delete_document(session, qdrant, doc_id)
