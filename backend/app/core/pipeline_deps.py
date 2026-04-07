"""Shared dependency container for retrieval pipeline operators."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.vectordb import QdrantService
from app.ingestion.embedder import BaseEmbedder


@dataclass(frozen=True)
class PipelineDeps:
    """Source-agnostic shared dependency container.

    Constructed by FastAPI routes, CLI commands, or MCP server,
    then passed into operator constructors uniformly.
    """

    embedder: BaseEmbedder
    qdrant_client: QdrantService
    session_factory: async_sessionmaker[AsyncSession]
