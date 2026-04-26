"""MCP stdio server — exposes Recall retrieval tools to MCP clients.

Run with:
    python -m app.mcp
"""

import json
import logging
from contextlib import asynccontextmanager

from mcp.server.fastmcp import Context, FastMCP

from app.cli._init_deps import AppResources, init_deps, teardown_deps
from app.config import settings
from app.services import DocumentService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan: initialize shared deps once for the server process lifetime
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(server: FastMCP):  # noqa: ARG001
    resources = await init_deps(settings)
    try:
        yield resources
    finally:
        await teardown_deps(resources)


mcp = FastMCP("Recall", lifespan=lifespan)


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
    resources: AppResources = ctx.request_context.lifespan_context
    results = await resources.search_service.search(
        query_text=query,
        top_k=top_k,
        retention_mode=mode,
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
    resources: AppResources = ctx.request_context.lifespan_context
    if resources.generation_service is None:
        return "Error: LLM generator not available. Set LLM_API_KEY to enable generation."

    results, response = await resources.generation_service.search_and_generate(
        query=query,
        top_k=top_k,
        mode=mode,
    )
    return response.answer


@mcp.tool()
async def list_documents(ctx: Context) -> str:
    """List all documents in the knowledge base.

    Returns:
        JSON array of documents. Each item contains document_id, title,
        source_path, sync_status, and created_at (ISO 8601).
    """
    resources: AppResources = ctx.request_context.lifespan_context

    async with resources.session_factory() as session:
        docs = await DocumentService.list_all(session)
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
    resources: AppResources = lc
    svc = resources.reindex_service

    if doc_id is not None:
        try:
            result = await svc.reindex_document(doc_id)
        except Exception as exc:
            logger.error("Failed to reindex document %s: %s", doc_id, exc)
            return f"Reindex failed: {exc}"

        if result.health_check_passed:
            return "Reindex complete: 1 succeeded, 0 failed."

        lines = ["Reindex complete: 0 succeeded, 1 failed."]
        lines.append("Errors:")
        for err in result.errors:
            lines.append(f"  - {err}")
        return "\n".join(lines)

    if reindex_all:
        results = await svc.reindex_all()
    else:
        results = await svc.reindex_dirty()

    if not results:
        return "No documents to reindex."

    succeeded = sum(1 for r in results if r.health_check_passed)
    failed = sum(1 for r in results if not r.health_check_passed)
    errors: list[str] = []
    for r in results:
        if not r.health_check_passed:
            label = f"[{r.succeeded}/{r.total} chunks]"
            errors.append(f"health check failed {label}")
        errors.extend(r.errors)

    lines = [f"Reindex complete: {succeeded} succeeded, {failed} failed."]
    if errors:
        lines.append("Errors:")
        lines.extend(f"  - {e}" for e in errors)
    return "\n".join(lines)
