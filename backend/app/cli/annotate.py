"""CLI annotate subcommand: manually annotate chunks for evaluation."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Annotated, Optional
from uuid import UUID

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from app.cli._init_deps import init_deps, teardown_deps

logger = logging.getLogger(__name__)
console = Console()

annotate_app = typer.Typer(help="Manually annotate chunks for evaluation.")

_VALID_QUERY_TYPES = {"factual", "comparative", "structural"}
_CONTENT_PREVIEW_LIMIT = 500


@annotate_app.callback(invoke_without_command=True)
def annotate(
    doc_id: Annotated[str, typer.Argument(help="Document UUID to annotate.")],
    output: Annotated[
        Optional[str],
        typer.Option("--output", "-o", help="Output JSON file path."),
    ] = None,
) -> None:
    """Browse chunks of a document and build a manual evaluation set."""
    asyncio.run(_run_annotate(doc_id, output))


async def _run_annotate(doc_id: str, output_path: Optional[str]) -> None:
    from app.config import settings
    from app.core.chunk_manager import ChunkManager
    from app.core.repository import ChunkRepository, DocumentRepository

    session_factory, qdrant, embedder, generator = await init_deps(settings)
    try:
        async with session_factory() as session:
            # Validate document exists
            try:
                doc_uuid = UUID(doc_id)
            except ValueError:
                console.print(f"[red]Error: '{doc_id}' is not a valid UUID.[/red]")
                raise typer.Exit(1)

            doc = await DocumentRepository.get_by_id(session, doc_uuid)
            if doc is None:
                console.print(f"[red]Error: Document '{doc_id}' not found.[/red]")
                raise typer.Exit(1)

            chunks = await ChunkRepository.list_by_document(session, doc_uuid)
            if not chunks:
                console.print(f"[yellow]Document '{doc_id}' has no chunks.[/yellow]")
                raise typer.Exit(0)

            # Resolve output path
            out_file = Path(output_path) if output_path else Path(f"eval_manual_{doc_id[:8]}.json")
            if out_file.exists():
                console.print(f"[yellow]Warning: '{out_file}' already exists and will be overwritten.[/yellow]")

            console.print(f"\n[bold]Document:[/bold] {doc.title or doc_id}")
            console.print(f"[bold]Chunks:[/bold] {len(chunks)}")
            console.print(f"[bold]Output:[/bold] {out_file}\n")

            # Interactive annotation loop
            annotations: list[dict] = []
            stats = {"annotated": 0, "deleted": 0, "skipped": 0}
            position = 0

            while True:
                chunk = chunks[position]
                content = chunk.content or ""
                preview = content[:_CONTENT_PREVIEW_LIMIT]
                suffix = f"... ({len(content)} chars)" if len(content) > _CONTENT_PREVIEW_LIMIT else ""

                tags_display = ", ".join(json.loads(chunk.tags)) if chunk.tags else "(none)"
                panel_content = (
                    f"[dim]tags:[/dim] {tags_display}\n\n"
                    f"{preview}{suffix}"
                )
                console.print(
                    Panel(
                        panel_content,
                        title=f"Chunk {position + 1}/{len(chunks)}  chunk_index={chunk.chunk_index}",
                        title_align="left",
                    )
                )
                console.print("  [a] Add query  [d] Delete chunk  [n] Next  [b] Back  [q] Save & quit")

                action = Prompt.ask("Action", default="n").strip().lower()

                if action == "a":
                    # Sub-loop: add one or more queries
                    added_this_round = 0
                    while True:
                        qt = Prompt.ask(
                            "query_type [factual/comparative/structural]",
                            default="factual",
                        ).strip().lower()
                        if qt not in _VALID_QUERY_TYPES:
                            console.print(f"[red]Invalid query_type '{qt}'. Choose from: factual, comparative, structural.[/red]")
                            continue

                        query_text = Prompt.ask("query (empty line to finish)").strip()
                        if not query_text:
                            break

                        annotations.append({
                            "query": query_text,
                            "ground_truth_chunk_ids": [str(chunk.chunk_id)],
                            "source_document_id": str(doc_uuid),
                            "metadata": {
                                "query_type": qt,
                                "generator_model": "human",
                            },
                        })
                        added_this_round += 1
                        stats["annotated"] += 1
                        console.print(f"[green]Added (total: {len(annotations)})[/green]")

                    if added_this_round == 0:
                        console.print("[dim]No queries added.[/dim]")

                elif action == "d":
                    confirm = Prompt.ask(
                        f"Warning: confirm delete chunk (index={chunk.chunk_index})? Irreversible [y/N]",
                        default="N",
                    ).strip().lower()
                    if confirm == "y":
                        await ChunkManager.delete_chunk(session, qdrant, str(chunk.chunk_id))
                        chunks.pop(position)
                        stats["deleted"] += 1
                        console.print(f"[yellow]Chunk deleted. Remaining: {len(chunks)}[/yellow]")

                        if not chunks:
                            console.print("[yellow]All chunks deleted.[/yellow]")
                            break

                        position = min(position, len(chunks) - 1)
                    else:
                        console.print("[dim]Delete cancelled.[/dim]")

                elif action == "n":
                    if position >= len(chunks) - 1:
                        console.print("[dim]Already at last chunk. [q] to quit or [b] to go back.[/dim]")
                    else:
                        position += 1
                        stats["skipped"] += 1

                elif action == "b":
                    if position <= 0:
                        console.print("[dim]Already at first chunk.[/dim]")
                    else:
                        position -= 1

                elif action == "q":
                    break

                else:
                    console.print("[red]Invalid input. Use a / d / n / b / q.[/red]")

            # Save output
            _save_output(annotations, stats, out_file)

    finally:
        await teardown_deps(qdrant, embedder, generator)


def _save_output(
    annotations: list[dict],
    stats: dict,
    out_file: Path,
) -> None:
    """Write annotations to JSON and print summary."""
    if annotations:
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(
            json.dumps(annotations, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        console.print(
            f"\n[green]Saved: {out_file}[/green]  "
            f"annotated: {stats['annotated']} | "
            f"deleted: {stats['deleted']} chunks | "
            f"skipped: {stats['skipped']} chunks"
        )
    elif stats["deleted"] > 0:
        console.print(
            f"\n[yellow]No queries annotated. {stats['deleted']} chunk(s) deleted. No file written.[/yellow]"
        )
    else:
        console.print("\n[yellow]No queries annotated. No file written.[/yellow]")
