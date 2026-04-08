"""Stratified chunk sampling from SQLite for evaluation test set generation."""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.repository import ChunkRepository, DocumentRepository

logger = logging.getLogger(__name__)


@dataclass
class SampledChunk:
    """A chunk selected for query synthesis."""
    chunk_id: str
    document_id: str
    content: str
    document_title: str
    context: str | None = None


async def sample_chunks_stratified(
    session: AsyncSession,
    total_n: int = 50,
    min_content_length: int = 100,
    include_doc_ids: list[str] | None = None,
    exclude_doc_ids: list[str] | None = None,
) -> list[SampledChunk]:
    """Sample chunks with proportional allocation across documents.

    Algorithm:
        1. Fetch all documents and their chunks.
        2. Apply include/exclude document filters.
        3. Filter chunks by minimum content length.
        4. Allocate per-document quota proportional to eligible chunk count.
        5. Random sample within each document.

    Args:
        session: Async database session.
        total_n: Target number of chunks to sample.
        min_content_length: Minimum character length for eligible chunks.
        include_doc_ids: Whitelist of document IDs. If set, only these documents
            are used. Mutually exclusive with exclude_doc_ids.
        exclude_doc_ids: Blacklist of document IDs. If set, these documents are
            skipped. Mutually exclusive with include_doc_ids.

    Returns:
        List of sampled chunks, may be fewer than total_n if the database
        has insufficient eligible chunks.
    """
    documents = await DocumentRepository.list_all(session)

    if include_doc_ids is not None:
        include_set = set(include_doc_ids)
        documents = [d for d in documents if str(d.document_id) in include_set]
        logger.info("include_doc_ids filter applied: %d documents retained", len(documents))
    elif exclude_doc_ids is not None:
        exclude_set = set(exclude_doc_ids)
        documents = [d for d in documents if str(d.document_id) not in exclude_set]
        logger.info("exclude_doc_ids filter applied: %d documents retained", len(documents))
    if not documents:
        logger.warning("No documents in database, cannot sample chunks")
        return []

    # Collect eligible chunks per document
    doc_eligible: dict[str, list[SampledChunk]] = {}
    total_eligible = 0

    for doc in documents:
        if not doc.title:
            logger.warning(
                "Document %s has no title, skipping for evaluation sampling",
                doc.document_id,
            )
            continue
        chunks = await ChunkRepository.list_by_document(session, doc.document_id)
        eligible = [
            SampledChunk(
                chunk_id=str(c.chunk_id),
                document_id=str(c.document_id),
                content=c.content,
                document_title=doc.title,
                context=c.context,
            )
            for c in chunks
            if len(c.content) >= min_content_length
        ]
        if eligible:
            doc_eligible[str(doc.document_id)] = eligible
            total_eligible += len(eligible)

    if total_eligible == 0:
        logger.warning(
            "No chunks meet min_content_length=%d, cannot sample", min_content_length
        )
        return []

    if total_eligible <= total_n:
        logger.warning(
            "Only %d eligible chunks available (requested %d), using all",
            total_eligible, total_n,
        )
        return [chunk for chunks in doc_eligible.values() for chunk in chunks]

    # Proportional quota allocation
    quotas: dict[str, int] = {}
    for doc_id, chunks in doc_eligible.items():
        quotas[doc_id] = max(1, round(total_n * len(chunks) / total_eligible))

    # Trim excess from the largest-quota document(s)
    while sum(quotas.values()) > total_n:
        max_doc = max(quotas, key=quotas.get)  # type: ignore[arg-type]
        quotas[max_doc] -= 1

    # Sample within each document
    sampled: list[SampledChunk] = []
    for doc_id, quota in quotas.items():
        eligible = doc_eligible[doc_id]
        quota = min(quota, len(eligible))
        sampled.extend(random.sample(eligible, quota))

    logger.info(
        "Sampled %d chunks from %d documents", len(sampled), len(quotas)
    )
    return sampled
