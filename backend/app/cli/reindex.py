"""CLI reindex subcommand: re-embed documents after an embedding model change."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Optional
from uuid import UUID

import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn

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

    from app.core.database import get_async_session

    _, qdrant, embedder, _ = await init_deps(settings)
    try:
        async with get_async_session() as session:
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
                all_docs = await DocumentRepository.list_all(session)
                docs = [
                    d for d in all_docs
                    if d.sync_status in (SyncStatus.DIRTY, SyncStatus.FAILED)
                ]

            if not docs:
                console.print("[yellow]No documents to reindex.[/yellow]")
                return

            succeeded_count = 0
            failed_count = 0

            with Progress(
                SpinnerColumn(),
                BarColumn(),
                MofNCompleteColumn(),
                TextColumn("{task.description}"),
                console=console,
            ) as progress:
                doc_task = progress.add_task("Reindexing", total=len(docs))
                chunk_task = progress.add_task("", total=1, visible=False)

                for doc in docs:
                    doc_id_str = str(doc.document_id)
                    doc_label = doc.title or doc_id_str[:8]

                    progress.update(
                        doc_task,
                        description=f"Reindexing  [dim]{doc_label}[/dim]",
                    )

                    def make_chunk_callback(task_id: int, label: str) -> object:
                        def on_chunk(current: int, total: int) -> None:
                            progress.update(
                                task_id,
                                completed=current,
                                total=total,
                                visible=True,
                                description=f"  [dim]{label}[/dim]  {current}/{total} chunks",
                            )
                        return on_chunk

                    try:
                        result = await ChunkManager.reindex_document(
                            session,
                            qdrant,
                            embedder,
                            doc_id_str,
                            chunk_callback=make_chunk_callback(chunk_task, doc_label),
                        )
                        progress.update(chunk_task, visible=False)

                        if result.health_check_passed:
                            succeeded_count += 1
                            progress.console.print(
                                f"  [green]✓[/green] {doc_label}  "
                                f"{result.succeeded}/{result.total} chunks"
                            )
                        else:
                            failed_count += 1
                            progress.console.print(
                                f"  [red]✗[/red] {doc_label}  "
                                f"{result.succeeded}/{result.total} chunks (health check failed)"
                            )

                        for err in result.errors:
                            logger.warning("Reindex error for %s: %s", doc_id_str, err)
                            progress.console.print(f"    [yellow]⚠[/yellow] {err}")

                    except Exception as exc:
                        progress.update(chunk_task, visible=False)
                        failed_count += 1
                        logger.error("Failed to reindex document %s: %s", doc_id_str, exc)
                        progress.console.print(f"  [red]✗[/red] {doc_label}: {exc}")

                    progress.advance(doc_task)

            console.print(
                f"\nDone: [green]{succeeded_count} succeeded[/green], "
                f"[red]{failed_count} failed[/red]"
            )

    finally:
        await teardown_deps(qdrant, embedder)
