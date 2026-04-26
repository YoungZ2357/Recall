import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select

from app.api.dependencies import GeneratorDep, PipelineDepsDep, SessionDep, build_retrieval_pipeline
from app.config import settings
from app.core.models import Chunk, Document
from app.core.schemas import GenerateRequest, GenerateResponse, RetrievalResult, SourceInfo

logger = logging.getLogger(__name__)

router = APIRouter()


async def _build_sources(
    session,
    results: list[RetrievalResult],
) -> str:
    chunk_ids = [r.chunk_id for r in results]
    rows = await session.execute(
        select(Chunk.chunk_id, Document.source_path, Document.title)
        .join(Document, Chunk.document_id == Document.document_id)
        .where(Chunk.chunk_id.in_(chunk_ids))
    )
    source_map: dict[str, tuple[str, str]] = {}
    for row in rows.all():
        cid = str(row.chunk_id)
        filename = Path(row.source_path).name if row.source_path else (row.title or "untitled")
        source_map[cid] = (str(row.chunk_id), filename)

    sources = [
        SourceInfo(
            doc_id=source_map.get(str(r.chunk_id), ("", ""))[0],
            filename=source_map.get(str(r.chunk_id), ("", "untitled"))[1],
            chunk_id=str(r.chunk_id),
        )
        for r in results
    ]
    return json.dumps({"sources": [s.model_dump() for s in sources]})


async def _stream_with_sources(
    stream: AsyncIterator[str],
    sources_json: str,
) -> AsyncIterator[str]:
    async for chunk in stream:
        if chunk.startswith("data: [DONE]"):
            yield f"data: {sources_json}\n\n"
            yield "data: [DONE]\n\n"
            return
        yield chunk
    yield f"data: {sources_json}\n\n"
    yield "data: [DONE]\n\n"


@router.post("", response_model=GenerateResponse)
async def generate(
    request: GenerateRequest,
    generator: GeneratorDep,
    deps: PipelineDepsDep,
    session: SessionDep,
) -> GenerateResponse | StreamingResponse | JSONResponse:
    try:
        pipeline = await build_retrieval_pipeline(
            request.topology, deps, session, settings.default_topology,
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content={"detail": str(e)})

    results = await pipeline.search(
        query_text=request.query,
        top_k=request.top_k,
        retention_mode=request.mode,
    )

    if request.stream:
        sources_json = await _build_sources(session, results)
        return StreamingResponse(
            _stream_with_sources(
                generator.generate_stream(
                    query=request.query,
                    context=results,
                ),
                sources_json,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return await generator.generate(
        query=request.query,
        context=results,
    )
