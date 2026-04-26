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
    ] = "mineru",
    strategy: Annotated[
        str,
        typer.Option("--strategy", "-s", help="Chunk strategy: recursive | fixed_count"),
    ] = "recursive",
    chunk_size: Annotated[
        int,
        typer.Option("--chunk-size", help="Target chunk size in characters (recursive only)."),
    ] = 768,
    chunk_overlap: Annotated[
        int,
        typer.Option("--chunk-overlap", help="Overlap between consecutive chunks (recursive only)."),  # noqa: E501
    ] = 96,
    contextualize: Annotated[
        bool,
        typer.Option("--contextualize/--no-contextualize", help="Generate document-level context per chunk via LLM before embedding."),  # noqa: E501
    ] = True,
    strip_tail: Annotated[
        bool,
        typer.Option("--strip-tail", help="Strip trailing references and appendix sections before chunking."),  # noqa: E501
    ] = False,
    strip_markdown: Annotated[
        bool,
        typer.Option("--strip-markdown/--no-strip-markdown", help="Remove reference/appendix sections by Markdown heading structure (surgical multi-range removal). Takes priority over --strip-tail when both are set."),  # noqa: E501
    ] = True,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompts."),
    ] = False,
    concurrency: Annotated[
        int,
        typer.Option("--concurrency", "-c", help="Number of documents to ingest concurrently (batch mode only)."),  # noqa: E501
    ] = 4,
) -> None:
    """Ingest a single file or all supported files in a directory."""
    asyncio.run(_run_ingest(
        path, pdf_parser, strategy, chunk_size, chunk_overlap,
        contextualize, strip_tail, strip_markdown, yes, concurrency,
    ))


async def _run_ingest(
    path: Path,
    pdf_parser: str,
    strategy: str,
    chunk_size: int,
    chunk_overlap: int,
    contextualize: bool = False,
    strip_tail: bool = False,
    strip_markdown: bool = False,
    yes: bool = False,
    concurrency: int = 1,
) -> None:
    from app.config import settings

    resources = await init_deps(settings)
    try:
        from app.ingestion.contextualizer import ContextGenerator
        from app.ingestion.tagger import AutoTagger

        tagger = AutoTagger(resources.generator) if resources.generator is not None else None

        # Resolve contextualizer: requires LLM + user confirmation
        contextualizer: ContextGenerator | None = None
        if contextualize:
            if resources.generator is None:
                console.print(
                    "[yellow]--contextualize requires LLM_API_KEY to be configured. "
                    "Skipping context generation.[/yellow]"
                )
            else:
                if yes or typer.confirm(
                    "Contextualize will call LLM once per chunk. Continue?",
                    default=False,
                ):
                    contextualizer = ContextGenerator(resources.generator)
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
                return (
                    MinerUParser(api_key=settings.mineru_api_key)
                    if p.suffix.lower() == ".pdf"
                    else get_parser(p)
                )
        else:
            parser_factory = get_parser

        kwargs = {}
        if strategy == "recursive":
            kwargs = {"chunk_size": chunk_size, "chunk_overlap": chunk_overlap}

        chunker = get_chunker(strategy, **kwargs)
        pipeline = IngestionPipeline(
            parser_factory=parser_factory,
            chunker=chunker,
            embedder=resources.embedder,
            session_factory=resources.session_factory,
            qdrant_service=resources.qdrant_client,
            tagger=tagger,
            contextualizer=contextualizer,
            strip_tail=strip_tail,
            strip_markdown=strip_markdown,
        )

        filtering_active = strip_markdown or strip_tail
        if await asyncio.to_thread(lambda: path.is_file()):  # noqa: ASYNC240
            await _ingest_single(pipeline, path, contextualizer, filtering_active)

        elif await asyncio.to_thread(lambda: path.is_dir()):  # noqa: ASYNC240
            supported_exts = set(_parser_registry.keys())
            files = [
                f for f in sorted(path.rglob("*"))  # noqa: ASYNC240
                if (
                    await asyncio.to_thread(lambda: f.is_file())  # noqa: ASYNC240, B023
                    and f.suffix.lower() in supported_exts
                )
            ]

            if not files:
                console.print(
                    f"[yellow]No supported files found in {path}.[/yellow]\n"
                    f"Supported extensions: {sorted(supported_exts)}"
                )
                return

            await _ingest_batch(pipeline, files, contextualizer, filtering_active, concurrency)

        else:
            console.print(f"[red]Path not found: {path}[/red]")
            raise typer.Exit(1)

    finally:
        await teardown_deps(resources)


async def _ingest_single(
    pipeline: IngestionPipeline,
    path: Path,
    contextualizer: object | None,
    filtering_active: bool = False,
) -> None:
    """Ingest a single file with per-stage step indicator."""
    # Base stages: Parse, Chunk, Embed, Write = 4
    # +1 for Contextualize, +1 for Filter
    total_stages = 4 + (1 if contextualizer is not None else 0) + (1 if filtering_active else 0)
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

        def on_chunk_count(n: int) -> None:
            eta = f", est. {n * 8}s" if contextualizer is not None else ""
            progress.console.print(f"  [dim]→ {n} chunks{eta}[/dim]")

        try:
            doc = await pipeline.ingest(
                path, stage_callback=on_stage, on_chunk_count=on_chunk_count,
            )
        except Exception as exc:
            console.print(f"[red]✗[/red] {path.name}: {exc}")
            raise typer.Exit(1) from exc

    filter_suffix = _filter_suffix(pipeline, filtering_active)
    console.print(
        f"[green]✓[/green] {path.name} → "
        f"doc_id={doc.document_id}, status={doc.sync_status.value}"
        f"{filter_suffix}"
    )


