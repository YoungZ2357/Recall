"""CLI generate subcommand: retrieve context and generate an answer."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from app.cli._init_deps import init_deps, teardown_deps

logger = logging.getLogger(__name__)
console = Console()

generate_app = typer.Typer(help="Retrieve context and generate an answer with LLM.")


@generate_app.callback(invoke_without_command=True)
def generate(
    query: Annotated[str, typer.Argument(help="Question to answer.")],
    top_k: Annotated[int, typer.Option("--top-k", "-k", help="Number of context chunks.")] = 5,
    mode: Annotated[
        str,
        typer.Option("--mode", "-m", help="Retention mode: prefer_recent | awaken_forgotten"),
    ] = "prefer_recent",
    stream: Annotated[
        bool,
        typer.Option("--stream", "-s", help="Stream the response token by token."),
    ] = False,
) -> None:
    """Retrieve relevant context then generate an answer using the configured LLM."""
    asyncio.run(_run_generate(query, top_k, mode, stream))


async def _run_generate(
    query: str,
    top_k: int,
    mode: str,
    stream: bool,
) -> None:
    from app.config import settings

    from app.retrieval.pipeline import RetrievalPipeline
    from app.retrieval.reranker import Reranker
    from app.retrieval.searcher import VectorSearcher

    session_factory, qdrant, embedder, generator = await init_deps(settings)
    try:
        if generator is None:
            console.print(
                "[red]LLM generator not available.[/red] "
                "Set the [bold]LLM_API_KEY[/bold] environment variable to enable generation."
            )
            raise typer.Exit(code=1)

        searcher = VectorSearcher(qdrant, embedder)
        reranker = Reranker(embedder, settings)
        pipeline = RetrievalPipeline(
            searcher=searcher,
            reranker=reranker,
            embedder=embedder,
            session_factory=session_factory,
            settings=settings,
        )

        results = await pipeline.search(
            query_text=query,
            top_k=top_k,
            retention_mode=mode,  # type: ignore[arg-type]
        )

        if not results:
            console.print("[yellow]No relevant context found — answering without context.[/yellow]")

        # Display sources table
        if results:
            source_table = Table(title="Sources", show_header=True)
            source_table.add_column("#", style="dim", width=3)
            source_table.add_column("Score", justify="right", width=8)
            source_table.add_column("Document", style="cyan", max_width=30)
            source_table.add_column("Content", max_width=80)
            for i, r in enumerate(results, start=1):
                preview = r.content[:80].replace("\n", " ")
                if len(r.content) > 80:
                    preview += "..."
                source_table.add_row(
                    str(i),
                    f"{r.final_score:.4f}",
                    r.document_title or "—",
                    preview,
                )
            console.print(source_table)

        # Generate answer
        if stream:
            console.print(f"\n[bold]Answer[/bold] ([dim]{settings.llm_model}[/dim])\n")
            async for chunk in generator.generate_stream(query, results):
                if chunk.strip() == "data: [DONE]":
                    break
                if chunk.startswith("data: "):
                    try:
                        delta = json.loads(chunk[len("data: "):]).get("content", "")
                        print(delta, end="", flush=True)
                    except json.JSONDecodeError:
                        pass
            print()  # trailing newline after stream
        else:
            response = await generator.generate(query, results)
            console.print(
                Panel(
                    response.answer,
                    title=f"Answer  [dim]({response.model})[/dim]",
                    border_style="green",
                )
            )
            if response.usage:
                console.print(
                    f"[dim]tokens — prompt: {response.usage['prompt_tokens']}, "
                    f"completion: {response.usage['completion_tokens']}, "
                    f"total: {response.usage['total_tokens']}[/dim]"
                )

    finally:
        await teardown_deps(qdrant, embedder, generator)
