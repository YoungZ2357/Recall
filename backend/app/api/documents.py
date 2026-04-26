import asyncio
import json
import logging
import shutil
from pathlib import Path as FilePath
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi import File as FastAPIFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.dependencies import (
    IngestionServiceDep,
    QdrantDep,
    SessionDep,
    SettingsDep,
    get_session_factory,
)
from app.core.exceptions import DocumentNotFoundError, IngestionError, UnsupportedFileTypeError
from app.core.models import Chunk, SyncStatus
from app.core.repository import ChunkRepository
from app.core.schemas import DeleteResponse, DocumentDetail, DocumentSummary, UploadResponse
from app.services import DocumentService

logger = logging.getLogger(__name__)

router = APIRouter()

_SUPPORTED_EXTENSIONS = {".txt", ".md", ".markdown", ".pdf"}
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB


def _write_file(dest: FilePath, file_obj) -> None:
    with open(dest, "wb") as f:
        shutil.copyfileobj(file_obj, f)


def _extract_file_type(source_path: str | None) -> str:
    if not source_path:
        return "unknown"
    return FilePath(source_path).suffix.lower().lstrip(".")


def _extract_filename(source_path: str | None, title: str | None) -> str:
    if source_path:
        return FilePath(source_path).name
    return title or "untitled"


async def _get_chunk_stats(
    session,
    doc_id: UUID,
) -> tuple[int, int]:
    total_result = await session.execute(
        select(func.count()).select_from(Chunk).where(Chunk.document_id == doc_id)
    )
    total = total_result.scalar_one() or 0

    synced_result = await session.execute(
        select(func.count())
        .select_from(Chunk)
        .where(Chunk.document_id == doc_id, Chunk.sync_status == SyncStatus.SYNCED)
    )
    synced = synced_result.scalar_one() or 0
    return total, synced


async def _get_doc_tags(session, doc_id: UUID) -> list[str]:
    chunks = await ChunkRepository.list_by_document(session, doc_id)
    tag_set: set[str] = set()
    for c in chunks:
        if c.tags:
            try:
                tags = json.loads(c.tags)
                if isinstance(tags, list):
                    tag_set.update(t for t in tags if isinstance(t, str) and t)
            except (json.JSONDecodeError, TypeError):
                pass
    return sorted(tag_set)


@router.get("", response_model=list[DocumentSummary])
async def list_documents(
    session: SessionDep,
) -> list[DocumentSummary]:
    docs = await DocumentService.list_all(session)
    result: list[DocumentSummary] = []
    for doc in docs:
        total, _synced = await _get_chunk_stats(session, doc.document_id)
        result.append(
            DocumentSummary(
                doc_id=str(doc.document_id),
                filename=_extract_filename(doc.source_path, doc.title),
                file_type=_extract_file_type(doc.source_path),
                chunk_count=total,
                created_at=doc.created_at.isoformat() if doc.created_at else "",
                weight=doc.weight,
                sync_status=doc.sync_status.value,
            )
        )
    return result


@router.get("/{doc_id}", response_model=DocumentDetail)
async def get_document(
    doc_id: str,
    session: SessionDep,
) -> DocumentDetail:
    doc = await DocumentService.get_by_id(session, UUID(doc_id))
    if doc is None:
        raise DocumentNotFoundError(doc_id=doc_id)

    total, synced = await _get_chunk_stats(session, doc.document_id)
    tags = await _get_doc_tags(session, doc.document_id)

    return DocumentDetail(
        doc_id=str(doc.document_id),
        filename=_extract_filename(doc.source_path, doc.title),
        file_type=_extract_file_type(doc.source_path),
        total_chunks=total,
        synced_chunks=synced,
        tags=tags,
        created_at=doc.created_at.isoformat() if doc.created_at else "",
        weight=doc.weight,
        sync_status=doc.sync_status.value,
    )


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: FastAPIFile,
    settings: SettingsDep,
    ingestion_service: IngestionServiceDep,
    session_factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
) -> UploadResponse:
    ext = FilePath(file.filename or "").suffix.lower()
    if ext not in _SUPPORTED_EXTENSIONS:
        raise UnsupportedFileTypeError(
            file_type=ext,
            detail=f"Supported formats: {sorted(_SUPPORTED_EXTENSIONS)}",
        )

    upload_dir = FilePath(settings.upload_file_dir)
    await asyncio.to_thread(lambda: upload_dir.mkdir(parents=True, exist_ok=True))  # noqa: ASYNC240
    dest_path = upload_dir / file.filename

    try:
        await asyncio.to_thread(_write_file, dest_path, file.file)
    except Exception:
        logger.exception("Failed to save uploaded file")
        if await asyncio.to_thread(lambda: dest_path.exists()):
            await asyncio.to_thread(lambda: dest_path.unlink())
        raise

    file_size = (await asyncio.to_thread(lambda: dest_path.stat())).st_size
    if file_size > _MAX_UPLOAD_BYTES:
        await asyncio.to_thread(lambda: dest_path.unlink())
        raise IngestionError(
            message=f"File too large: {file_size / (1024 * 1024):.1f} MB (max 50 MB)",
        )

    try:
        doc = await ingestion_service.ingest_file(dest_path)
    except Exception:
        if await asyncio.to_thread(lambda: dest_path.exists()):
            await asyncio.to_thread(lambda: dest_path.unlink())
        raise

    async with session_factory() as new_session:
        total, _synced = await _get_chunk_stats(new_session, doc.document_id)

    return UploadResponse(
        doc_id=str(doc.document_id),
        filename=file.filename or "unknown",
        chunk_count=total,
        status=doc.sync_status.value,
    )


@router.delete("/{doc_id}", response_model=DeleteResponse)
async def delete_document(
    doc_id: str,
    session: SessionDep,
    qdrant: QdrantDep,
) -> DeleteResponse:
    doc = await DocumentService.get_by_id(session, UUID(doc_id))
    if doc is None:
        raise DocumentNotFoundError(doc_id=doc_id)

    await DocumentService.delete_document(session, qdrant, doc_id)
    await session.commit()

    return DeleteResponse(deleted=True, doc_id=doc_id)
