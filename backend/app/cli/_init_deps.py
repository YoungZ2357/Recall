"""Async dependency initialization for CLI commands."""

from __future__ import annotations

import logging
from typing import NamedTuple

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.config import settings as _default_settings
from app.core.database import (
    create_context_fts_table,
    create_fts_table,
    create_tables,
    dispose_engine,
    get_session_factory,
    populate_context_fts_from_chunks,
    populate_fts_from_chunks,
)
from app.core.exceptions import ConfigError
from app.core.vectordb import QdrantService
from app.generation.generator import LLMGenerator
from app.ingestion.embedder import APIEmbedder
from app.services import GenerationService, IngestionService, ReindexService, SearchService

logger = logging.getLogger(__name__)


class AppResources(NamedTuple):
    session_factory: async_sessionmaker[AsyncSession]
    qdrant_client: QdrantService
    embedder: APIEmbedder
    generator: LLMGenerator | None
    search_service: SearchService
    generation_service: GenerationService | None
    ingestion_service: IngestionService
    reindex_service: ReindexService


async def init_deps(
    cfg: Settings | None = None,
) -> AppResources:
    """Initialize SQLite tables, Qdrant collection, embedder, and optional LLM generator.

    Args:
        cfg: Settings instance; defaults to module-level settings singleton.

    Returns:
        AppResources with populated services ready for use.
        generation_service is None when LLM_API_KEY is not configured.
    """
    cfg = cfg or _default_settings

    # 1. Ensure SQLite tables and FTS indexes exist
    await create_tables()
    await create_fts_table()
    await populate_fts_from_chunks()
    await create_context_fts_table()
    await populate_context_fts_from_chunks()
    logger.debug("SQLite tables and FTS indexes ready")

    # 2. Connect to Qdrant and ensure collection exists
    qdrant = QdrantService()
    await qdrant.connect()

    # 3. Build embedder (validates API key at construction time)
    embedder = APIEmbedder(cfg)
    await qdrant.ensure_collection(embedder.dimension)
    logger.debug("Qdrant collection ready (dimension=%d)", embedder.dimension)

    # 4. Build LLM generator (optional — skip if API key not set)
    generator: LLMGenerator | None = None
    if cfg.llm_api_key:
        try:
            generator = LLMGenerator(cfg)
            logger.debug("LLM generator ready (model=%s)", cfg.llm_model)
        except ConfigError:
            logger.warning("LLM generator disabled: llm_api_key not configured")

    session_factory = get_session_factory()

    # 5. Build services
    search_service = SearchService(
        embedder=embedder,
        qdrant_client=qdrant,
        session_factory=session_factory,
    )
    generation_service: GenerationService | None = None
    if generator is not None:
        generation_service = GenerationService(search_service, generator)

    ingestion_service = IngestionService(
        session_factory=session_factory,
        qdrant_client=qdrant,
        embedder=embedder,
        generator=generator,
        mineru_api_key=cfg.mineru_api_key,
    )

    reindex_service = ReindexService(
        session_factory=session_factory,
        qdrant_client=qdrant,
        embedder=embedder,
    )

    return AppResources(
        session_factory, qdrant, embedder, generator,
        search_service, generation_service, ingestion_service,
        reindex_service,
    )


async def teardown_deps(resources: AppResources) -> None:
    """Close Qdrant connection, HTTP clients, and SQLAlchemy engine."""
    await resources.qdrant_client.close()
    await resources.embedder.aclose()
    if resources.generator is not None:
        await resources.generator.aclose()
    await dispose_engine()
    logger.debug("Dependencies torn down")
