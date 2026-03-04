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
    embedding: list[float]

    model_config = ConfigDict(arbitrary_types_allowed=True)
