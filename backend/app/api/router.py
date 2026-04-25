from fastapi import APIRouter

from app.api import documents, generate, search, topology

router = APIRouter()

router.include_router(generate.router, prefix="/generate", tags=["generate"])
router.include_router(documents.router, prefix="/api/documents", tags=["documents"])
router.include_router(search.router, prefix="/api/search", tags=["search"])
router.include_router(topology.router, prefix="/api/topology", tags=["topology"])
