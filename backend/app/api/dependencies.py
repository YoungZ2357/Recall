from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.config import settings as _settings
from app.core.database import get_session
from app.core.exceptions import ConfigError
from app.core.vectordb import QdrantService
from app.generation.generator import LLMGenerator
from app.ingestion.chunker import RecursiveSplitStrategy
from app.ingestion.embedder import APIEmbedder
from app.ingestion.parser import get_parser
from app.ingestion.pipeline import IngestionPipeline
from app.services import GenerationService, SearchService

# --- Base resources (extracted from app.state) ---

def get_qdrant(request: Request) -> QdrantService:
    return request.app.state.qdrant


def get_embedder(request: Request) -> APIEmbedder:
    return request.app.state.embedder


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.session_factory


def get_settings() -> Settings:
    return _settings


def get_generator(request: Request) -> LLMGenerator:
    gen = request.app.state.generator
    if gen is None:
        raise ConfigError(message="LLM_API_KEY is not configured")
    return gen


# get_session from database.py is already FastAPI Depends-compatible
get_db_session = get_session


# --- Service dependencies ---

def get_search_service(
    qdrant: Annotated[QdrantService, Depends(get_qdrant)],
    embedder: Annotated[APIEmbedder, Depends(get_embedder)],
    session_factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
) -> SearchService:
    return SearchService(
        embedder=embedder,
        qdrant_client=qdrant,
        session_factory=session_factory,
    )


def get_generation_service(
    search_service: Annotated[SearchService, Depends(get_search_service)],
    generator: Annotated[LLMGenerator, Depends(get_generator)],
) -> GenerationService:
    return GenerationService(search_service, generator)


def get_ingestion_pipeline(
    qdrant: Annotated[QdrantService, Depends(get_qdrant)],
    embedder: Annotated[APIEmbedder, Depends(get_embedder)],
    session_factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
) -> IngestionPipeline:
    return IngestionPipeline(
        parser_factory=get_parser,
        chunker=RecursiveSplitStrategy(),
        embedder=embedder,
        session_factory=session_factory,
        qdrant_service=qdrant,
    )


# --- Type aliases (for concise route annotations) ---

QdrantDep = Annotated[QdrantService, Depends(get_qdrant)]
EmbedderDep = Annotated[APIEmbedder, Depends(get_embedder)]
SessionDep = Annotated[AsyncSession, Depends(get_db_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
IngestionPipelineDep = Annotated[IngestionPipeline, Depends(get_ingestion_pipeline)]
GeneratorDep = Annotated[LLMGenerator, Depends(get_generator)]
SearchServiceDep = Annotated[SearchService, Depends(get_search_service)]
GenerationServiceDep = Annotated[GenerationService, Depends(get_generation_service)]
