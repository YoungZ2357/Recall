"""Pydantic request/response models for the /api/eval router.

Kept in a separate module from core/schemas.py because eval has a focused
audience (just the eval router) and core/schemas.py already covers a wide
ingest / documents / generate surface.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.evaluation.schemas import EvalReport, TestSetEntry

# ============================================================
# Constants
# ============================================================

NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


# ============================================================
# Requests
# ============================================================


class GenerateTestSetRequest(BaseModel):
    """POST /api/eval/test-sets/generate request body."""

    name: str = Field(..., description="Test set name (filename stem); [A-Za-z0-9_-]{1,64}")
    num_chunks: int = Field(default=50, ge=1)
    queries_per_chunk: int = Field(default=2, ge=1)
    min_length: int = Field(default=100, ge=1)
    concurrency: int = Field(default=5, ge=1)
    with_context: bool = False
    pool_size: int = Field(default=50, ge=1)
    skip_grading: bool = False
    include_doc_ids: list[str] | None = None
    exclude_doc_ids: list[str] | None = None
    auto_split: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not NAME_PATTERN.match(v):
            raise ValueError("name must match [A-Za-z0-9_-]{1,64}")
        return v

    @model_validator(mode="after")
    def _validate_filters_exclusive(self) -> GenerateTestSetRequest:
        active = sum([
            bool(self.include_doc_ids),
            bool(self.exclude_doc_ids),
            self.auto_split > 0.0,
        ])
        if active > 1:
            raise ValueError(
                "include_doc_ids, exclude_doc_ids, and auto_split are mutually exclusive"
            )
        return self


class RunEvalRequest(BaseModel):
    """POST /api/eval/run request body."""

    test_set_name: str = Field(..., description="Test set name to evaluate against")
    top_k: int = Field(default=10, ge=1)
    mode: Literal["prefer_recent", "awaken_forgotten"] = "prefer_recent"
    report_name: str | None = Field(
        default=None,
        description="Report filename stem; defaults to test_set_name when omitted",
    )
    persist_report: bool = True

    @field_validator("test_set_name")
    @classmethod
    def _validate_test_set_name(cls, v: str) -> str:
        if not NAME_PATTERN.match(v):
            raise ValueError("test_set_name must match [A-Za-z0-9_-]{1,64}")
        return v

    @field_validator("report_name")
    @classmethod
    def _validate_report_name(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not NAME_PATTERN.match(v):
            raise ValueError("report_name must match [A-Za-z0-9_-]{1,64}")
        return v


# ============================================================
# Task progress / status
# ============================================================


class EvalTaskIdResponse(BaseModel):
    task_id: str


class GenerateProgressResponse(BaseModel):
    stage: Literal["sampling", "synthesizing", "grading", "writing"]
    current: int
    total: int


class RunProgressResponse(BaseModel):
    current_query: int
    total_queries: int


class EvalTaskStatusResponse(BaseModel):
    """GET /api/eval/tasks/{task_id} response."""

    task_id: str
    kind: Literal["generate", "run"]
    name: str
    status: Literal["pending", "running", "done", "error"]
    progress: GenerateProgressResponse | RunProgressResponse
    summary: dict | None = None
    result_path: str | None = None
    error: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


# ============================================================
# Test set / report listing
# ============================================================


class TestSetSummaryResponse(BaseModel):
    name: str
    entry_count: int
    created_at: str
    size_bytes: int


class TestSetPreviewResponse(BaseModel):
    name: str
    entry_count: int
    created_at: str
    size_bytes: int
    entries: list[TestSetEntry]


class ReportSummaryResponse(BaseModel):
    name: str
    created_at: str
    num_queries: int
    top_k: int
    aggregate_metrics: dict[str, float]


# Full report response — re-export EvalReport so routes can annotate cleanly
ReportResponse = EvalReport
