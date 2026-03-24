"""CLI reindex subcommand: re-embed documents after an embedding model change."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Optional
from uuid import UUID

import typer
from rich.console import Console
from rich.table import Table

from app.cli._init_deps import init_deps, teardown_deps
from app.core.chunk_manager import ChunkManager
from app.core.models import SyncStatus
from app.core.repository import DocumentRepository

logger = logging.getLogger(__name__)
console = Console()

reindex_app = typer.Typer(help="Re-embed documents after an embedding model change.")


@reindex_app.callback(invoke_without_command=True)
def reindex(
    doc_id: Annotated[
        Optional[str],
        typer.Option("--doc-id", help="Reindex a specific document by UUID."),
    ] = None,
    force_all: Annotated[
        bool,
        typer.Option("--all/--no-all", help="Force reindex all documents, including synced."),
    ] = False,
) -> None:
    """Re-embed documents.

    Default (no flags): processes all DIRTY and FAILED documents.
    --doc-id: processes a single document regardless of status.
    --all: processes every document, including already-synced ones.

    Note: FAILED documents may fail during reindex because the state machine
    does not allow a direct FAILED → DIRTY transition. Use --doc-id for
    targeted investigation of individual FAILED documents.
    """
    asyncio.run(_run_reindex(doc_id, force_all))


async def _run_reindex(doc_id: Optional[str], force_all: bool) -> None:
    from app.config import settings

    session_factory, qdrant, embedder = await init_deps(settings)
    try:
        async with session_factory() as session:
            # Determine target documents
            if doc_id:
                doc = await DocumentRepository.get_by_id(session, UUID(doc_id))
                if doc is None:
                    console.print(f"[red]Document not found: {doc_id}[/red]")
                    raise typer.Exit(1)
                docs = [doc]

            elif force_all:
                docs = await DocumentRepository.list_all(session)

            else:
                # Default: DIRTY + FAILED
                all_docs = await DocumentRepository.list_all(session)
                docs = [
                    d for d in all_docs
                    if d.sync_status in (SyncStatus.DIRTY, SyncStatus.FAILED)
                ]

            if not docs:
                console.print("[yellow]No documents to reindex.[/yellow]")
                return

            console.print(f"Reindexing [bold]{len(docs)}[/bold] document(s)...")

            table = Table(title="Reindex Results")
            table.add_column("Title", style="cyan", max_width=40)
            table.add_column("Status", style="dim")
            table.add_column("Total", justify="right")
            table.add_column("OK", style="green", justify="right")
            table.add_column("Fail", style="red", justify="right")
            table.add_column("Health", justify="center")

            for doc in docs:
                doc_id_str = str(doc.document_id)
                prev_status = doc.sync_status.value
                try:
                    result = await ChunkManager.reindex_document(
                        session, qdrant, embedder, doc_id_str
                    )
                    health = "[green]✓[/green]" if result.health_check_passed else "[red]✗[/red]"
                    table.add_row(
                        doc.title,
                        prev_status,
                        str(result.total),
                        str(result.succeeded),
                        str(result.failed),
                        health,
                    )
                    if result.errors:
                        for err in result.errors:
                            logger.warning("Reindex error for %s: %s", doc_id_str, err)
                        console.print(
                            f"  [yellow]Warnings for '{doc.title}':[/yellow] "
                            + "; ".join(result.errors)
                        )
                except Exception as exc:
                    logger.error("Failed to reindex document %s: %s", doc_id_str, exc)
                    table.add_row(
                        doc.title,
                        prev_status,
                        "-",
                        "-",
                        "-",
                        f"[red]ERR[/red]",
                    )
                    console.print(f"  [red]Error reindexing '{doc.title}':[/red] {exc}")

            console.print(table)

    finally:
        await teardown_deps(qdrant, embedder)
