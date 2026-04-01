from pydantic import BaseModel, ConfigDict
from uuid import UUID as PyUUID


class DocumentCreate(BaseModel):
    title: str | None = None
    source_path: str | None = None
    file_hash: str | None = None


class ChunkCreate(BaseModel):
    document_id: PyUUID
    chunk_index: int
    content: str
    # embedding: list[float]

    # model_config = ConfigDict(arbitrary_types_allowed=True)


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


class RerankResult(BaseModel):
    """Single reranked result with score breakdown."""
    chunk_id: PyUUID
    final_score: float
    retrieval_score: float
    metadata_score: float
    retention_score: float


class RetrievalResult(BaseModel):
    """Pipeline output: rerank scores + chunk content."""
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
    context: list[RetrievalResult]
    max_tokens: int | None = None
    temperature: float | None = None
    stream: bool = False


class GenerateResponse(BaseModel):
    """POST /generate non-streaming response."""
    answer: str
    model: str
    usage: dict[str, int] | None = None
