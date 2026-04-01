"""CLI ingest subcommand: ingest a file or directory into the knowledge base."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn

from app.cli._init_deps import init_deps, teardown_deps
from app.ingestion.chunker import get_chunker
from app.ingestion.parser import BaseParser, _parser_registry, get_parser
from app.ingestion.pipeline import FailedIngest, IngestionPipeline

logger = logging.getLogger(__name__)
console = Console()

ingest_app = typer.Typer(help="Ingest documents into the knowledge base.")


@ingest_app.callback(invoke_without_command=True)
def ingest(
    path: Annotated[Path, typer.Argument(help="File or directory to ingest.")],
    pdf_parser: Annotated[
        str,
        typer.Option("--pdf-parser", help="PDF parser: pymupdf | marker | mineru"),
    ] = "pymupdf",
    strategy: Annotated[
        str,
        typer.Option("--strategy", "-s", help="Chunk strategy: recursive | fixed_count"),
    ] = "recursive",
    chunk_size: Annotated[
        int,
        typer.Option("--chunk-size", help="Target chunk size in characters (recursive only)."),
    ] = 512,
    chunk_overlap: Annotated[
        int,
        typer.Option("--chunk-overlap", help="Overlap between consecutive chunks (recursive only)."),
    ] = 64,
    contextualize: Annotated[
        bool,
        typer.Option("--contextualize", help="Generate document-level context per chunk via LLM before embedding."),
    ] = False,
    strip_tail: Annotated[
        bool,
        typer.Option("--strip-tail", help="Strip trailing references and appendix sections before chunking."),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompts."),
    ] = False,
) -> None:
    """Ingest a single file or all supported files in a directory."""
    asyncio.run(_run_ingest(path, pdf_parser, strategy, chunk_size, chunk_overlap, contextualize, strip_tail, yes))


async def _run_ingest(
    path: Path,
    pdf_parser: str,
    strategy: str,
    chunk_size: int,
    chunk_overlap: int,
    contextualize: bool = False,
    strip_tail: bool = False,
    yes: bool = False,
) -> None:
    from app.config import settings

    session_factory, qdrant, embedder, generator = await init_deps(settings)
    try:
        from app.ingestion.contextualizer import ContextGenerator
        from app.ingestion.tagger import AutoTagger

        tagger = AutoTagger(generator) if generator is not None else None

        # Resolve contextualizer: requires LLM + user confirmation
        contextualizer: ContextGenerator | None = None
        if contextualize:
            if generator is None:
                console.print(
                    "[yellow]--contextualize requires LLM_API_KEY to be configured. "
                    "Skipping context generation.[/yellow]"
                )
            else:
                if yes or typer.confirm(
                    "Contextualize will call LLM once per chunk. Continue?",
                    default=False,
                ):
                    contextualizer = ContextGenerator(generator)
                else:
                    console.print("[dim]Context generation skipped by user.[/dim]")

        # Build parser factory
        if pdf_parser == "marker":
            from app.ingestion.parsers.pdf import MarkerCliParser
            def parser_factory(p: Path) -> BaseParser:
                return MarkerCliParser() if p.suffix.lower() == ".pdf" else get_parser(p)
        elif pdf_parser == "mineru":
            from app.ingestion.parsers.pdf_mineru import MinerUParser
            def parser_factory(p: Path) -> BaseParser:
                return MinerUParser(api_key=settings.mineru_api_key) if p.suffix.lower() == ".pdf" else get_parser(p)
        else:
            parser_factory = get_parser

        kwargs = {}
        if strategy == "recursive":
            kwargs = {"chunk_size": chunk_size, "chunk_overlap": chunk_overlap}

        chunker = get_chunker(strategy, **kwargs)
        pipeline = IngestionPipeline(
            parser_factory=parser_factory,
            chunker=chunker,
            embedder=embedder,
            session_factory=session_factory,
            qdrant_service=qdrant,
            tagger=tagger,
            contextualizer=contextualizer,
            strip_tail=strip_tail,
        )

        if path.is_file():
            await _ingest_single(pipeline, path, contextualizer, strip_tail)

        elif path.is_dir():
            supported_exts = set(_parser_registry.keys())
            files = [
                f for f in sorted(path.rglob("*"))
                if f.is_file() and f.suffix.lower() in supported_exts
            ]

            if not files:
                console.print(
                    f"[yellow]No supported files found in {path}.[/yellow]\n"
                    f"Supported extensions: {sorted(supported_exts)}"
                )
                return

            await _ingest_batch(pipeline, files, contextualizer, strip_tail)

        else:
            console.print(f"[red]Path not found: {path}[/red]")
            raise typer.Exit(1)

    finally:
        await teardown_deps(qdrant, embedder, generator)


async def _ingest_single(
    pipeline: IngestionPipeline,
    path: Path,
    contextualizer: object | None,
    strip_tail: bool = False,
) -> None:
    """Ingest a single file with per-stage step indicator."""
    # Base stages: Parse, Chunk, Embed, Write = 4
    # +1 for Contextualize, +1 for Filter
    total_stages = 4 + (1 if contextualizer is not None else 0) + (1 if strip_tail else 0)
    stage_num = [0]

    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task_id = progress.add_task("Starting...", total=None)

        def on_stage(name: str) -> None:
            stage_num[0] += 1
            progress.update(
                task_id,
                description=f"[bold cyan][{stage_num[0]}/{total_stages}] {name}...[/bold cyan]",
            )

        try:
            doc = await pipeline.ingest(path, stage_callback=on_stage)
        except Exception as exc:
            console.print(f"[red]✗[/red] {path.name}: {exc}")
            raise typer.Exit(1) from exc

    filter_suffix = ""
    if strip_tail and pipeline.last_filter_result is not None:
        fr = pipeline.last_filter_result
        if fr.cut_point is not None:
            filter_suffix = f", stripped {fr.removed_chars:,} chars ({fr.cut_reason})"
        else:
            filter_suffix = ", no tail detected"

    console.print(
        f"[green]✓[/green] {path.name} → "
        f"doc_id={doc.document_id}, status={doc.sync_status.value}"
        f"{filter_suffix}"
    )


async def _ingest_batch(
    pipeline: IngestionPipeline,
    files: list[Path],
    contextualizer: object | None,
    strip_tail: bool = False,
) -> None:
    """Ingest multiple files with an outer document progress bar."""
    total_stages = 4 + (1 if contextualizer is not None else 0) + (1 if strip_tail else 0)
    succeeded: list = []
    failed: list[FailedIngest] = []

    with Progress(
        SpinnerColumn(),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("{task.description}"),
        console=console,
    ) as progress:
        overall = progress.add_task(f"Ingesting [dim]{files[0].parent}[/dim]", total=len(files))

        for path in files:
            stage_num = [0]

            def make_on_stage(captured: Path) -> object:
                def on_stage(name: str) -> None:
                    stage_num[0] += 1
                    progress.update(
                        overall,
                        description=(
                            f"[dim]{captured.name}[/dim] "
                            f"[{stage_num[0]}/{total_stages}] {name}..."
                        ),
                    )
                return on_stage

            t0 = time.monotonic()
            try:
                doc = await pipeline.ingest(path, stage_callback=make_on_stage(path))
                elapsed = time.monotonic() - t0
                succeeded.append(doc)
                progress.console.print(f"  [green]✓[/green] {path.name}  ({elapsed:.1f}s)")
            except Exception as exc:
                elapsed = time.monotonic() - t0
                logger.warning("Failed to ingest %s: %s", path, exc)
                failed.append(FailedIngest(file_path=path, error=str(exc)))
                progress.console.print(f"  [red]✗[/red] {path.name}: {exc}")

            progress.advance(overall)
            progress.update(overall, description="Ingesting")

    console.print(
        f"\nDone: [green]{len(succeeded)} succeeded[/green], "
        f"[red]{len(failed)} failed[/red]"
    )
    if failed:
        for f in failed:
            console.print(f"  [red]✗[/red] {f.file_path.name}: {f.error}")