async def _ingest_batch(
    pipeline: IngestionPipeline,
    files: list[Path],
    contextualizer: object | None,
    filtering_active: bool = False,
    concurrency: int = 1,
) -> None:
    """Ingest multiple files with a progress bar.

    concurrency=1 runs documents sequentially (original behaviour).
    concurrency>1 runs up to N documents simultaneously; each active document
    gets its own progress row showing the current pipeline stage.
    """
    total_stages = 4 + (1 if contextualizer is not None else 0) + (1 if filtering_active else 0)
    succeeded: list = []
    failed: list[FailedIngest] = []

    if concurrency <= 1:
        # ── Sequential path (original behaviour) ──────────────────────────
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

                def make_on_stage(captured: Path, counter: list[int]) -> object:
                    def on_stage(name: str) -> None:
                        counter[0] += 1
                        progress.update(
                            overall,
                            description=(
                                f"[dim]{captured.name}[/dim] "
                                f"[{counter[0]}/{total_stages}] {name}..."
                            ),
                        )
                    return on_stage

                def make_on_chunk_count(captured: Path) -> object:
                    def on_chunk_count(n: int) -> None:
                        eta = f", est. {n * 8}s" if contextualizer is not None else ""
                        progress.console.print(f"  [dim]{captured.name} → {n} chunks{eta}[/dim]")
                    return on_chunk_count

                t0 = time.monotonic()
                try:
                    doc = await pipeline.ingest(
                        path,
                        stage_callback=make_on_stage(path, stage_num),
                        on_chunk_count=make_on_chunk_count(path),
                    )
                    elapsed = time.monotonic() - t0
                    filter_suffix = _filter_suffix(pipeline, filtering_active)
                    succeeded.append(doc)
                    progress.console.print(f"  [green]✓[/green] {path.name}  ({elapsed:.1f}s){filter_suffix}")  # noqa: E501
                except Exception as exc:
                    elapsed = time.monotonic() - t0
                    logger.warning("Failed to ingest %s: %s", path, exc)
                    failed.append(FailedIngest(file_path=path, error=str(exc)))
                    progress.console.print(f"  [red]✗[/red] {path.name}: {exc}")

                progress.advance(overall)
                progress.update(overall, description="Ingesting")

    else:
        # ── Concurrent path ────────────────────────────────────────────────
        # Each active document occupies its own progress row. pipeline.last_filter_result
        # is a shared instance attribute and is unreliable under concurrency, so
        # filter suffix is intentionally omitted here.
        semaphore = asyncio.Semaphore(concurrency)

        with Progress(
            SpinnerColumn(),
            BarColumn(),
            MofNCompleteColumn(),
            TextColumn("{task.description}"),
            console=console,
        ) as progress:
            overall = progress.add_task(
                f"Ingesting [dim]{files[0].parent}[/dim]",
                total=len(files),
            )

            async def process_file(path: Path) -> None:
                async with semaphore:
                    file_task = progress.add_task(
                        f"[dim]{path.name}[/dim] [1/{total_stages}] Starting...",
                        total=total_stages,
                    )
                    stage_num = [0]

                    def on_stage(name: str) -> None:
                        stage_num[0] += 1
                        progress.update(
                            file_task,
                            completed=stage_num[0],
                            description=(
                                f"[dim]{path.name}[/dim] "
                                f"[{stage_num[0]}/{total_stages}] {name}..."
                            ),
                        )

                    t0 = time.monotonic()
                    try:
                        doc = await pipeline.ingest(path, stage_callback=on_stage)
                        elapsed = time.monotonic() - t0
                        succeeded.append(doc)
                        progress.console.print(f"  [green]✓[/green] {path.name}  ({elapsed:.1f}s)")
                    except Exception as exc:
                        elapsed = time.monotonic() - t0
                        logger.warning("Failed to ingest %s: %s", path, exc)
                        failed.append(FailedIngest(file_path=path, error=str(exc)))
                        progress.console.print(f"  [red]✗[/red] {path.name}: {exc}")
                    finally:
                        progress.update(file_task, visible=False)
                        progress.advance(overall)
                        progress.update(
                            overall,
                            description=f"Ingesting [dim]{files[0].parent}[/dim]",
                        )

            await asyncio.gather(*[process_file(p) for p in files])

    console.print(
        f"\nDone: [green]{len(succeeded)} succeeded[/green], "
        f"[red]{len(failed)} failed[/red]"
    )
    if failed:
        for f in failed:
            console.print(f"  [red]✗[/red] {f.file_path.name}: {f.error}")


def _filter_suffix(pipeline: IngestionPipeline, filtering_active: bool) -> str:
    """Build the filter-result suffix string for sequential ingest output."""
    if not filtering_active or pipeline.last_filter_result is None:
        return ""
    fr = pipeline.last_filter_result
    if fr.cut_point is not None:
        return f", stripped {fr.removed_chars:,} chars ({fr.cut_reason})"
    return ", no tail detected"
