"""Async dependency initialization for CLI commands."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, settings as _default_settings
from app.core.database import (
    create_fts_table,
    create_tables,
    dispose_engine,
    get_session_factory,
    populate_fts_from_chunks,
)
from app.core.exceptions import ConfigError
from app.core.vectordb import QdrantService
from app.generation.generator import LLMGenerator
from app.ingestion.embedder import APIEmbedder

logger = logging.getLogger(__name__)


async def init_deps(
    cfg: Settings | None = None,
) -> tuple[async_sessionmaker[AsyncSession], QdrantService, APIEmbedder, LLMGenerator | None]:
    """Initialize SQLite tables, Qdrant collection, embedder, and optional LLM generator.

    Args:
        cfg: Settings instance; defaults to module-level settings singleton.

    Returns:
        (session_factory, qdrant_service, embedder, generator) tuple ready for use.
        generator is None when LLM_API_KEY is not configured.
    """
    cfg = cfg or _default_settings

    # 1. Ensure SQLite tables and FTS index exist
    await create_tables()
    await create_fts_table()
    await populate_fts_from_chunks()
    logger.debug("SQLite tables and FTS index ready")

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
    return session_factory, qdrant, embedder, generator


async def teardown_deps(
    qdrant: QdrantService,
    embedder: APIEmbedder,
    generator: LLMGenerator | None = None,
) -> None:
    """Close Qdrant connection, HTTP clients, and SQLAlchemy engine."""
    await qdrant.close()
    await embedder.aclose()
    if generator is not None:
        await generator.aclose()
    await dispose_engine()
    logger.debug("Dependencies torn down")
