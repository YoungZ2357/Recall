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
    from app.core.repository import ChunkRepository, DocumentRepository
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
            doc_chunks: list[tuple[str, str | None, list]] = []  # (doc_id_str, source_path, chunks)
            total_chunk_count = 0
            for d in documents:
                chunks = await ChunkRepository.list_by_document_without_context(
                    session, d.document_id
                )
                if chunks:
                    # Snapshot chunk data to avoid lazy-load after session commit
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

        # Process each document
        succeeded_total = 0
        failed_total = 0

        for doc_id_str, source_path, chunk_snapshots in doc_chunks:
            # Re-parse document to get full text
            if not source_path or not Path(source_path).is_file():
                console.print(
                    f"[yellow]Skipping doc {doc_id_str}: source file not accessible "
                    f"({source_path})[/yellow]"
                )
                failed_total += len(chunk_snapshots)
                continue

            try:
                parser = get_parser(Path(source_path))
                parse_result = parser.parse(Path(source_path))
                document_text = parse_result.content
            except Exception as exc:
                console.print(
                    f"[yellow]Skipping doc {doc_id_str}: failed to re-parse "
                    f"({exc})[/yellow]"
                )
                failed_total += len(chunk_snapshots)
                continue

            # Generate context per chunk
            contexts = await ctx_gen.generate_batch(
                document_text,
                [cs["content"] for cs in chunk_snapshots],
            )

            # Write context + mark DIRTY, then re-embed
            async with session_factory() as session:
                # Batch update context field
                updates = [
                    (cs["chunk_id"], ctx)
                    for cs, ctx in zip(chunk_snapshots, contexts)
                    if ctx is not None
                ]
                if updates:
                    await ChunkRepository.bulk_update_context(
                        session, updates, SyncStatus.DIRTY
                    )
                    await session.commit()

                # Re-embed all chunks that got context
                from datetime import datetime, timezone

                embed_items = [
                    (cs, ctx)
                    for cs, ctx in zip(chunk_snapshots, contexts)
                    if ctx is not None
                ]
                if not embed_items:
                    console.print(
                        f"[yellow]Doc {doc_id_str}: all LLM calls failed, skipping re-embed.[/yellow]"
                    )
                    failed_total += len(chunk_snapshots)
                    continue

                embed_texts = [
                    ctx + "\n\n" + cs["content"] for cs, ctx in embed_items
                ]
                try:
                    vectors = await embedder.embed_batch(embed_texts)
                except Exception as exc:
                    console.print(
                        f"[red]Doc {doc_id_str}: embedding failed ({exc})[/red]"
                    )
                    failed_total += len(embed_items)
                    continue

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
                    console.print(
                        f"[red]Doc {doc_id_str}: Qdrant upsert failed ({exc})[/red]"
                    )
                    failed_total += len(embed_items)
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
                skipped = len(chunk_snapshots) - len(embed_items)
                if skipped:
                    failed_total += skipped

            console.print(
                f"  [green]✓[/green] doc {doc_id_str}: "
                f"{len(embed_items)}/{len(chunk_snapshots)} chunks contextualized"
            )

        console.print(
            f"\n[bold]Done:[/bold] [green]{succeeded_total} succeeded[/green], "
            f"[red]{failed_total} failed[/red]"
        )

    finally:
        await teardown_deps(qdrant, embedder, generator)
