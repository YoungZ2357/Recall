"""
All exceptions should be processed by FastAPI exception handler.
All exceptions have a status_code attribute.

Use example:

    from app.core.exceptions import DocumentNotFoundError

    raise DocumentNotFoundError(doc_id="abc-123")
"""

from __future__ import annotations


# ============================================================
# 基类
# ============================================================

class RecallError(Exception):
    """Recall 全局异常基类，所有自定义异常均继承此类。"""

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
    """Failed to coordinate SQLite / Qdrant"""

    status_code = 500
    message = "Failed operation in life cycle management"


class SyncError(ChunkManagerError):
    """Failed to sync SQLite and Qdrant"""
    message = "Failed to sync data"

    def __init__(
        self,
        doc_id: str | None = None,
        **kwargs,
    ) -> None:
        msg = f"Failed to sync data (doc_id={doc_id})" if doc_id else None
        super().__init__(message=msg, **kwargs)
        self.doc_id = doc_id


class InvalidSyncStatusTransitionError(ChunkManagerError):
    """
    不合法的 sync_status 状态转换。

    合法转换:
        Pending  → Synced | Failed
        Synced   → Dirty
        Dirty    → Synced | Failed
        Failed   → Pending
    """

    status_code = 409
    message = "Invalid sync status transition"

    def __init__(
        self,
        doc_id: str | None = None,
        from_status: str | None = None,
        to_status: str | None = None,
        **kwargs,
    ) -> None:
        msg = None
        if from_status and to_status:
            parts = [f"Invalid sync status transition: {from_status} → {to_status}"]
            if doc_id:
                parts.append(f"(doc_id={doc_id})")
            msg = " ".join(parts)
        super().__init__(message=msg, **kwargs)
        self.doc_id = doc_id
        self.from_status = from_status
        self.to_status = to_status


# ============================================================
# 健康检查（Health Check）
# ============================================================

class HealthCheckError(ChunkManagerError):
    """
    健康检查未通过的基类。

    健康检查分两层执行：
      Layer 1 — 快检: chunk 数量是否匹配 (ChunkCountMismatchError)
      Layer 2 — 全检: 逐 chunk UUID 双向差集比较 (ChunkIDMismatchError)
    Layer 1 失败时直接标记 Dirty，不再执行 Layer 2。
    """

    status_code = 409
    message = "Health check failed"

    def __init__(
        self,
        doc_id: str | None = None,
        **kwargs,
    ) -> None:
        self.doc_id = doc_id
        super().__init__(**kwargs)


class ChunkCountMismatchError(HealthCheckError):
    """
    Layer 1 快检失败：SQLite 与 Qdrant 的 chunk 数量不一致。
    触发 Synced → Dirty 转换。
    """

    message = "Chunk count mismatch between SQLite and Qdrant"

    def __init__(
        self,
        doc_id: str | None = None,
        expected: int | None = None,
        actual: int | None = None,
        **kwargs,
    ) -> None:
        msg = None
        if expected is not None and actual is not None:
            parts = [f"Chunk count mismatch: SQLite={expected}, Qdrant={actual}"]
            if doc_id:
                parts.append(f"(doc_id={doc_id})")
            msg = " ".join(parts)
        super().__init__(doc_id=doc_id, message=msg, **kwargs)
        self.expected = expected
        self.actual = actual


class ChunkIDMismatchError(HealthCheckError):
    """
    Layer 2 全检失败：逐 UUID 比较发现 SQLite 与 Qdrant 之间存在差集。
    missing_in_qdrant: SQLite 中有但 Qdrant 中缺失的 chunk_id 集合
    orphaned_in_qdrant: Qdrant 中有但 SQLite 中不存在的 point_id 集合
    """

    message = "Chunk ID mismatch between SQLite and Qdrant"

    def __init__(
        self,
        doc_id: str | None = None,
        missing_in_qdrant: set[str] | None = None,
        orphaned_in_qdrant: set[str] | None = None,
        **kwargs,
    ) -> None:
        parts = ["Chunk ID mismatch"]
        if doc_id:
            parts.append(f"(doc_id={doc_id})")
        if missing_in_qdrant:
            parts.append(f"| missing_in_qdrant={len(missing_in_qdrant)}")
        if orphaned_in_qdrant:
            parts.append(f"| orphaned_in_qdrant={len(orphaned_in_qdrant)}")
        super().__init__(doc_id=doc_id, message=" ".join(parts), **kwargs)
        self.missing_in_qdrant = missing_in_qdrant or set()
        self.orphaned_in_qdrant = orphaned_in_qdrant or set()



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
            msg = f"Embedding dimension mismatch: expected={expected}, actual={actual}"
        super().__init__(message=msg, **kwargs)
        self.expected = expected
        self.actual = actual



class IngestionError(RecallError):
    """Failed to ingest document"""

    status_code = 422
    message = "Failed to ingest document"


class ParsingError(IngestionError):
    """Failed to parse document (unsupported format, corrupted file, etc.)"""

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



class RetrievalError(RecallError):
    """Failed to retrieve"""

    status_code = 500
    message = "Failed to retrieve"

class ConfigError(RecallError):
    """Wrong config (missing required parameters, wrong param type, etc.)"""

    status_code = 500
    message = "Wrong config"


# ============================================================
# Generation (LLM)
# ============================================================

class GenerationError(RecallError):
    """Failed to generate LLM response"""

    status_code = 502
    message = "Failed to generate LLM response"