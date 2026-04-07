"""MCP stdio server — exposes Recall retrieval tools to MCP clients.

Run with:
    python -m app.mcp
"""

import json
import logging
from contextlib import asynccontextmanager
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP

from app.cli._init_deps import init_deps, teardown_deps
from app.config import settings
from app.core.chunk_manager import ChunkManager
from app.core.models import SyncStatus
from app.core.pipeline_deps import PipelineDeps
from app.core.repository import DocumentRepository
from app.retrieval.pipeline import RetrievalPipeline

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan: initialize shared deps once for the server process lifetime
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(server: FastMCP):  # noqa: ARG001
    resources = await init_deps(settings)
    try:
        yield {
            "session_factory": resources.session_factory,
            "qdrant": resources.qdrant_client,
            "embedder": resources.embedder,
            "generator": resources.generator,
        }
    finally:
        await teardown_deps(resources.qdrant_client, resources.embedder, resources.generator)


mcp = FastMCP("Recall", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _build_pipeline(lc: dict) -> RetrievalPipeline:
    """Construct a RetrievalPipeline from the lifespan context."""
    from app.retrieval import workflows
    deps = PipelineDeps(
        embedder=lc["embedder"],
        qdrant_client=lc["qdrant"],
        session_factory=lc["session_factory"],
    )
    return RetrievalPipeline(
        dag=workflows.hybrid(deps),
        embedder=deps.embedder,
        session_factory=deps.session_factory,
    )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def search(
    query: str,
    ctx: Context,
    top_k: int = 5,
    mode: str = "prefer_recent",
) -> str:
    """Search the knowledge base and return ranked chunks with scores.

    Args:
        query: Search query text.
        top_k: Number of results to return (default 5).
        mode: Retention mode — prefer_recent or awaken_forgotten.

    Returns:
        JSON array of results. Each item contains chunk_id, document_title,
        content, final_score, retrieval_score, metadata_score, retention_score.
    """
    lc = ctx.request_context.lifespan_context
    pipeline = _build_pipeline(lc)
    results = await pipeline.search(
        query_text=query,
        top_k=top_k,
        retention_mode=mode,  # type: ignore[arg-type]
    )
    return json.dumps(
        [
            {
                "chunk_id": str(r.chunk_id),
                "document_title": r.document_title,
                "content": r.content,
                "final_score": round(r.final_score, 4),
                "retrieval_score": round(r.retrieval_score, 4),
                "metadata_score": round(r.metadata_score, 4),
                "retention_score": round(r.retention_score, 4),
            }
            for r in results
        ],
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool()
async def generate(
    query: str,
    ctx: Context,
    top_k: int = 5,
    mode: str = "prefer_recent",
) -> str:
    """Retrieve relevant context from the knowledge base and generate an answer.

    Args:
        query: Question to answer.
        top_k: Number of context chunks to retrieve (default 5).
        mode: Retention mode — prefer_recent or awaken_forgotten.

    Returns:
        The generated answer text, or an error message if the LLM is not configured.
    """
    lc = ctx.request_context.lifespan_context
    generator = lc["generator"]
    if generator is None:
        return "Error: LLM generator not available. Set LLM_API_KEY to enable generation."

    pipeline = _build_pipeline(lc)
    results = await pipeline.search(
        query_text=query,
        top_k=top_k,
        retention_mode=mode,  # type: ignore[arg-type]
    )
    response = await generator.generate(query, results)
    return response.answer


@mcp.tool()
async def list_documents(ctx: Context) -> str:
    """List all documents in the knowledge base.

    Returns:
        JSON array of documents. Each item contains document_id, title,
        source_path, sync_status, and created_at (ISO 8601).
    """
    lc = ctx.request_context.lifespan_context
    session_factory = lc["session_factory"]

    async with session_factory() as session:
        docs = await DocumentRepository.list_all(session)
        payload = json.dumps(
            [
                {
                    "document_id": str(doc.document_id),
                    "title": doc.title,
                    "source_path": doc.source_path,
                    "sync_status": (
                        doc.sync_status.value
                        if hasattr(doc.sync_status, "value")
                        else doc.sync_status
                    ),
                    "created_at": doc.created_at.isoformat(),
                }
                for doc in docs
            ],
            ensure_ascii=False,
            indent=2,
        )
    return payload


@mcp.tool()
async def reindex(
    ctx: Context,
    doc_id: str | None = None,
    reindex_all: bool = False,
) -> str:
    """Re-embed documents after an embedding model change.

    Default (no args): processes all DIRTY and FAILED documents.
    doc_id set: re-embeds a single document regardless of its current status.
    reindex_all=True: re-embeds every document including already-synced ones.

    Args:
        doc_id: UUID of a specific document to reindex (optional).
        reindex_all: Force reindex all documents, including already-synced ones.

    Returns:
        Plain-text summary of succeeded/failed counts and any errors.
    """
    lc = ctx.request_context.lifespan_context
    session_factory = lc["session_factory"]
    qdrant = lc["qdrant"]
    embedder = lc["embedder"]

    async with session_factory() as session:
        if doc_id is not None:
            doc = await DocumentRepository.get_by_id(session, UUID(doc_id))
            if doc is None:
                return f"Error: document not found: {doc_id}"
            docs = [doc]
        elif reindex_all:
            docs = await DocumentRepository.list_all(session)
        else:
            all_docs = await DocumentRepository.list_all(session)
            docs = [
                d for d in all_docs
                if d.sync_status in (SyncStatus.DIRTY, SyncStatus.FAILED)
            ]

        if not docs:
            return "No documents to reindex."

        succeeded = 0
        failed = 0
        errors: list[str] = []

        for doc in docs:
            doc_id_str = str(doc.document_id)
            label = doc.title or doc_id_str[:8]
            try:
                result = await ChunkManager.reindex_document(
                    session, qdrant, embedder, doc_id_str
                )
                if result.health_check_passed:
                    succeeded += 1
                else:
                    failed += 1
                    errors.append(
                        f"{label}: health check failed "
                        f"({result.succeeded}/{result.total} chunks synced)"
                    )
                for err in result.errors:
                    errors.append(f"{label}: {err}")
            except Exception as exc:
                failed += 1
                logger.error("Failed to reindex document %s: %s", doc_id_str, exc)
                errors.append(f"{label}: {exc}")

    lines = [f"Reindex complete: {succeeded} succeeded, {failed} failed."]
    if errors:
        lines.append("Errors:")
        lines.extend(f"  - {e}" for e in errors)
    return "\n".join(lines)
