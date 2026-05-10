"""Ingest API: temporary file upload and async ingestion task management."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from app.api.dependencies import TaskStoreDep
from app.config import settings
from app.core.exceptions import RecallError
from app.core.schemas import (
    FileTaskProgressResponse,
    IngestRequest,
    IngestResponse,
    StageProgressResponse,
    TaskStatusResponse,
    TempFileInfo,
    TempUploadResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md"}
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB

# Temp upload directory: backend/tmp/uploads/
_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
_UPLOAD_TMP_DIR = _BACKEND_ROOT / "tmp" / "uploads"


# ============================================================
# Upload
# ============================================================


@router.post("/upload", response_model=TempUploadResponse)
async def upload_files(
    request: Request,
    files: list[UploadFile],
) -> TempUploadResponse:
    """Store files to a temp directory and return file metadata.

    Does not trigger ingestion. Call POST /api/ingest with the returned
    file_ids to start asynchronous ingestion.
    """
    await asyncio.to_thread(lambda: _UPLOAD_TMP_DIR.mkdir(parents=True, exist_ok=True))  # noqa: ASYNC240

    upload_store: dict[str, str] = request.app.state.upload_store
    result: list[TempFileInfo] = []

    for file in files:
        filename = file.filename or "upload"
        ext = Path(filename).suffix.lower()

        if ext not in _ALLOWED_EXTENSIONS:
            return JSONResponse(
                status_code=422,
                content={
                    "error": "UnsupportedFileTypeError",
                    "message": (
                        f"File '{filename}': unsupported type '{ext}'."
                        f" Allowed: {sorted(_ALLOWED_EXTENSIONS)}"
                    ),
                },
            )

        file_id = str(uuid4())
        dest = _UPLOAD_TMP_DIR / f"{file_id}_{filename}"

        try:
            content = await file.read()
        except Exception:
            logger.exception("Failed to read uploaded file: %s", filename)
            return JSONResponse(
                status_code=500,
                content={"error": "ReadError", "message": "Failed to read file"},
            )

        if len(content) > _MAX_UPLOAD_BYTES:
            size_mb = len(content) / (1024 * 1024)
            return JSONResponse(
                status_code=422,
                content={
                    "error": "FileTooLargeError",
                    "message": f"File '{filename}' is {size_mb:.1f} MB (max 50 MB)",
                },
            )

        file_hash = hashlib.sha256(content).hexdigest()

        await asyncio.to_thread(dest.write_bytes, content)  # noqa: ASYNC240
        upload_store[file_id] = str(dest)

        result.append(
            TempFileInfo(
                file_id=file_id,
                filename=filename,
                size=len(content),
                file_hash=file_hash,
            )
        )

    return TempUploadResponse(files=result)


# ============================================================
# Start ingest task
# ============================================================


@router.post("/ingest", response_model=IngestResponse)
async def start_ingest(
    request: Request,
    req: IngestRequest,
    task_store: TaskStoreDep,
) -> IngestResponse:
    """Start an async ingestion task for previously uploaded files.

    Returns immediately with a task_id. Poll GET /api/ingest/{task_id}
    to track per-file, per-stage progress.
    """
    upload_store: dict[str, str] = request.app.state.upload_store

    file_upload_map: dict[str, Path] = {}
    file_infos: list[dict[str, str]] = []

    for fid in req.file_ids:
        if fid not in upload_store:
            return JSONResponse(
                status_code=404,
                content={"error": "FileNotFoundError", "message": f"File not found: {fid}"},
            )
        temp_path = Path(upload_store[fid])
        if not temp_path.exists():  # noqa: ASYNC240
            return JSONResponse(
                status_code=410,
                content={"error": "FileExpiredError", "message": f"Temp file expired: {fid}"},
            )
        file_upload_map[fid] = temp_path
        # Reconstruct original filename by stripping the leading uuid4_ prefix
        parts = temp_path.name.split("_", 1)
        filename = parts[1] if len(parts) > 1 else temp_path.name
        file_infos.append({"file_id": fid, "filename": filename})

    task_id = str(uuid4())
    task_store.create_task(task_id, file_infos)

    from app.services.ingest_task_runner import execute_ingest_task

    asyncio.create_task(
        execute_ingest_task(
            task_id=task_id,
            req=req,
            file_upload_map=file_upload_map,
            task_store=task_store,
            session_factory=request.app.state.session_factory,
            qdrant=request.app.state.qdrant,
            embedder=request.app.state.embedder,
            generator=request.app.state.generator,
            mineru_api_key=settings.mineru_api_key,
        )
    )

    return IngestResponse(task_id=task_id)


# ============================================================
# Task status
# ============================================================


@router.get("/ingest/{task_id}", response_model=TaskStatusResponse)
async def get_ingest_task(
    task_id: str,
    task_store: TaskStoreDep,
) -> TaskStatusResponse:
    """Return current status and per-stage progress for an ingestion task."""
    task = task_store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")

    files = [
        FileTaskProgressResponse(
            file_id=fp.file_id,
            filename=fp.filename,
            status=fp.status.value,
            stages=[
                StageProgressResponse(
                    stage=sp.stage,
                    status=sp.status.value,
                    detail=sp.detail,
                    current=sp.current,
                    total=sp.total,
                )
                for sp in fp.stages
            ],
            error=fp.error,
            chunk_count=fp.chunk_count,
            tags=fp.tags,
        )
        for fp in task.files
    ]

    return TaskStatusResponse(
        task_id=task.task_id,
        status=task.status.value,
        files=files,
        started_at=task.started_at.isoformat() if task.started_at else None,
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
    )
