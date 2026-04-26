"""
Ingestion pipeline: orchestrates parser → chunker → embedder → chunk_manager
for a single atomic ingest operation.

Usage:
    pipeline = IngestionPipeline(
        parser_factory=get_parser,
        chunker=RecursiveSplitStrategy(),
        embedder=APIEmbedder(settings),
        session_factory=async_session_factory,
        qdrant_service=qdrant_svc,
    )
    doc = await pipeline.ingest(Path("notes.txt"))
    result = await pipeline.ingest_batch([Path("a.txt"), Path("b.md")])
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.chunk_manager import ChunkManager
from app.core.exceptions import EmbeddingError, IngestionError, SyncError
from app.core.models import Document
from app.core.repository import DocumentRepository
from app.core.schemas import ChunkIngest, DocumentCreate
from app.core.vectordb import QdrantService
from app.ingestion.chunker import BaseChunker
from app.ingestion.content_filter import (
    ContentFilterResult,
    content_filter,
    strip_markdown_sections,
)
from app.ingestion.contextualizer import ContextGenerator
from app.ingestion.embedder import BaseEmbedder
from app.ingestion.parser import BaseParser
from app.ingestion.tagger import AutoTagger

logger = logging.getLogger(__name__)


# ============================================================
# Result types
# ============================================================

@dataclass
class FailedIngest:
    file_path: Path
    error: str


@dataclass
class BatchIngestResult:
    succeeded: list[Document] = field(default_factory=list)
    failed: list[FailedIngest] = field(default_factory=list)


# ============================================================
# Pipeline
# ============================================================

class IngestionPipeline:
    """Single-document and batch ingestion orchestrator.

    Note: session_factory and qdrant_service are required because ChunkManager
    uses classmethods that require these dependencies to be passed explicitly.
    """

    def __init__(
        self,
        parser_factory: Callable[[Path], BaseParser],
        chunker: BaseChunker,
        embedder: BaseEmbedder,
        session_factory: async_sessionmaker[AsyncSession],
        qdrant_service: QdrantService,
        tagger: AutoTagger | None = None,
        contextualizer: ContextGenerator | None = None,
        strip_tail: bool = False,
        strip_markdown: bool = False,
    ) -> None:
        self._parser_factory = parser_factory
        self._chunker = chunker
        self._embedder = embedder
        self._session_factory = session_factory
        self._qdrant_service = qdrant_service
        self._tagger = tagger
        self._contextualizer = contextualizer
        self._strip_tail = strip_tail
        self._strip_markdown = strip_markdown
        self.last_filter_result: ContentFilterResult | None = None

    async def ingest(
        self,
        file_path: Path,
        stage_callback: Callable[[str], None] | None = None,
        on_chunk_count: Callable[[int], None] | None = None,
    ) -> Document:
        """Ingest a single file end-to-end: parse → chunk → embed → dual-write.

        Args:
            file_path: Absolute or relative path to the file.
            stage_callback: Optional callable invoked before each pipeline stage
                with the stage name (e.g. "Parsing", "Chunking"). Useful for
                driving CLI progress indicators without importing UI libraries here.

        Returns:
            The created Document ORM object (sync_status=SYNCED on success).

        Raises:
            FileNotFoundError: File does not exist.
            IngestionError: No chunks produced after splitting.
            EmbeddingError: Embedding API failed or vector count mismatch.
            SyncError: Qdrant upsert failed; document persisted with FAILED status.
        """
        file_path = file_path.resolve()  # noqa: ASYNC240
        if not file_path.is_file():  # noqa: ASYNC240
            raise FileNotFoundError(f"File not found: {file_path}")

        # Compute SHA-256 file hash for dedup
        file_hash = _sha256(file_path)

        # Step 1: Parse (sync method → run in thread)
        if stage_callback is not None:
            stage_callback("Parsing")
        parser = self._parser_factory(file_path)
        parse_result = await asyncio.to_thread(parser.parse, file_path)
        logger.debug("Parsed %s (%d chars)", file_path.name, len(parse_result.content))

        # Step 2 (optional): Filter references / appendix sections
        self.last_filter_result = None
        if self._strip_markdown:
            if stage_callback is not None:
                stage_callback("Filtering")
            self.last_filter_result = strip_markdown_sections(parse_result.content)
            if self.last_filter_result.cut_point is not None:
                parse_result.content = self.last_filter_result.filtered_text
        elif self._strip_tail:
            if stage_callback is not None:
                stage_callback("Filtering")
            self.last_filter_result = content_filter(parse_result.content)
            if self.last_filter_result.cut_point is not None:
                parse_result.content = self.last_filter_result.filtered_text

        # Step 3: Chunk
        if stage_callback is not None:
            stage_callback("Chunking")
        chunks = self._chunker.split(parse_result.content, parse_result.metadata)
        if not chunks:
            raise IngestionError(
                message=f"No chunks produced from file: {file_path.name}",
                detail="File may be empty or contain only whitespace.",
            )
        logger.debug("Split into %d chunks", len(chunks))
        if on_chunk_count is not None:
            on_chunk_count(len(chunks))

        # Step 4: Contextualize (optional — generate document-level context per chunk)
        contexts: list[str | None] = [None] * len(chunks)
        if self._contextualizer is not None:
            if stage_callback is not None:
                stage_callback("Contextualizing")
            contexts = await self._contextualizer.generate_batch(
                parse_result.content, [c.content for c in chunks]
            )
            ctx_count = sum(1 for c in contexts if c is not None)
            logger.debug("Generated context for %d/%d chunks", ctx_count, len(chunks))

        # Step 5: Embed — use context + content when context is available
        if stage_callback is not None:
            stage_callback("Embedding")
        embed_texts = [
            ctx + "\n\n" + c.content if ctx else c.content
            for ctx, c in zip(contexts, chunks, strict=False)
        ]
        embeddings = await self._embedder.embed_batch(embed_texts)
        if len(embeddings) != len(chunks):
            raise EmbeddingError(
                message="Embedding count mismatch",
                detail=f"Expected {len(chunks)} vectors, got {len(embeddings)}",
            )
        logger.debug("Embedded %d chunks", len(embeddings))

        # Step 6: Tag + Dual-write (SQLite + Qdrant) within a single session
        if stage_callback is not None:
            stage_callback("Writing")
        async with self._session_factory() as session:
            # Auto-tag: query existing tags and call LLM before writing
            tags: list[str] = []
            if self._tagger is not None:
                tags = await self._tagger.tag(parse_result.content, session)
                if tags:
                    logger.debug("Auto-tagged with %d tags: %s", len(tags), tags)

            title = parse_result.metadata.get("title") or file_path.name
            doc = await DocumentRepository.create(
                session,
                DocumentCreate(
                    title=title,
                    source_path=str(file_path),
                    file_hash=file_hash,
                ),
            )

            chunk_ingests = [
                ChunkIngest(
                    document_id=doc.document_id,
                    chunk_index=cd.chunk_index,
                    content=cd.content,
                    vector=embeddings[i],
                    tags=tags,
                    context=contexts[i],
                    context_embedded=contexts[i] is not None,
                )
                for i, cd in enumerate(chunks)
            ]

            try:
                await ChunkManager.write_chunks(
                    session,
                    self._qdrant_service,
                    str(doc.document_id),
                    chunk_ingests,
                )
                await session.commit()
            except SyncError:
                # Persist FAILED status set by write_chunks before re-raising
                await session.commit()
                raise
            except Exception:
                await session.rollback()
                raise

        logger.info(
            "Ingested %s → doc_id=%s, chunks=%d",
            file_path.name,
            doc.document_id,
            len(chunks),
        )
        return doc

    async def ingest_batch(
        self,
        file_paths: list[Path],
        concurrency: int = 1,
    ) -> BatchIngestResult:
        """Ingest multiple files. Failures are collected, not raised.

        Args:
            file_paths: List of file paths to ingest.
            concurrency: Max number of documents processed simultaneously.
                1 (default) preserves the original sequential behaviour.

        Returns:
            BatchIngestResult with succeeded Documents and FailedIngest entries.
        """
        if concurrency <= 1:
            result = BatchIngestResult()
            for path in file_paths:
                try:
                    doc = await self.ingest(path)
                    result.succeeded.append(doc)
                except Exception as exc:
                    logger.warning("Failed to ingest %s: %s", path, exc)
                    result.failed.append(FailedIngest(file_path=path, error=str(exc)))
            return result

        semaphore = asyncio.Semaphore(concurrency)

        async def _ingest_one(path: Path) -> Document | FailedIngest:
            async with semaphore:
                try:
                    return await self.ingest(path)
                except Exception as exc:
                    logger.warning("Failed to ingest %s: %s", path, exc)
                    return FailedIngest(file_path=path, error=str(exc))

        outcomes = await asyncio.gather(*[_ingest_one(p) for p in file_paths])
        result = BatchIngestResult()
        for outcome in outcomes:
            if isinstance(outcome, Document):
                result.succeeded.append(outcome)
            else:
                result.failed.append(outcome)  # type: ignore[arg-type]
        return result


# ============================================================
# Helper
# ============================================================

def _sha256(file_path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with file_path.open("rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()
