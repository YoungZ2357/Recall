"""CLI docs subcommand: list and delete documents in the knowledge base."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated
from uuid import UUID

import typer
from rich.console import Console
from rich.table import Table

from app.cli._init_deps import init_deps, teardown_deps

logger = logging.getLogger(__name__)
console = Console()

docs_app = typer.Typer(help="Manage documents in the knowledge base.")


@docs_app.command("list")
def list_docs() -> None:
    """List all documents with their IDs and metadata."""
    asyncio.run(_run_list())


@docs_app.command("delete")
def delete_docs(
    doc_id: Annotated[
        str | None,
        typer.Option("--doc-id", help="Delete a specific document by UUID."),
    ] = None,
    title: Annotated[
        str | None,
        typer.Option("--title", help="Delete a document by exact title match."),
    ] = None,
    delete_all: Annotated[
        bool,
        typer.Option("--all", help="Delete all documents."),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompts."),
    ] = False,
) -> None:
    """Delete documents by ID, title, or delete all.

    Exactly one of --doc-id, --title, or --all must be provided.
    """
    provided = sum([doc_id is not None, title is not None, delete_all])
    if provided == 0:
        console.print("[red]Error:[/red] provide one of --doc-id, --title, or --all.")
        raise typer.Exit(1)
    if provided > 1:
        console.print("[red]Error:[/red] --doc-id, --title, and --all are mutually exclusive.")
        raise typer.Exit(1)

    asyncio.run(_run_delete(doc_id, title, delete_all, yes))


# ---------------------------------------------------------------------------
# Async implementations
# ---------------------------------------------------------------------------

async def _run_list() -> None:
    from app.config import settings
    from app.core.database import get_async_session
    from app.services import DocumentService

    _, qdrant, embedder, _ = await init_deps(settings)
    try:
        async with get_async_session() as session:
            docs = await DocumentService.list_all(session)

        if not docs:
            console.print("[yellow]No documents in the knowledge base.[/yellow]")
            return

        table = Table(title=f"Documents ({len(docs)} total)")
        table.add_column("#", style="dim", width=3)
        table.add_column("Document ID", style="cyan", width=36)
        table.add_column("Title", max_width=40)
        table.add_column("Source Path", style="dim", max_width=40)
        table.add_column("Status", width=8)
        table.add_column("Created At", width=19)

        for i, doc in enumerate(docs, start=1):
            table.add_row(
                str(i),
                str(doc.document_id),
                doc.title or "—",
                doc.source_path or "—",
                doc.sync_status.value if hasattr(doc.sync_status, "value") else doc.sync_status,
                doc.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            )

        console.print(table)

    finally:
        await teardown_deps(qdrant, embedder)


async def _run_delete(
    doc_id: str | None,
    title: str | None,
    delete_all: bool,
    yes: bool,
) -> None:
    from app.config import settings
    from app.core.database import get_async_session
    from app.core.exceptions import DocumentNotFoundError, VectorDBError
    from app.services import DocumentService

    _, qdrant, embedder, _ = await init_deps(settings)
    try:
        async with get_async_session() as session:
            if doc_id is not None:
                doc = await DocumentService.get_by_id(session, UUID(doc_id))
                if doc is None:
                    console.print(f"[red]Document not found:[/red] {doc_id}")
                    raise typer.Exit(1)
                targets = [doc]

            elif title is not None:
                all_docs = await DocumentService.list_all(session)
                targets = [d for d in all_docs if d.title == title]
                if not targets:
                    console.print(f"[red]No document found with title:[/red] {title!r}")
                    raise typer.Exit(1)
                if len(targets) > 1:
                    console.print(
                        f"[yellow]Multiple documents match title {title!r}:[/yellow]"
                    )
                    for d in targets:
                        console.print(f"  {d.document_id}  {d.title}")
                    console.print("Use [bold]--doc-id[/bold] to specify the exact document.")
                    raise typer.Exit(1)

            else:  # delete_all
                targets = await DocumentService.list_all(session)
                if not targets:
                    console.print("[yellow]No documents to delete.[/yellow]")
                    return

            # Confirmation
            if not yes:
                if delete_all:
                    console.print(
                        f"[bold red]This will delete all {len(targets)} document(s) "
                        "and their chunks.[/bold red]"
                    )
                else:
                    doc = targets[0]
                    console.print(
                        f"Delete [cyan]{doc.title or doc.document_id}[/cyan]? "
                        "This cannot be undone."
                    )
                confirm = typer.prompt("Type 'y' to confirm", default="n")
                if confirm.lower() != "y":
                    console.print("Aborted.")
                    raise typer.Exit(0)

            # Execute deletions
            success_count = 0
            for doc in targets:
                doc_id_str = str(doc.document_id)
                try:
                    await DocumentService.delete_document(session, qdrant, doc_id_str)
                    console.print(
                        f"[green]Deleted:[/green] {doc.title or doc_id_str}"
                    )
                    success_count += 1
                except DocumentNotFoundError:
                    console.print(
                        f"[yellow]Not found (already deleted?):[/yellow] {doc_id_str}"
                    )
                except VectorDBError as exc:
                    logger.error("VectorDB error deleting %s: %s", doc_id_str, exc)
                    console.print(
                        f"[red]Failed to delete[/red] {doc.title or doc_id_str}: {exc}"
                    )

            console.print(f"\nDone. {success_count}/{len(targets)} document(s) deleted.")

    finally:
        await teardown_deps(qdrant, embedder)
