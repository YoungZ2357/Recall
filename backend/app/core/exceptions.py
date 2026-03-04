"""
All exceptions should be processed by FastAPI exception handler
All excecptions has status code

Use example:

    from app.core.exceptions import DocumentNotFoundError

    raise DocumentNotFoundError(doc_id="abc-123")
"""

from __future__ import annotations


# ============================================================
# 基类
# ============================================================

class RecallError(Exception):
    """
    """

    status_code: int = 500
    message: str = "Server Error"

    def __init__(
        self,
        message: str | None = None,
        detail: str | None = None,
    ) -> None:
        self.message = message or self.__class__.message
        self.detail = detail
        super().__init__(self.message)

    def __repr__(self) -> str:
        cls = self.__class__.__name__
        if self.detail:
            return f"{cls}(message={self.message!r}, detail={self.detail!r})"
        return f"{cls}(message={self.message!r})"


# ============================================================
# 数据库层（SQLite / SQLAlchemy）
# ============================================================

class DatabaseError(RecallError):
    """SQLite / SQLAlchemy operations failed"""

    status_code = 500
    message = "Failed operation in database"


class DocumentNotFoundError(RecallError):
    """Document does not exist"""

    status_code = 404
    message = "Document does not exist"

    def __init__(
        self,
        doc_id: str | None = None,
        **kwargs,
    ) -> None:
        msg = f"Document does not exist: {doc_id}" if doc_id else None
        super().__init__(message=msg, **kwargs)
        self.doc_id = doc_id


class ChunkNotFoundError(RecallError):
    """Chunk does not exist"""

    status_code = 404
    message = "Chunk does not exist"

    def __init__(
        self,
        chunk_id: str | None = None,
        **kwargs,
    ) -> None:
        msg = f"Chunk does not exist: {chunk_id}" if chunk_id else None
        super().__init__(message=msg, **kwargs)
        self.chunk_id = chunk_id


# ============================================================
# Vector Database (Qdrant)
# ============================================================

class VectorDBError(RecallError):
    """Failed operation in vector database, including connection, upsert, search, delete, etc."""

    status_code = 502
    message = "Failed operation in vector database"


class CollectionNotFoundError(VectorDBError):
    """Qdrant collection does not exist"""

    status_code = 404
    message = "Qdrant collection does not exist"


# ============================================================
# Chunk 生命周期管理
# ============================================================

class ChunkManagerError(RecallError):
    """chunk_manager 协调 SQLite / Qdrant 时发生错误。"""
    """Failed to corrdinate SQLite / Qdrant"""

    status_code = 500
    message = "Failed operation in life cycle management"


class SyncError(ChunkManagerError):
    """Failed to sync SQLite and Qdrant"""

    message = "Failed to sync data"


# ============================================================
# Embedding
# ============================================================

class EmbeddingError(RecallError):
    """Failed to generate embedding"""

    status_code = 502
    message = "Failed to generate embedding"


class EmbeddingDimensionMismatchError(EmbeddingError):
    """Embedding dimension mismatch with current Qdrant collection"""

    status_code = 409
    message = "Embedding dimension mismatch with current Qdrant collection. Please reindex"

    def __init__(
        self,
        expected: int | None = None,
        actual: int | None = None,
        **kwargs,
    ) -> None:
        msg = None
        if expected is not None and actual is not None:
            msg = f"Embedding dimension mismatch: Expected:{expected}, Actual: {actual}"
        super().__init__(message=msg, **kwargs)
        self.expected = expected
        self.actual = actual


# ============================================================
# 文档摄入（Ingestion）
# ============================================================

class IngestionError(RecallError):
    """Failed to injest document"""

    status_code = 422
    message = "Failed to injest document"


class ParsingError(IngestionError):
    """文件解析失败（格式不支持、文件损坏等）。"""
    """Failed to parse document(which includes wrong format and broken file)"""

    message = "Failed to parse document"


class UnsupportedFileTypeError(ParsingError):
    """Unsupported file type"""

    message = "Unsupported file type"

    def __init__(
        self,
        file_type: str | None = None,
        **kwargs,
    ) -> None:
        msg = f"Unsupported file type: {file_type}" if file_type else None
        super().__init__(message=msg, **kwargs)
        self.file_type = file_type


# ============================================================
# 检索（Retrieval）
# ============================================================

class RetrievalError(RecallError):
    """Failed to retrieve"""

    status_code = 500
    message = "Failed to retrieve"


# ============================================================
# 配置
# ============================================================

class ConfigError(RecallError):
    """Wrong config(which includes missing required parameters and wrong param type)"""

    status_code = 500
    message = "Wrong config"