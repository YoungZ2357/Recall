"""Background runners for evaluation tasks (generate / run).

Mirrors ingest_task_runner.py: each runner wraps an EvaluationService call
in try/except/finally, writes progress to EvalTaskStore via closures, and
guarantees the task ends in DONE or ERROR (never stuck RUNNING).
"""

from __future__ import annotations

import logging

from app.core.eval_schemas import GenerateTestSetRequest, RunEvalRequest
from app.core.exceptions import RecallError
from app.services.eval_task_store import (
    EvalTaskStore,
    GenerateStage,
)
from app.services.evaluation_service import EvaluationService
from app.services.task_store import TaskStatus

logger = logging.getLogger(__name__)


async def execute_generate_task(
    task_id: str,
    params: GenerateTestSetRequest,
    eval_service: EvaluationService,
    task_store: EvalTaskStore,
    llm_model_name: str = "",
) -> None:
    """Run a test-set generation task end-to-end with progress reporting."""
    task_store.start_task(task_id)

    def stage_cb(stage: GenerateStage, current: int, total: int) -> None:
        task_store.update_generate_progress(
            task_id, stage=stage, current=current, total=total,
        )

    try:
        path, entry_count = await eval_service.generate_test_set(
            params, llm_model_name=llm_model_name, stage_cb=stage_cb,
        )
        task_store.complete_task(
            task_id,
            summary={"entry_count": entry_count, "name": params.name},
            result_path=str(path),
        )
    except RecallError as exc:
        logger.exception("Generate task failed: task_id=%s name=%s", task_id, params.name)
        detail = getattr(exc, "detail", None)
        error_msg = f"{exc.message} | {detail}" if detail else exc.message
        task_store.fail_task(task_id, error_msg)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Generate task crashed: task_id=%s name=%s", task_id, params.name)
        task_store.fail_task(task_id, str(exc) or "unknown error")
    finally:
        # Safety net: if the task is still RUNNING (e.g. a coroutine was cancelled),
        # mark it failed so the client doesn't poll forever.
        task = task_store.get_task(task_id)
        if task is not None and task.status == TaskStatus.RUNNING:
            task_store.fail_task(task_id, "Task ended without final status")


async def execute_eval_run_task(
    task_id: str,
    request: RunEvalRequest,
    eval_service: EvaluationService,
    task_store: EvalTaskStore,
) -> None:
    """Run an evaluation against an existing test set with progress reporting."""
    task_store.start_task(task_id)

    def progress_cb(current: int, total: int) -> None:
        task_store.update_run_progress(task_id, current, total)

    try:
        report, saved_path = await eval_service.run_evaluation(
            test_set_name=request.test_set_name,
            top_k=request.top_k,
            mode=request.mode,
            report_name=request.report_name,
            persist_report=request.persist_report,
            progress_cb=progress_cb,
            topology_spec=request.topology,
        )
        summary = {
            "num_queries": report.num_queries,
            "top_k": report.top_k,
            "aggregate_metrics": report.aggregate_metrics,
        }
        task_store.complete_task(
            task_id,
            summary=summary,
            result_path=str(saved_path) if saved_path else None,
        )
    except RecallError as exc:
        logger.exception(
            "Run task failed: task_id=%s test_set=%s", task_id, request.test_set_name,
        )
        detail = getattr(exc, "detail", None)
        error_msg = f"{exc.message} | {detail}" if detail else exc.message
        task_store.fail_task(task_id, error_msg)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Run task crashed: task_id=%s test_set=%s", task_id, request.test_set_name,
        )
        task_store.fail_task(task_id, str(exc) or "unknown error")
    finally:
        task = task_store.get_task(task_id)
        if task is not None and task.status == TaskStatus.RUNNING:
            task_store.fail_task(task_id, "Task ended without final status")
