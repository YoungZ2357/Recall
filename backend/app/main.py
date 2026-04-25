import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import router
from app.cli._init_deps import init_deps, teardown_deps
from app.config import settings
from app.core.database import dispose_engine
from app.core.exceptions import RecallError


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logging.basicConfig(level=settings.log_level.upper())
    logger = logging.getLogger(__name__)
    logger.info("Starting Recall API server")

    session_factory, qdrant, embedder, generator = await init_deps(settings)
    app.state.session_factory = session_factory
    app.state.qdrant = qdrant
    app.state.embedder = embedder
    app.state.generator = generator

    yield

    logger.info("Shutting down Recall API server")
    await teardown_deps(qdrant, embedder, generator)
    await dispose_engine()


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
