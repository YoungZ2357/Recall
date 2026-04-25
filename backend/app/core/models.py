from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID as PyUUID

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import text

from .database import Base


class SyncStatus(StrEnum):
    PENDING = "pending"
    SYNCED = "synced"
    DIRTY = "dirty"
    FAILED = "failed"


class Document(Base):
    __tablename__ = "documents"

    document_id: Mapped[PyUUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=True)
    source_path: Mapped[str] = mapped_column(String(500), nullable=True)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
    weight: Mapped[float] = mapped_column(
        Float, default=1.0, nullable=False, server_default=text("1.0")
    )
    sync_status: Mapped[SyncStatus] = mapped_column(
        String(20),
        default=SyncStatus.PENDING,
        nullable=False,
    )

    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_documents_file_hash", "file_hash"),
    )


class Chunk(Base):
    __tablename__ = "chunks"

    chunk_id: Mapped[PyUUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True
    )
    document_id: Mapped[PyUUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("documents.document_id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[str] = mapped_column(
        Text, default="[]", nullable=False, server_default=text("'[]'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
    context: Mapped[str | None] = mapped_column(Text, default=None, nullable=True)
    context_embedded: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=text("0")
    )
    sync_status: Mapped[SyncStatus] = mapped_column(
        String(20), default=SyncStatus.PENDING, index=True
    )

    document: Mapped["Document"] = relationship(back_populates="chunks")

    __table_args__ = (
        Index("ix_chunks_document_id", "document_id"),
        Index("ix_chunks_document_id_index", "document_id", "chunk_index"),
        UniqueConstraint("document_id", "chunk_index", name="uq_chunk_document_index"),
    )


class ChunkAccess(Base):
    """Append-only access log for Ebbinghaus retention scoring."""
    __tablename__ = "chunk_accesses"

    access_id: Mapped[PyUUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True
    )
    chunk_id: Mapped[PyUUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("chunks.chunk_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
        index=True,
    )
