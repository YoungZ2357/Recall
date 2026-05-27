from fastapi import APIRouter

from app.api import documents, generate, ingest, search, settings, stats, topology

router = APIRouter()

router.include_router(generate.router, prefix="/generate", tags=["generate"])
router.include_router(documents.router, prefix="/api/documents", tags=["documents"])
router.include_router(search.router, prefix="/api/search", tags=["search"])
router.include_router(topology.router, prefix="/api/topology", tags=["topology"])
router.include_router(ingest.router, prefix="/api", tags=["ingest"])
router.include_router(stats.router, prefix="/api", tags=["stats"])
router.include_router(settings.router, prefix="/api/settings", tags=["settings"])
