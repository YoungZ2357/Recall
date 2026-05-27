import asyncio
import json
import logging
import shutil
from pathlib import Path as FilePath
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.dependencies import (
    EmbedderDep,
    GeneratorDep,
    IngestionServiceDep,
    QdrantDep,
    ReindexServiceDep,
    SessionDep,
    SettingsDep,
    get_session_factory,
)
from app.core.chunk_manager import ChunkManager
from app.core.exceptions import (
    ConfigError,
    DocumentNotFoundError,
    IngestionError,
    UnsupportedFileTypeError,
)
from app.core.models import Chunk, SyncStatus
from app.core.repository import ChunkRepository, DocumentRepository
from app.core.schemas import (
    ChunkDetail,
    DeleteResponse,
    DocumentDetail,
    DocumentSummary,
    RetagRequest,
    UploadResponse,
    WeightUpdate,
)
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
    # Prefer the stored title (display_name or content-extracted) over source_path.name,
    # which may contain a UUID-prefixed temp filename from the upload pipeline.
    return title or (FilePath(source_path).name if source_path else None) or "untitled"


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
                sync_status=str(doc.sync_status),
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
        sync_status=str(doc.sync_status),
    )


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile,
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
        status=str(doc.sync_status),
    )


@router.get("/{doc_id}/chunks", response_model=list[ChunkDetail])
async def list_document_chunks(
    doc_id: str,
    session: SessionDep,
) -> list[ChunkDetail]:
    doc = await DocumentService.get_by_id(session, UUID(doc_id))
    if doc is None:
        raise DocumentNotFoundError(doc_id=doc_id)

    chunks = await ChunkRepository.list_by_document(session, UUID(doc_id))
    result: list[ChunkDetail] = []
    for c in sorted(chunks, key=lambda x: x.chunk_index):
        try:
            tags = json.loads(c.tags) if c.tags else []
        except (json.JSONDecodeError, TypeError):
            tags = []
        result.append(
            ChunkDetail(
                chunk_id=str(c.chunk_id),
                chunk_index=c.chunk_index,
                content=c.content,
                context=c.context,
                tags=tags,
                sync_status=str(c.sync_status),
            )
        )
    return result


@router.patch("/{doc_id}/weight", response_model=DocumentSummary)
async def update_document_weight(
    doc_id: str,
    body: WeightUpdate,
    session: SessionDep,
) -> DocumentSummary:
    doc = await DocumentService.get_by_id(session, UUID(doc_id))
    if doc is None:
        raise DocumentNotFoundError(doc_id=doc_id)

    doc.weight = body.weight
    await session.commit()
    await session.refresh(doc)

    total, _synced = await _get_chunk_stats(session, doc.document_id)
    return DocumentSummary(
        doc_id=str(doc.document_id),
        filename=_extract_filename(doc.source_path, doc.title),
        file_type=_extract_file_type(doc.source_path),
        chunk_count=total,
        created_at=doc.created_at.isoformat() if doc.created_at else "",
        weight=doc.weight,
        sync_status=str(doc.sync_status),
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


# ============================================================
# Post-op endpoints
# ============================================================


@router.post("/{doc_id}/reindex")
async def reindex_document(
    doc_id: str,
    reindex_service: ReindexServiceDep,
) -> dict:
    """Re-embed all chunks of a document and sync to Qdrant."""
    result = await reindex_service.reindex_document(doc_id)
    return {
        "doc_id": doc_id,
        "status": "reindexed",
        "total": result.total,
        "succeeded": result.succeeded,
        "failed": result.failed,
    }


@router.post("/{doc_id}/retag")
async def retag_document(
    doc_id: str,
    req: RetagRequest,
    session: SessionDep,
    qdrant: QdrantDep,
    request: Request,
) -> dict:
    """Update tags on all chunks of a document.

    tags=null: auto-regenerate via LLM (requires LLM_API_KEY).
    tags=[...]: set the provided tags directly.
    """
    doc = await DocumentService.get_by_id(session, UUID(doc_id))
    if doc is None:
        raise DocumentNotFoundError(doc_id=doc_id)

    if req.tags is not None:
        tags = req.tags
    else:
        generator = request.app.state.generator
        if generator is None:
            raise ConfigError(message="LLM_API_KEY is not configured")

        chunks = await ChunkRepository.list_by_document(session, UUID(doc_id))
        doc_text = "\n\n".join(c.content for c in sorted(chunks, key=lambda c: c.chunk_index))

        from app.ingestion.tagger import AutoTagger
        tagger = AutoTagger(generator)
        tags = await tagger.tag(doc_text, session)

    updated = await ChunkManager.retag_document(session, qdrant, doc_id, tags)
    await session.commit()
    return {"doc_id": doc_id, "updated_chunks": updated, "tags": tags}


@router.post("/{doc_id}/contextualize")
async def contextualize_document(
    doc_id: str,
    session: SessionDep,
    qdrant: QdrantDep,
    embedder: EmbedderDep,
    generator: GeneratorDep,
) -> dict:
    """Generate context for all chunks of a document and re-embed them."""
    doc = await DocumentService.get_by_id(session, UUID(doc_id))
    if doc is None:
        raise DocumentNotFoundError(doc_id=doc_id)

    chunks = await ChunkRepository.list_by_document(session, UUID(doc_id))
    if not chunks:
        return {"doc_id": doc_id, "contextualized": 0}

    sorted_chunks = sorted(chunks, key=lambda c: c.chunk_index)
    doc_text = "\n\n".join(c.content for c in sorted_chunks)

    from app.ingestion.contextualizer import ContextGenerator
    ctx_gen = ContextGenerator(generator)
    contexts = await ctx_gen.generate_batch(doc_text, [c.content for c in sorted_chunks])

    chunk_updates = []
    for chunk, context in zip(sorted_chunks, contexts, strict=False):
        if context is None:
            continue
        try:
            tags = json.loads(chunk.tags) if chunk.tags else []
        except (json.JSONDecodeError, TypeError):
            tags = []
        chunk_updates.append({
            "chunk_id": chunk.chunk_id,
            "content": chunk.content,
            "chunk_index": chunk.chunk_index,
            "tags": tags,
            "context": context,
        })

    if not chunk_updates:
        return {"doc_id": doc_id, "contextualized": 0}

    count = await ChunkManager.contextualize_chunks(
        session, qdrant, embedder, doc_id, chunk_updates
    )
    return {"doc_id": doc_id, "contextualized": count}


@router.get("/{doc_id}/health")
async def health_check_document(
    doc_id: str,
    session: SessionDep,
    qdrant: QdrantDep,
) -> dict:
    """Verify SQLite ↔ Qdrant consistency for a document (raises 409 on mismatch)."""
    doc = await DocumentService.get_by_id(session, UUID(doc_id))
    if doc is None:
        raise DocumentNotFoundError(doc_id=doc_id)

    await ChunkManager.health_check(session, qdrant, doc_id, level="full")
    return {"doc_id": doc_id, "status": "ok"}


@router.post("/health-check")
async def health_check_all(
    session: SessionDep,
    qdrant: QdrantDep,
) -> dict:
    """Run health check on all documents and auto-mark inconsistent ones as dirty."""
    docs = await DocumentRepository.list_all(session)
    issues: list[dict] = []

    for doc in docs:
        doc_id = str(doc.document_id)
        try:
            await ChunkManager.health_check_with_auto_dirty(session, qdrant, doc_id, level="full")
        except Exception as exc:
            issues.append({"doc_id": doc_id, "error": str(exc)})
            await session.rollback()

    return {"checked": len(docs), "issues": issues}
