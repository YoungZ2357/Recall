"""CLI entry point: python -m app.cli

Usage:
    python -m app.cli ingest <path> [--strategy recursive|fixed_count] [--chunk-size N] [--chunk-overlap N]
    python -m app.cli reindex [--doc-id UUID] [--all]
"""

import logging

import typer

from app.cli.ingest import ingest_app
from app.cli.reindex import reindex_app
from app.config import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(levelname)s %(name)s: %(message)s",
)

app = typer.Typer(
    name="recall",
    help="Recall CLI — manage your local knowledge base.",
    no_args_is_help=True,
)
app.add_typer(ingest_app, name="ingest")
app.add_typer(reindex_app, name="reindex")

if __name__ == "__main__":
    app()
