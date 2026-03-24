"""CLI search subcommand: search the knowledge base."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from app.cli._init_deps import init_deps, teardown_deps

logger = logging.getLogger(__name__)
console = Console()

search_app = typer.Typer(help="Search the knowledge base.")


@search_app.callback(invoke_without_command=True)
def search(
    query: Annotated[str, typer.Argument(help="Search query text.")],
    top_k: Annotated[int, typer.Option("--top-k", "-k", help="Number of results.")] = 5,
    mode: Annotated[
        str,
        typer.Option("--mode", "-m", help="Retention mode: prefer_recent | awaken_forgotten"),
    ] = "prefer_recent",
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Show detailed score breakdown."),
    ] = False,
) -> None:
    """Search the knowledge base and display ranked results."""
    asyncio.run(_run_search(query, top_k, mode, verbose))


async def _run_search(
    query: str,
    top_k: int,
    mode: str,
    verbose: bool,
) -> None:
    from app.config import settings

    from app.retrieval.pipeline import RetrievalPipeline
    from app.retrieval.reranker import Reranker
    from app.retrieval.searcher import BM25Searcher, VectorSearcher

    session_factory, qdrant, embedder, _ = await init_deps(settings)
    try:
        vector_searcher = VectorSearcher(qdrant, embedder)
        bm25_searcher = BM25Searcher(session_factory)
        reranker = Reranker(embedder, settings)
        pipeline = RetrievalPipeline(
            vector_searcher=vector_searcher,
            bm25_searcher=bm25_searcher,
            reranker=reranker,
            embedder=embedder,
            session_factory=session_factory,
            settings=settings,
        )

        results = await pipeline.search(
            query_text=query,
            top_k=top_k,
            retention_mode=mode,  # type: ignore[arg-type]
        )

        if not results:
            console.print("[yellow]No results found.[/yellow]")
            return

        table = Table(title=f"Search Results — \"{query}\"")
        table.add_column("#", style="dim", width=3)
        table.add_column("Score", justify="right", width=8)
        table.add_column("Document", style="cyan", max_width=30)
        table.add_column("Content", max_width=80)

        if verbose:
            table.add_column("Retrieval", justify="right", width=9)
            table.add_column("Metadata", justify="right", width=9)
            table.add_column("Retention", justify="right", width=9)
            table.add_column("Chunk ID", style="dim", width=36)

        for i, r in enumerate(results, start=1):
            content_preview = r.content[:120].replace("\n", " ")
            if len(r.content) > 120:
                content_preview += "..."

            row = [
                str(i),
                f"{r.final_score:.4f}",
                r.document_title or "—",
                content_preview,
            ]

            if verbose:
                row.extend([
                    f"{r.retrieval_score:.4f}",
                    f"{r.metadata_score:.4f}",
                    f"{r.retention_score:.4f}",
                    str(r.chunk_id),
                ])

            table.add_row(*row)

        console.print(table)

    finally:
        await teardown_deps(qdrant, embedder)
