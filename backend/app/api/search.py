import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.api.dependencies import SearchServiceDep, SessionDep
from app.core.models import Chunk, Document
from app.core.repository import ChunkRepository
from app.core.schemas import (
    ScoreDetail,
    SearchRequest,
    SearchResultItem,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("", response_model=list[SearchResultItem])
async def search(
    request: SearchRequest,
    search_service: SearchServiceDep,
    session: SessionDep,
) -> list[SearchResultItem] | JSONResponse:
    try:
        results = await search_service.search(
            query_text=request.query,
            top_k=request.top_k,
            retention_mode=request.mode,
            topology_spec=request.topology,
            topology_session=session,
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})

    if not results:
        return []

    chunk_ids = [r.chunk_id for r in results]
    tags_map = await ChunkRepository.get_tags_by_ids(session, chunk_ids)

    doc_id_map: dict[str, str] = {}
    doc_rows = await session.execute(
        select(Chunk.chunk_id, Chunk.document_id, Document.title, Document.source_path)
        .join(Document, Chunk.document_id == Document.document_id)
        .where(Chunk.chunk_id.in_(chunk_ids))
    )
    for row in doc_rows.all():
        cid = str(row.chunk_id)
        doc_id_map[cid] = str(row.document_id)

    items: list[SearchResultItem] = []
    for r in results:
        cid = str(r.chunk_id)
        did = doc_id_map.get(cid, "")
        doc_title = r.document_title or "untitled"
        tags = tags_map.get(cid, [])

        items.append(
            SearchResultItem(
                chunk_id=cid,
                content=r.content,
                doc_id=did,
                filename=doc_title,
                final_score=r.final_score,
                score_detail=ScoreDetail(
                    retrieval_score=r.retrieval_score,
                    metadata_score=r.metadata_score,
                    retention_score=r.retention_score,
                ),
                tags=tags,
            )
        )

    return items
