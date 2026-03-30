"""CLI entry point: python -m app.cli

Usage:
    python -m app.cli ingest <path> [--strategy recursive|fixed_count] [--chunk-size N] [--chunk-overlap N]
    python -m app.cli reindex [--doc-id UUID] [--all]
    python -m app.cli search "<query>" [--top-k N] [--mode prefer_recent|awaken_forgotten] [--verbose]
    python -m app.cli generate "<query>" [--top-k N] [--mode prefer_recent|awaken_forgotten] [--stream]
    python -m app.cli docs list
    python -m app.cli docs delete [--doc-id UUID] [--title TEXT] [--all] [--yes]
"""

import logging

import typer

from app.cli.docs import docs_app
from app.cli.eval import eval_app
from app.cli.generate import generate_app
from app.cli.ingest import ingest_app
from app.cli.reindex import reindex_app
from app.cli.search import search_app
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
app.add_typer(search_app, name="search")
app.add_typer(generate_app, name="generate")
app.add_typer(eval_app, name="eval")
app.add_typer(docs_app, name="docs")

if __name__ == "__main__":
    app()
