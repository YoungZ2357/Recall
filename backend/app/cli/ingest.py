"""CLI ingest subcommand: ingest a file or directory into the knowledge base."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from app.cli._init_deps import init_deps, teardown_deps
from app.ingestion.chunker import get_chunker
from app.ingestion.parser import BaseParser, _parser_registry, get_parser
from app.ingestion.pipeline import IngestionPipeline

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
) -> None:
    """Ingest a single file or all supported files in a directory."""
    asyncio.run(_run_ingest(path, pdf_parser, strategy, chunk_size, chunk_overlap))


async def _run_ingest(
    path: Path,
    pdf_parser: str,
    strategy: str,
    chunk_size: int,
    chunk_overlap: int,
) -> None:
    from app.config import settings

    session_factory, qdrant, embedder, _ = await init_deps(settings)
    try:
        # Build parser factory: marker / mineru override the default pymupdf for .pdf
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

        # Only pass chunk_size / chunk_overlap to strategies that support them
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
        )

        if path.is_file():
            try:
                doc = await pipeline.ingest(path)
                console.print(
                    f"[green]✓[/green] {path.name} → "
                    f"doc_id={doc.document_id}, status={doc.sync_status.value}"
                )
            except Exception as exc:
                console.print(f"[red]✗[/red] {path.name}: {exc}")
                raise typer.Exit(1) from exc

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

            console.print(f"Found [bold]{len(files)}[/bold] file(s) to ingest...")
            result = await pipeline.ingest_batch(files)

            table = Table(title="Ingest Results")
            table.add_column("File", style="cyan")
            table.add_column("Status", style="bold")
            table.add_column("Doc ID / Error")

            for doc in result.succeeded:
                table.add_row(
                    Path(doc.source_path).name,
                    "[green]synced[/green]",
                    str(doc.document_id),
                )
            for fail in result.failed:
                table.add_row(
                    fail.file_path.name,
                    "[red]failed[/red]",
                    fail.error,
                )

            console.print(table)
            console.print(
                f"\nDone: [green]{len(result.succeeded)} succeeded[/green], "
                f"[red]{len(result.failed)} failed[/red]"
            )

        else:
            console.print(f"[red]Path not found: {path}[/red]")
            raise typer.Exit(1)

    finally:
        await teardown_deps(qdrant, embedder)
