from typing import Literal
from uuid import UUID as PyUUID

from pydantic import BaseModel, ConfigDict, Field


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


# ============================================================
# Search API schemas
# ============================================================


class SearchRequest(BaseModel):
    """POST /api/search request body."""
    query: str
    top_k: int = Field(default=10, ge=1, le=50)
    mode: Literal["prefer_recent", "awaken_forgotten"] = "prefer_recent"


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
