"""CLI retag subcommand: auto-tag documents whose chunks have no tags."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn

from app.cli._init_deps import init_deps, teardown_deps

logger = logging.getLogger(__name__)
console = Console()

retag_app = typer.Typer(help="Auto-tag documents that currently have no tags.")


@retag_app.callback(invoke_without_command=True)
def retag(
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompt."),
    ] = False,
) -> None:
    """Find documents with no tags on any chunk and run auto-tagger on them."""
    asyncio.run(_run_retag(yes))


async def _run_retag(yes: bool) -> None:
    from app.config import settings
    from app.core.repository import ChunkRepository, DocumentRepository
    from app.ingestion.tagger import AutoTagger

    session_factory, qdrant, embedder, generator = await init_deps(settings)
    try:
        if generator is None:
            console.print("[red]LLM_API_KEY is not configured. Cannot run auto-tagger.[/red]")
            raise typer.Exit(1)

        tagger = AutoTagger(generator)

        # Collect untagged documents with their titles
        async with session_factory() as session:
            untagged_ids = await ChunkRepository.get_untagged_document_ids(session)
            if not untagged_ids:
                console.print("[green]All documents already have tags. Nothing to do.[/green]")
                return

            # Fetch titles for display
            doc_map: dict = {}
            for doc_id in untagged_ids:
                doc = await DocumentRepository.get_by_id(session, doc_id)
                if doc:
                    doc_map[doc_id] = doc.title or str(doc_id)

        console.print(f"Found [bold]{len(untagged_ids)}[/bold] untagged document(s):")
        for _doc_id, title in doc_map.items():
            console.print(f"  [dim]{title}[/dim]")

        if not yes:
            if not typer.confirm(f"\nRun auto-tagger on {len(untagged_ids)} document(s)?", default=False):  # noqa: E501
                console.print("[dim]Aborted by user.[/dim]")
                return

        succeeded = 0
        failed = 0

        with Progress(
            SpinnerColumn(),
            BarColumn(),
            MofNCompleteColumn(),
            TextColumn("{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Tagging", total=len(untagged_ids))

            for doc_id in untagged_ids:
                title = doc_map.get(doc_id, str(doc_id))
                progress.update(task, description=f"Tagging  [dim]{title}[/dim]")

                async with session_factory() as session:
                    # Reconstruct document text from chunks in order
                    chunks = await ChunkRepository.list_by_document(session, doc_id)
                    if not chunks:
                        progress.console.print(f"  [yellow]⚠[/yellow] {title}: no chunks found, skipping")  # noqa: E501
                        failed += 1
                        progress.advance(task)
                        continue

                    content = "\n".join(c.content for c in chunks)
                    chunk_ids = [str(c.chunk_id) for c in chunks]

                    # Call auto-tagger (truncates internally to 8000 chars)
                    tags = await tagger.tag(content, session)

                if not tags:
                    progress.console.print(f"  [yellow]⚠[/yellow] {title}: tagger returned no tags, skipping")  # noqa: E501
                    failed += 1
                    progress.advance(task)
                    continue

                # Update SQLite
                async with session_factory() as session:
                    await ChunkRepository.bulk_update_tags(session, doc_id, tags)
                    await session.commit()

                # Update Qdrant payload
                try:
                    await qdrant.set_payload_for_points({"tags": tags}, chunk_ids)
                except Exception as exc:
                    progress.console.print(
                        f"  [yellow]⚠[/yellow] {title}: Qdrant payload update failed ({exc}). "
                        "SQLite updated; run reindex to sync."
                    )
                    # SQLite is source of truth — treat as partial success
                    succeeded += 1
                    progress.advance(task)
                    continue

                progress.console.print(f"  [green]✓[/green] {title}: {tags}")
                succeeded += 1
                progress.advance(task)

        console.print(
            f"\n[bold]Done:[/bold] [green]{succeeded} succeeded[/green], "
            f"[red]{failed} failed[/red]"
        )

    finally:
        await teardown_deps(qdrant, embedder, generator)
