"""Background ingestion task runner with per-file, per-stage progress tracking."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.schemas import IngestRequest
from app.core.vectordb import QdrantService
from app.generation.generator import LLMGenerator
from app.ingestion.contextualizer import ContextGenerator
from app.ingestion.embedder import BaseEmbedder
from app.ingestion.tagger import AutoTagger
from app.services.ingestion_service import IngestionService
from app.services.task_store import StageStatus, TaskStatus, TaskStore

logger = logging.getLogger(__name__)


async def execute_ingest_task(
    task_id: str,
    req: IngestRequest,
    file_upload_map: dict[str, Path],
    task_store: TaskStore,
    session_factory: async_sessionmaker,
    qdrant: QdrantService,
    embedder: BaseEmbedder,
    generator: LLMGenerator | None,
    mineru_api_key: str | None = None,
) -> None:
    """Run ingestion for all files in the task. Single-file failures are isolated."""
    task_store.start_task(task_id)

    for file_id, file_path in file_upload_map.items():
        await _ingest_single_file(
            task_id=task_id,
            file_id=file_id,
            file_path=file_path,
            req=req,
            task_store=task_store,
            session_factory=session_factory,
            qdrant=qdrant,
            embedder=embedder,
            generator=generator,
            mineru_api_key=mineru_api_key,
        )

    task_store.complete_task(task_id)


async def _ingest_single_file(
    task_id: str,
    file_id: str,
    file_path: Path,
    req: IngestRequest,
    task_store: TaskStore,
    session_factory: async_sessionmaker,
    qdrant: QdrantService,
    embedder: BaseEmbedder,
    generator: LLMGenerator | None,
    mineru_api_key: str | None = None,
) -> None:
    # Pre-mark stages that will be skipped
    if not req.strip_tail and not req.strip_markdown:
        task_store.update_stage(task_id, file_id, "Filtering", StageStatus.SKIPPED)
    if not req.contextualize:
        task_store.update_stage(task_id, file_id, "Contextualizing", StageStatus.SKIPPED)

    task_store.update_file_status(task_id, file_id, TaskStatus.RUNNING)

    # Track the stage currently running so we can mark it DONE when the next starts
    current_stage: list[str | None] = [None]

    def stage_cb(stage_name: str) -> None:
        # Mark previous stage done before starting next
        if current_stage[0] is not None:
            task_store.update_stage(task_id, file_id, current_stage[0], StageStatus.DONE)
        current_stage[0] = stage_name
        task_store.update_stage(task_id, file_id, stage_name, StageStatus.RUNNING)

    def chunk_count_cb(count: int) -> None:
        task_store.set_chunk_count(task_id, file_id, count)

    contextualizer: ContextGenerator | None = None
    if req.contextualize and generator is not None:
        contextualizer = ContextGenerator(generator)

    tagger: AutoTagger | None = None
    if req.auto_tag and generator is not None:
        tagger = AutoTagger(generator)

    svc = IngestionService(
        session_factory=session_factory,
        qdrant_client=qdrant,
        embedder=embedder,
        generator=generator,
        mineru_api_key=mineru_api_key,
    )

    try:
        doc = await svc.ingest_file(
            file_path,
            pdf_parser=req.pdf_parser,
            strategy=req.chunk_strategy,
            chunk_size=req.chunk_size,
            chunk_overlap=req.chunk_overlap,
            target_chunks=req.target_chunks,
            overlap_ratio=req.overlap_ratio,
            contextualize=req.contextualize,
            contextualizer=contextualizer,
            tagger=tagger,
            strip_tail=req.strip_tail,
            strip_markdown=req.strip_markdown,
            stage_callback=stage_cb,
            on_chunk_count=chunk_count_cb,
        )

        # Mark the final stage done
        if current_stage[0] is not None:
            task_store.update_stage(task_id, file_id, current_stage[0], StageStatus.DONE)

        # Collect tags from the ingested document's chunks
        async with session_factory() as session:
            from app.core.repository import ChunkRepository
            chunks = await ChunkRepository.list_by_document(session, doc.document_id)
            tag_set: set[str] = set()
            for c in chunks:
                if c.tags:
                    try:
                        parsed = json.loads(c.tags)
                        if isinstance(parsed, list):
                            tag_set.update(t for t in parsed if isinstance(t, str) and t)
                    except (json.JSONDecodeError, TypeError):
                        pass
            task_store.set_tags(task_id, file_id, sorted(tag_set))

        task_store.update_file_status(task_id, file_id, TaskStatus.DONE)

    except Exception as exc:
        logger.exception("Ingestion failed for file_id=%s path=%s", file_id, file_path)
        if current_stage[0] is not None:
            task_store.update_stage(task_id, file_id, current_stage[0], StageStatus.ERROR)
        detail = getattr(exc, "detail", None)
        error_msg = f"{exc} | {detail}" if detail else str(exc)
        task_store.update_file_status(task_id, file_id, TaskStatus.ERROR, error=error_msg)
