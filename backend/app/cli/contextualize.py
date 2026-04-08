"""CLI contextualize subcommand: generate document-level context for existing chunks."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Annotated
from uuid import UUID

import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn

from app.cli._init_deps import init_deps, teardown_deps

logger = logging.getLogger(__name__)
console = Console()

contextualize_app = typer.Typer(help="Generate document-level context for chunks via LLM.")


@contextualize_app.callback(invoke_without_command=True)
def contextualize(
    doc_id: Annotated[
        str | None,
        typer.Option("--doc-id", help="Document UUID to contextualize."),
    ] = None,
    all_docs: Annotated[
        bool,
        typer.Option("--all", help="Contextualize all documents."),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompts."),
    ] = False,
) -> None:
    """Generate document-level context for chunks that lack it, then re-embed."""
    if not doc_id and not all_docs:
        console.print("[red]Must specify --doc-id or --all.[/red]")
        raise typer.Exit(1)
    if doc_id and all_docs:
        console.print("[red]--doc-id and --all are mutually exclusive.[/red]")
        raise typer.Exit(1)

    asyncio.run(_run_contextualize(doc_id, all_docs, yes))


async def _run_contextualize(
    doc_id: str | None,
    all_docs: bool,
    yes: bool,
) -> None:
    from qdrant_client.models import PointStruct

    from app.config import settings
    from app.core.models import SyncStatus
    from app.core.repository import ChunkRepository, DocumentRepository, FTSRepository
    from app.ingestion.contextualizer import ContextGenerator
    from app.ingestion.parser import get_parser

    session_factory, qdrant, embedder, generator = await init_deps(settings)
    try:
        if generator is None:
            console.print("[red]LLM_API_KEY is not configured. Cannot generate context.[/red]")
            raise typer.Exit(1)

        ctx_gen = ContextGenerator(generator)

        # Resolve target documents
        async with session_factory() as session:
            if all_docs:
                documents = await DocumentRepository.list_all(session)
            else:
                doc = await DocumentRepository.get_by_id(session, UUID(doc_id))  # type: ignore[arg-type]
                documents = [doc] if doc else []
                if not doc:
                    console.print(f"[red]Document {doc_id} not found.[/red]")
                    raise typer.Exit(1)

            # Collect chunks without context across all target documents
            doc_chunks: list[tuple[str, str | None, list]] = []
            total_chunk_count = 0
            for d in documents:
                chunks = await ChunkRepository.list_by_document_without_context(
                    session, d.document_id
                )
                if chunks:
                    chunk_snapshots = [
                        {
                            "chunk_id": c.chunk_id,
                            "chunk_index": c.chunk_index,
                            "content": c.content,
                            "tags": json.loads(c.tags) if c.tags else [],
                        }
                        for c in chunks
                    ]
                    doc_chunks.append((str(d.document_id), d.source_path, chunk_snapshots))
                    total_chunk_count += len(chunks)

        if total_chunk_count == 0:
            console.print("[green]All chunks already have context. Nothing to do.[/green]")
            return

        # User confirmation
        if not yes:
            if not typer.confirm(
                f"将为 {total_chunk_count} 个 chunk 生成上下文"
                f"（预计 {total_chunk_count} 次 LLM 调用）。继续？",
                default=False,
            ):
                console.print("[dim]Aborted by user.[/dim]")
                return

        # Process each document with dual-layer progress
        succeeded_total = 0
        failed_total = 0

        with Progress(
            SpinnerColumn(),
            BarColumn(),
            MofNCompleteColumn(),
            TextColumn("{task.description}"),
            console=console,
        ) as progress:
            doc_task = progress.add_task("Contextualizing", total=len(doc_chunks))
            chunk_task = progress.add_task("", total=1, visible=False)

            for doc_id_str, source_path, chunk_snapshots in doc_chunks:
                doc_name = Path(source_path).name if source_path else doc_id_str
                n_chunks = len(chunk_snapshots)

                progress.update(
                    doc_task,
                    description=f"Contextualizing  [dim]current: {doc_name}[/dim]",
                )

                # Re-parse document to get full text
                if not source_path or not Path(source_path).is_file():
                    progress.console.print(
                        f"  [yellow]⚠[/yellow] {doc_name}: source file not accessible "
                        f"({source_path})"
                    )
                    failed_total += n_chunks
                    progress.advance(doc_task)
                    continue

                try:
                    parser = get_parser(Path(source_path))
                    parse_result = parser.parse(Path(source_path))
                    document_text = parse_result.content
                except Exception as exc:
                    progress.console.print(
                        f"  [yellow]⚠[/yellow] {doc_name}: failed to re-parse ({exc})"
                    )
                    failed_total += n_chunks
                    progress.advance(doc_task)
                    continue

                # Show inner chunk progress
                progress.update(
                    chunk_task,
                    total=n_chunks,
                    completed=0,
                    visible=True,
                    description=f"  [dim]{doc_name}[/dim]",
                )

                def make_chunk_callback(task_id: int) -> object:
                    def on_chunk(current: int, total: int) -> None:
                        progress.update(task_id, completed=current, total=total)
                    return on_chunk

                # Generate context per chunk
                contexts = await ctx_gen.generate_batch(
                    document_text,
                    [cs["content"] for cs in chunk_snapshots],
                    chunk_callback=make_chunk_callback(chunk_task),
                )

                progress.update(chunk_task, visible=False)

                # Write context + mark DIRTY, then re-embed
                async with session_factory() as session:
                    updates = [
                        (cs["chunk_id"], ctx)
                        for cs, ctx in zip(chunk_snapshots, contexts)
                        if ctx is not None
                    ]
                    if updates:
                        await ChunkRepository.bulk_update_context(
                            session, updates, SyncStatus.DIRTY
                        )
                        # Sync updated context to FTS index; use INSERT OR REPLACE
                        # to handle chunks being re-contextualized.
                        doc_id_map: dict[str, UUID] = {
                            str(cs["chunk_id"]): UUID(doc_id_str)
                            for cs in chunk_snapshots
                        }
                        content_map: dict[str, str] = {
                            str(cs["chunk_id"]): cs["content"]
                            for cs in chunk_snapshots
                        }
                        fts_items = [
                            (chunk_id, doc_id_map[str(chunk_id)], ctx, content_map[str(chunk_id)])
                            for chunk_id, ctx in updates
                        ]
                        await FTSRepository.context_bulk_insert_raw(session, fts_items)
                        await session.commit()

                    embed_items = [
                        (cs, ctx)
                        for cs, ctx in zip(chunk_snapshots, contexts)
                        if ctx is not None
                    ]
                    if not embed_items:
                        progress.console.print(
                            f"  [yellow]⚠[/yellow] {doc_name}: all LLM calls failed, skipping re-embed"
                        )
                        failed_total += n_chunks
                        progress.advance(doc_task)
                        continue

                    embed_texts = [
                        ctx + "\n\n" + cs["content"] for cs, ctx in embed_items
                    ]
                    try:
                        vectors = await embedder.embed_batch(embed_texts)
                    except Exception as exc:
                        progress.console.print(
                            f"  [red]✗[/red] {doc_name}: embedding failed ({exc})"
                        )
                        failed_total += len(embed_items)
                        progress.advance(doc_task)
                        continue

                    from datetime import datetime, timezone

                    now_iso = datetime.now(timezone.utc).isoformat()
                    points = [
                        PointStruct(
                            id=str(cs["chunk_id"]),
                            vector=vector,
                            payload={
                                "document_id": doc_id_str,
                                "chunk_index": cs["chunk_index"],
                                "tags": cs["tags"],
                                "created_at": now_iso,
                            },
                        )
                        for (cs, _ctx), vector in zip(embed_items, vectors)
                    ]

                    try:
                        await qdrant.upsert(points)
                    except Exception as exc:
                        progress.console.print(
                            f"  [red]✗[/red] {doc_name}: Qdrant upsert failed ({exc})"
                        )
                        failed_total += len(embed_items)
                        progress.advance(doc_task)
                        continue

                    # Mark SYNCED + context_embedded=True
                    from sqlalchemy import update as sa_update

                    from app.core.models import Chunk

                    embed_chunk_ids = [cs["chunk_id"] for cs, _ in embed_items]
                    await session.execute(
                        sa_update(Chunk)
                        .where(Chunk.chunk_id.in_(embed_chunk_ids))
                        .values(
                            sync_status=SyncStatus.SYNCED,
                            context_embedded=True,
                        )
                    )
                    await session.commit()

                    succeeded_total += len(embed_items)
                    skipped = n_chunks - len(embed_items)
                    if skipped:
                        failed_total += skipped

                progress.console.print(
                    f"  [green]✓[/green] {doc_name}  "
                    f"{len(embed_items)}/{n_chunks} chunks contextualized"
                )
                progress.advance(doc_task)

        console.print(
            f"\n[bold]Done:[/bold] [green]{succeeded_total} succeeded[/green], "
            f"[red]{failed_total} failed[/red]"
        )

    finally:
        await teardown_deps(qdrant, embedder, generator)
