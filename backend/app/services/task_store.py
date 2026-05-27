"""In-memory task state store for async ingestion jobs."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


class StageStatus(StrEnum):
    WAITING = "waiting"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    SKIPPED = "skipped"


# Pipeline stage names in execution order (must match IngestionPipeline.ingest() callbacks)
PIPELINE_STAGES = ["Parsing", "Filtering", "Chunking", "Contextualizing", "Embedding", "Writing"]


@dataclass
class StageProgress:
    stage: str
    status: StageStatus = StageStatus.WAITING
    detail: str = ""
    current: int = 0
    total: int = 0


@dataclass
class FileTaskProgress:
    file_id: str
    filename: str
    status: TaskStatus = TaskStatus.PENDING
    stages: list[StageProgress] = field(default_factory=list)
    error: str | None = None
    chunk_count: int = 0
    tags: list[str] = field(default_factory=list)


@dataclass
class IngestTask:
    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    files: list[FileTaskProgress] = field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None


class TaskStore:
    """In-memory task state store. Not persistent across restarts."""

    def __init__(self) -> None:
        self._tasks: dict[str, IngestTask] = {}

    def create_task(self, task_id: str, file_infos: list[dict[str, Any]]) -> IngestTask:
        files = [
            FileTaskProgress(
                file_id=info["file_id"],
                filename=info["filename"],
                stages=[StageProgress(stage=s) for s in PIPELINE_STAGES],
            )
            for info in file_infos
        ]
        task = IngestTask(task_id=task_id, files=files)
        self._tasks[task_id] = task
        return task

    def get_task(self, task_id: str) -> IngestTask | None:
        return self._tasks.get(task_id)

    def start_task(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if task is not None:
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.now(UTC)

    def update_file_status(
        self,
        task_id: str,
        file_id: str,
        status: TaskStatus,
        error: str | None = None,
    ) -> None:
        task = self._tasks.get(task_id)
        if task is None:
            return
        for fp in task.files:
            if fp.file_id == file_id:
                fp.status = status
                if error is not None:
                    fp.error = error
                return

    def update_stage(
        self,
        task_id: str,
        file_id: str,
        stage: str,
        status: StageStatus,
        detail: str = "",
        current: int = 0,
        total: int = 0,
    ) -> None:
        task = self._tasks.get(task_id)
        if task is None:
            return
        for fp in task.files:
            if fp.file_id == file_id:
                for sp in fp.stages:
                    if sp.stage == stage:
                        sp.status = status
                        sp.detail = detail
                        sp.current = current
                        sp.total = total
                        return

    def set_chunk_count(self, task_id: str, file_id: str, count: int) -> None:
        task = self._tasks.get(task_id)
        if task is None:
            return
        for fp in task.files:
            if fp.file_id == file_id:
                fp.chunk_count = count
                return

    def set_tags(self, task_id: str, file_id: str, tags: list[str]) -> None:
        task = self._tasks.get(task_id)
        if task is None:
            return
        for fp in task.files:
            if fp.file_id == file_id:
                fp.tags = tags
                return

    def complete_task(self, task_id: str) -> None:
        """Mark task complete; status is DONE only if all files succeeded."""
        task = self._tasks.get(task_id)
        if task is not None:
            all_done = all(f.status == TaskStatus.DONE for f in task.files)
            task.status = TaskStatus.DONE if all_done else TaskStatus.ERROR
            task.completed_at = datetime.now(UTC)

    def fail_task(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if task is not None:
            task.status = TaskStatus.ERROR
            task.completed_at = datetime.now(UTC)
