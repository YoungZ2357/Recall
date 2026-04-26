import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import router
from app.cli._init_deps import init_deps, teardown_deps
from app.config import settings
from app.core.exceptions import RecallError


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logging.basicConfig(level=settings.log_level.upper())
    logger = logging.getLogger(__name__)
    logger.info("Starting Recall API server")

    resources = await init_deps(settings)
    app.state.session_factory = resources.session_factory
    app.state.qdrant = resources.qdrant_client
    app.state.embedder = resources.embedder
    app.state.generator = resources.generator
    app.state.ingestion_service = resources.ingestion_service
    app.state.reindex_service = resources.reindex_service

    # Seed builtin topology configs
    async with resources.session_factory() as session:
        from sqlalchemy import select

        from app.core.models import TopologyConfig
        from app.retrieval.workflows import builtin_topology_seeds

        seeds = builtin_topology_seeds()
        for seed in seeds:
            result = await session.execute(
                select(TopologyConfig).where(TopologyConfig.name == seed["name"])
            )
            if result.scalar_one_or_none() is None:
                session.add(TopologyConfig(**seed))
        await session.commit()
    logger.info("Topology seeds ensured")

    yield

    logger.info("Shutting down Recall API server")
    await teardown_deps(resources)


def create_app() -> FastAPI:
    app = FastAPI(title="Recall API", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(RecallError)
    async def recall_error_handler(request: Request, exc: RecallError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.__class__.__name__,
                "message": exc.message,
                "status_code": exc.status_code,
            },
        )

    app.include_router(router)
    return app


app = create_app()
