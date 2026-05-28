"""Eval API: graded test-set generation, retrieval evaluation, and CRUD."""

from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

from fastapi import APIRouter, Query

from app.api.dependencies import (
    EvalTaskStoreDep,
    EvaluationServiceDep,
    SettingsDep,
)
from app.core.eval_schemas import (
    EvalTaskIdResponse,
    EvalTaskStatusResponse,
    GenerateProgressResponse,
    GenerateTestSetRequest,
    ReportResponse,
    ReportSummaryResponse,
    RunEvalRequest,
    RunProgressResponse,
    TestSetPreviewResponse,
    TestSetSummaryResponse,
)
from app.core.exceptions import (
    ConfigError,
    EvalTaskNotFoundError,
    TestSetAlreadyExistsError,
)
from app.services.eval_task_runner import execute_eval_run_task, execute_generate_task
from app.services.eval_task_store import (
    EvalTaskKind,
    GenerateProgress,
    RunProgress,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================
# Generate test set
# ============================================================


@router.post("/test-sets/generate", response_model=EvalTaskIdResponse)
async def start_generate_task(
    req: GenerateTestSetRequest,
    eval_service: EvaluationServiceDep,
    task_store: EvalTaskStoreDep,
    settings: SettingsDep,
) -> EvalTaskIdResponse:
    """Kick off an async test-set generation task.

    Returns immediately with a task_id. Poll GET /api/eval/tasks/{task_id} for
    stage and progress; final result_path is set on completion.
    """
    # Eager checks so the client gets a synchronous 4xx instead of a "task that
    # immediately fails" — same pattern as /api/ingest's pre-flight validation.
    path = eval_service._resolve_test_set_path(req.name, must_exist=False)
    if path.exists():
        raise TestSetAlreadyExistsError(name=req.name)
    if eval_service._generator is None:  # noqa: SLF001
        raise ConfigError(message="LLM_API_KEY is not configured")

    task_id = str(uuid4())
    task_store.create_task(task_id, EvalTaskKind.GENERATE, req.name)

    asyncio.create_task(
        execute_generate_task(
            task_id=task_id,
            params=req,
            eval_service=eval_service,
            task_store=task_store,
            llm_model_name=settings.llm_model,
        )
    )
    return EvalTaskIdResponse(task_id=task_id)


# ============================================================
# Run evaluation
# ============================================================


@router.post("/run", response_model=EvalTaskIdResponse)
async def start_run_task(
    req: RunEvalRequest,
    eval_service: EvaluationServiceDep,
    task_store: EvalTaskStoreDep,
) -> EvalTaskIdResponse:
    """Kick off an async evaluation task against an existing test set."""
    # Verify the test set exists synchronously so a missing name returns 404 now.
    eval_service._resolve_test_set_path(req.test_set_name, must_exist=True)

    task_id = str(uuid4())
    task_name = req.report_name or req.test_set_name
    task_store.create_task(task_id, EvalTaskKind.RUN, task_name)

    asyncio.create_task(
        execute_eval_run_task(
            task_id=task_id,
            request=req,
            eval_service=eval_service,
            task_store=task_store,
        )
    )
    return EvalTaskIdResponse(task_id=task_id)


# ============================================================
# Task status
# ============================================================


@router.get("/tasks/{task_id}", response_model=EvalTaskStatusResponse)
async def get_task_status(
    task_id: str,
    task_store: EvalTaskStoreDep,
) -> EvalTaskStatusResponse:
    """Return current state of an evaluation task (generate or run)."""
    task = task_store.get_task(task_id)
    if task is None:
        raise EvalTaskNotFoundError(task_id=task_id)

    if isinstance(task.progress, GenerateProgress):
        progress_resp: GenerateProgressResponse | RunProgressResponse = (
            GenerateProgressResponse(
                stage=task.progress.stage,
                current=task.progress.current,
                total=task.progress.total,
            )
        )
    elif isinstance(task.progress, RunProgress):
        progress_resp = RunProgressResponse(
            current_query=task.progress.current_query,
            total_queries=task.progress.total_queries,
        )
    else:  # pragma: no cover — defensive
        raise EvalTaskNotFoundError(task_id=task_id)

    return EvalTaskStatusResponse(
        task_id=task.task_id,
        kind=task.kind.value,
        name=task.name,
        status=task.status.value,
        progress=progress_resp,
        summary=task.summary,
        result_path=task.result_path,
        error=task.error,
        started_at=task.started_at.isoformat() if task.started_at else None,
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
    )


# ============================================================
# Test sets CRUD
# ============================================================


@router.get("/test-sets", response_model=list[TestSetSummaryResponse])
async def list_test_sets(
    eval_service: EvaluationServiceDep,
) -> list[TestSetSummaryResponse]:
    return eval_service.list_test_sets()


@router.get("/test-sets/{name}", response_model=TestSetPreviewResponse)
async def get_test_set(
    name: str,
    eval_service: EvaluationServiceDep,
    preview: int = Query(default=5, ge=0, le=100),
) -> TestSetPreviewResponse:
    summary = eval_service.load_test_set_summary(name)
    entries = eval_service.load_test_set(name, preview=preview)
    return TestSetPreviewResponse(
        name=summary.name,
        entry_count=summary.entry_count,
        created_at=summary.created_at,
        size_bytes=summary.size_bytes,
        entries=entries,
    )


@router.delete("/test-sets/{name}", status_code=204)
async def delete_test_set(
    name: str,
    eval_service: EvaluationServiceDep,
) -> None:
    eval_service.delete_test_set(name)


# ============================================================
# Reports CRUD
# ============================================================


@router.get("/reports", response_model=list[ReportSummaryResponse])
async def list_reports(
    eval_service: EvaluationServiceDep,
) -> list[ReportSummaryResponse]:
    return eval_service.list_reports()


@router.get("/reports/{name}", response_model=ReportResponse)
async def get_report(
    name: str,
    eval_service: EvaluationServiceDep,
) -> ReportResponse:
    return eval_service.load_report(name)


@router.delete("/reports/{name}", status_code=204)
async def delete_report(
    name: str,
    eval_service: EvaluationServiceDep,
) -> None:
    eval_service.delete_report(name)
