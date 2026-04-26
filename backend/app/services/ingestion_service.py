"""IngestionService — encapsulates IngestionPipeline construction and ingest calls."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.models import Document
from app.core.vectordb import QdrantService
from app.generation.generator import LLMGenerator
from app.ingestion.chunker import BaseChunker, get_chunker
from app.ingestion.content_filter import ContentFilterResult
from app.ingestion.contextualizer import ContextGenerator
from app.ingestion.embedder import BaseEmbedder
from app.ingestion.parser import BaseParser, get_parser
from app.ingestion.pipeline import IngestionPipeline
from app.ingestion.tagger import AutoTagger

logger = logging.getLogger(__name__)


class IngestionService:
    """Service that owns IngestionPipeline construction for callers.

    Constructor takes individual dependencies and assembles them into
    an `IngestionPipeline` internally per ingest call.

    Usage::

        svc = IngestionService(
            session_factory=...,
            qdrant_client=...,
            embedder=...,
            generator=...,
        )
        doc = await svc.ingest_file(Path("notes.txt"))
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        qdrant_client: QdrantService,
        embedder: BaseEmbedder,
        generator: LLMGenerator | None = None,
        *,
        mineru_api_key: str | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._qdrant_client = qdrant_client
        self._embedder = embedder
        self._generator = generator
        self._mineru_api_key = mineru_api_key
        self.last_filter_result: ContentFilterResult | None = None

    def _resolve_parser_factory(
        self, pdf_parser: str,
    ) -> Callable[[Path], BaseParser]:
        if pdf_parser == "marker":
            from app.ingestion.parsers.pdf import MarkerCliParser

            def factory(p: Path) -> BaseParser:
                return MarkerCliParser() if p.suffix.lower() == ".pdf" else get_parser(p)

            return factory

        if pdf_parser == "mineru":
            from app.ingestion.parsers.pdf_mineru import MinerUParser

            api_key = self._mineru_api_key

            def factory(p: Path) -> BaseParser:
                return (
                    MinerUParser(api_key=api_key)
                    if p.suffix.lower() == ".pdf"
                    else get_parser(p)
                )

            return factory

        return get_parser

    def _resolve_chunker(
        self,
        strategy: str,
        chunk_size: int,
        chunk_overlap: int,
    ) -> BaseChunker:
        kwargs: dict = {}
        if strategy == "recursive":
            kwargs = {"chunk_size": chunk_size, "chunk_overlap": chunk_overlap}
        return get_chunker(strategy, **kwargs)

    async def ingest_file(
        self,
        file_path: Path,
        *,
        pdf_parser: str = "pymupdf",
        strategy: str = "recursive",
        chunk_size: int = 512,
        chunk_overlap: int = 64,
        contextualize: bool = False,
        contextualizer: ContextGenerator | None = None,
        tagger: AutoTagger | None = None,
        strip_tail: bool = False,
        strip_markdown: bool = False,
        stage_callback: Callable[[str], None] | None = None,
        on_chunk_count: Callable[[int], None] | None = None,
    ) -> Document:
        """Ingest a single file end-to-end through the ingestion pipeline.

        Returns:
            The created Document ORM object.
        """
        parser_factory = self._resolve_parser_factory(pdf_parser)
        chunker = self._resolve_chunker(strategy, chunk_size, chunk_overlap)

        pipeline = IngestionPipeline(
            parser_factory=parser_factory,
            chunker=chunker,
            embedder=self._embedder,
            session_factory=self._session_factory,
            qdrant_service=self._qdrant_client,
            tagger=tagger,
            contextualizer=contextualizer if contextualize else None,
            strip_tail=strip_tail,
            strip_markdown=strip_markdown,
        )

        doc = await pipeline.ingest(
            file_path,
            stage_callback=stage_callback,
            on_chunk_count=on_chunk_count,
        )

        self.last_filter_result = pipeline.last_filter_result
        return doc
