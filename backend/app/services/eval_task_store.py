"""In-memory task state store for evaluation jobs (generate + run).

Mirrors the ingest TaskStore pattern but with a flatter shape — each eval
task tracks a single linear progression rather than per-file × per-stage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from app.services.task_store import TaskStatus

GenerateStage = Literal["sampling", "synthesizing", "grading", "writing"]


class EvalTaskKind(StrEnum):
    GENERATE = "generate"
    RUN = "run"


@dataclass
class GenerateProgress:
    stage: GenerateStage = "sampling"
    current: int = 0
    total: int = 0


@dataclass
class RunProgress:
    current_query: int = 0
    total_queries: int = 0


@dataclass
class EvalTask:
    task_id: str
    kind: EvalTaskKind
    name: str  # test-set name (for generate / run input) or report name
    status: TaskStatus = TaskStatus.PENDING
    progress: GenerateProgress | RunProgress = field(default_factory=GenerateProgress)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    result_path: str | None = None
    summary: dict | None = None


class EvalTaskStore:
    """In-memory store. Not persistent across restarts."""

    def __init__(self) -> None:
        self._tasks: dict[str, EvalTask] = {}

    def create_task(
        self,
        task_id: str,
        kind: EvalTaskKind,
        name: str,
    ) -> EvalTask:
        progress: GenerateProgress | RunProgress = (
            GenerateProgress() if kind == EvalTaskKind.GENERATE else RunProgress()
        )
        task = EvalTask(task_id=task_id, kind=kind, name=name, progress=progress)
        self._tasks[task_id] = task
        return task

    def get_task(self, task_id: str) -> EvalTask | None:
        return self._tasks.get(task_id)

    def start_task(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if task is not None:
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.now(UTC)

    def update_generate_progress(
        self,
        task_id: str,
        *,
        stage: GenerateStage | None = None,
        current: int | None = None,
        total: int | None = None,
    ) -> None:
        task = self._tasks.get(task_id)
        if task is None or not isinstance(task.progress, GenerateProgress):
            return
        if stage is not None:
            task.progress.stage = stage
            # Reset counters when stage transitions
            task.progress.current = 0
            task.progress.total = 0
        if current is not None:
            task.progress.current = current
        if total is not None:
            task.progress.total = total

    def update_run_progress(
        self,
        task_id: str,
        current: int,
        total: int,
    ) -> None:
        task = self._tasks.get(task_id)
        if task is None or not isinstance(task.progress, RunProgress):
            return
        task.progress.current_query = current
        task.progress.total_queries = total

    def complete_task(
        self,
        task_id: str,
        *,
        summary: dict | None = None,
        result_path: str | None = None,
    ) -> None:
        task = self._tasks.get(task_id)
        if task is None:
            return
        task.status = TaskStatus.DONE
        task.completed_at = datetime.now(UTC)
        task.summary = summary
        task.result_path = result_path

    def fail_task(self, task_id: str, error: str) -> None:
        task = self._tasks.get(task_id)
        if task is None:
            return
        task.status = TaskStatus.ERROR
        task.completed_at = datetime.now(UTC)
        task.error = error
