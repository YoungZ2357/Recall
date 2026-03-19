"""Async dependency initialization for CLI commands."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, settings as _default_settings
from app.core.database import create_tables, get_session_factory
from app.core.vectordb import QdrantService
from app.ingestion.embedder import APIEmbedder

logger = logging.getLogger(__name__)


async def init_deps(
    cfg: Settings | None = None,
) -> tuple[async_sessionmaker[AsyncSession], QdrantService, APIEmbedder]:
    """Initialize SQLite tables, Qdrant collection, and embedder.

    Args:
        cfg: Settings instance; defaults to module-level settings singleton.

    Returns:
        (session_factory, qdrant_service, embedder) tuple ready for use.
    """
    cfg = cfg or _default_settings

    # 1. Ensure SQLite tables exist
    await create_tables()
    logger.debug("SQLite tables ready")

    # 2. Connect to Qdrant and ensure collection exists
    qdrant = QdrantService()
    await qdrant.connect()

    # 3. Build embedder (validates API key at construction time)
    embedder = APIEmbedder(cfg)
    await qdrant.ensure_collection(embedder.dimension)
    logger.debug("Qdrant collection ready (dimension=%d)", embedder.dimension)

    session_factory = get_session_factory()
    return session_factory, qdrant, embedder


async def teardown_deps(qdrant: QdrantService, embedder: APIEmbedder) -> None:
    """Close Qdrant connection and HTTP client."""
    await qdrant.close()
    await embedder.aclose()
    logger.debug("CLI dependencies torn down")
