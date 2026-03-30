"""CLI parse subcommand: parse documents via external APIs."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from toolkit.external_parser.mineru import (
    MinerUError,
    _DEFAULT_MODEL_VERSION,
    _DEFAULT_POLL_INTERVAL,
    _DEFAULT_POLL_MAX_RETRIES,
    parse_pdf,
)

logger = logging.getLogger(__name__)
console = Console()

parse_app = typer.Typer(help="Parse documents via external APIs.")


@parse_app.command("mineru")
def mineru_parse(
    input: Annotated[Path, typer.Argument(help="Input PDF file path.")],
    output_dir: Annotated[Path, typer.Argument(help="Output directory for result files.")],
    model: Annotated[
        str,
        typer.Option(
            "--model",
            help="Parsing backend: pipeline (fast) | vlm (accurate).",
            show_default=True,
        ),
    ] = os.environ.get("MINERU_MODEL_VERSION", _DEFAULT_MODEL_VERSION),
    language: Annotated[
        str,
        typer.Option("--language", help="Primary document language code, e.g. 'ch' or 'en'."),
    ] = "ch",
    no_formula: Annotated[
        bool,
        typer.Option("--no-formula", help="Disable formula recognition."),
    ] = False,
    no_table: Annotated[
        bool,
        typer.Option("--no-table", help="Disable table detection."),
    ] = False,
    poll_interval: Annotated[
        int,
        typer.Option("--poll-interval", metavar="SECONDS", help="Seconds between status polls."),
    ] = int(os.environ.get("MINERU_POLL_INTERVAL", _DEFAULT_POLL_INTERVAL)),
    poll_retries: Annotated[
        int,
        typer.Option("--poll-retries", metavar="N", help="Max poll attempts before timeout."),
    ] = int(os.environ.get("MINERU_POLL_MAX_RETRIES", _DEFAULT_POLL_MAX_RETRIES)),
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable debug-level logging."),
    ] = False,
) -> None:
    """Parse a PDF via MinerU Precision API. Outputs <stem>.md and <stem>.json."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        md_path, json_path = parse_pdf(
            file_path=input,
            output_dir=output_dir,
            model_version=model,
            language=language,
            enable_formula=not no_formula,
            enable_table=not no_table,
            poll_interval=poll_interval,
            poll_max_retries=poll_retries,
        )
    except (MinerUError, FileNotFoundError, EnvironmentError) as exc:
        console.print(f"[red]✗[/red] {exc}")
        raise typer.Exit(1) from exc

    console.print(f"[green]✓[/green] Markdown → {md_path}")
    if json_path:
        console.print(f"[green]✓[/green] JSON     → {json_path}")
    else:
        console.print("[yellow]·[/yellow] JSON     → (not produced by API)")
