"""Toolkit CLI entry point.

Usage:
    python -m toolkit parse mineru <input.pdf> <output_dir> [options]
"""

import logging

import typer

from toolkit.cli.parse import parse_app

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
)

app = typer.Typer(
    name="toolkit",
    help="Recall toolkit — evaluation and external parsing utilities.",
    no_args_is_help=True,
)
app.add_typer(parse_app, name="parse")

if __name__ == "__main__":
    app()
