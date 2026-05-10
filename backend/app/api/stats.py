"""Stats and tags API."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.dependencies import SessionDep
from app.core.repository import ChunkRepository, DocumentRepository
from app.core.schemas import SystemStatsResponse

router = APIRouter()


@router.get("/stats", response_model=SystemStatsResponse)
async def get_system_stats(session: SessionDep) -> SystemStatsResponse:
    """Return aggregate counts for documents, chunks, and sync status."""
    doc_count = await DocumentRepository.count_all(session)
    chunk_count = await ChunkRepository.count_all(session)
    status_counts = await ChunkRepository.count_by_status(session)
    latest_at = await DocumentRepository.get_latest_created_at(session)

    return SystemStatsResponse(
        document_count=doc_count,
        chunk_count=chunk_count,
        synced_count=status_counts.get("synced", 0),
        dirty_count=status_counts.get("dirty", 0),
        failed_count=status_counts.get("failed", 0),
        last_ingestion_at=latest_at.isoformat() if latest_at else None,
    )


@router.get("/tags")
async def get_all_tags(session: SessionDep) -> dict:
    """Return all unique tags across all chunks."""
    tags = await ChunkRepository.get_all_unique_tags(session)
    return {"tags": tags}
