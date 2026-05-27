from typing import Literal
from uuid import UUID as PyUUID

from pydantic import BaseModel, ConfigDict, Field

from app.retrieval.topology import TopologySpecJSON


class DocumentCreate(BaseModel):
    title: str | None = None
    source_path: str | None = None
    file_hash: str | None = None


class ChunkCreate(BaseModel):
    document_id: PyUUID
    chunk_index: int
    content: str


class DocumentQuery(BaseModel):
    title: str | None = None
    source_path: str | None = None


class ChunkQuery(BaseModel):
    document_id: PyUUID | None = None
    chunk_index: int | None = None


class ChunkIngest(BaseModel):
    """Schema for passing chunk data + embedding vector into ChunkManager.write_chunks."""
    document_id: PyUUID
    chunk_index: int
    content: str
    vector: list[float]
    tags: list[str] = []
    context: str | None = None
    context_embedded: bool = False


class RetrievalResult(BaseModel):
    """Pipeline output: rerank scores + chunk content.

    Assembled from a SearchHit (source="rerank") plus hydrated content.
    final_score maps to SearchHit.score; breakdown fields map to the
    optional SearchHit.retrieval_score / metadata_score / retention_score.
    """
    chunk_id: PyUUID
    final_score: float
    retrieval_score: float
    metadata_score: float
    retention_score: float
    content: str
    document_title: str | None = None


class GenerateRequest(BaseModel):
    """POST /generate request body."""
    query: str
    top_k: int = 5
    mode: Literal["prefer_recent", "awaken_forgotten"] = "prefer_recent"
    stream: bool = False
    topology: TopologySpecJSON | None = None


class GenerateResponse(BaseModel):
    """POST /generate non-streaming response."""
    answer: str
    model: str
    usage: dict[str, int] | None = None


# ============================================================
# Documents API schemas
# ============================================================


class DocumentSummary(BaseModel):
    """GET /api/documents list item."""
    doc_id: str
    filename: str
    file_type: str
    chunk_count: int
    created_at: str
    weight: float
    sync_status: str

    model_config = ConfigDict(from_attributes=True)


class DocumentDetail(BaseModel):
    """GET /api/documents/{doc_id} detail response."""
    doc_id: str
    filename: str
    file_type: str
    total_chunks: int
    synced_chunks: int
    tags: list[str]
    created_at: str
    weight: float
    sync_status: str

    model_config = ConfigDict(from_attributes=True)


class UploadResponse(BaseModel):
    """POST /api/documents/upload response."""
    doc_id: str
    filename: str
    chunk_count: int
    status: str


class DeleteResponse(BaseModel):
    """DELETE /api/documents/{doc_id} response."""
    deleted: bool
    doc_id: str


class ChunkDetail(BaseModel):
    """GET /api/documents/{doc_id}/chunks list item."""
    chunk_id: str
    chunk_index: int
    content: str
    context: str | None
    tags: list[str]
    sync_status: str


class WeightUpdate(BaseModel):
    """PATCH /api/documents/{doc_id}/weight request body."""
    weight: float = Field(ge=0.0, le=2.0)


# ============================================================
# Search API schemas
# ============================================================


class SearchRequest(BaseModel):
    """POST /api/search request body."""
    query: str
    top_k: int = Field(default=10, ge=1, le=50)
    mode: Literal["prefer_recent", "awaken_forgotten"] = "prefer_recent"
    topology: TopologySpecJSON | None = None


class ScoreDetail(BaseModel):
    retrieval_score: float
    metadata_score: float
    retention_score: float


class SearchResultItem(BaseModel):
    """Single search result in response."""
    chunk_id: str
    content: str
    doc_id: str
    filename: str
    final_score: float
    score_detail: ScoreDetail
    tags: list[str]


class SourceInfo(BaseModel):
    """Chunk source metadata for SSE sources event."""
    doc_id: str
    filename: str
    chunk_id: str


# ============================================================
# Ingest task schemas (POST /api/upload, POST /api/ingest, GET /api/ingest/{task_id})
# ============================================================


class TempFileInfo(BaseModel):
    """Single file info returned by POST /api/upload."""
    file_id: str
    filename: str
    size: int
    file_hash: str


class TempUploadResponse(BaseModel):
    """POST /api/upload response."""
    files: list[TempFileInfo]


class IngestRequest(BaseModel):
    """POST /api/ingest request body."""
    file_ids: list[str]
    # Client-supplied task UUID. When present, the backend uses it as-is so the
    # client can persist the task_id before the request flies (eliminates the
    # race window where the backend creates a task but the client never learns
    # its id). Omit to let the backend generate one (CLI / legacy callers).
    task_id: str | None = None
    pdf_parser: Literal["pymupdf", "marker", "mineru"] = "pymupdf"
    strip_tail: bool = True
    strip_markdown: bool = False
    chunk_strategy: Literal["recursive", "fixed_count"] = "recursive"
    chunk_size: int = Field(default=512, ge=1)
    chunk_overlap: int = Field(default=64, ge=0)
    target_chunks: int = Field(default=20, ge=1)
    overlap_ratio: float = Field(default=0.1, ge=0.0, le=1.0)
    contextualize: bool = True
    context_concurrency: int = Field(default=8, ge=1)
    auto_tag: bool = True


class IngestResponse(BaseModel):
    """POST /api/ingest response."""
    task_id: str


class StageProgressResponse(BaseModel):
    stage: str
    status: str
    detail: str
    current: int
    total: int


class FileTaskProgressResponse(BaseModel):
    file_id: str
    filename: str
    status: str
    stages: list[StageProgressResponse]
    error: str | None
    chunk_count: int
    tags: list[str]


class TaskStatusResponse(BaseModel):
    """GET /api/ingest/{task_id} response."""
    task_id: str
    status: str
    files: list[FileTaskProgressResponse]
    started_at: str | None
    completed_at: str | None


# ============================================================
# Post-op document operation schemas
# ============================================================


class RetagRequest(BaseModel):
    """POST /api/documents/{doc_id}/retag request body."""
    tags: list[str] | None = None  # None = auto-regenerate via LLM


# ============================================================
# System stats schema
# ============================================================


class SystemStatsResponse(BaseModel):
    """GET /api/stats response."""
    document_count: int
    chunk_count: int
    synced_count: int
    dirty_count: int
    failed_count: int
    last_ingestion_at: str | None
