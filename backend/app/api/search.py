import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.api.dependencies import PipelineDepsDep, SessionDep
from app.config import settings
from app.core.models import Chunk, Document
from app.core.repository import ChunkRepository
from app.core.schemas import (
    ScoreDetail,
    SearchRequest,
    SearchResultItem,
)
from app.retrieval.engine import instantiate
from app.retrieval.graph import inject_normalizers, validate
from app.retrieval.pipeline import RetrievalPipeline
from app.retrieval.topology import resolve_topology

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("", response_model=list[SearchResultItem])
async def search(
    request: SearchRequest,
    deps: PipelineDepsDep,
    session: SessionDep,
) -> list[SearchResultItem] | JSONResponse:
    try:
        graph_spec = await resolve_topology(request.topology, settings.default_topology, session)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})

    try:
        validate(graph_spec)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"valid": False, "errors": [str(e)]})

    graph_spec = inject_normalizers(graph_spec)
    dag = instantiate(graph_spec, deps)
    pipeline = RetrievalPipeline(
        dag=dag,
        embedder=deps.embedder,
        session_factory=deps.session_factory,
    )

    results = await pipeline.search(
        query_text=request.query,
        top_k=request.top_k,
        retention_mode=request.mode,
    )

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
