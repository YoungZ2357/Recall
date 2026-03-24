from fastapi import APIRouter

from app.api import generate

router = APIRouter()

# P1-5/P1-6 routes will be mounted here:
# from app.api import documents, search
# router.include_router(documents.router, prefix="/documents", tags=["documents"])
# router.include_router(search.router, prefix="/search", tags=["search"])

router.include_router(generate.router, prefix="/generate", tags=["generate"])
