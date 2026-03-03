from datetime import UTC, datetime
from uuid import UUID as PyUUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import text

from .database import Base


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

    document: Mapped["Document"] = relationship(back_populates="chunks")

    __table_args__ = (
        Index("ix_chunks_document_id", "document_id"),
        Index("ix_chunks_document_id_index", "document_id", "chunk_index"),
        UniqueConstraint("document_id", "chunk_index", name="uq_chunk_document_index"),
    )
