"""CLI eval subcommands: generate synthetic test set and run retrieval evaluation."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table

from app.cli._init_deps import init_deps, teardown_deps

logger = logging.getLogger(__name__)
console = Console()

eval_app = typer.Typer(help="Evaluate retrieval quality.")


@eval_app.command("generate-set")
def generate_set(
    output: Annotated[
        str, typer.Option("--output", "-o", help="Output JSON file path.")
    ] = "data/eval_test_set.json",
    num_chunks: Annotated[
        int, typer.Option("--num-chunks", "-n", help="Number of chunks to sample.")
    ] = 50,
    queries_per_chunk: Annotated[
        int, typer.Option("--queries-per-chunk", help="Queries to generate per chunk.")
    ] = 2,
    min_length: Annotated[
        int, typer.Option("--min-length", help="Minimum chunk content length (chars).")
    ] = 100,
    concurrency: Annotated[
        int, typer.Option("--concurrency", help="Max parallel LLM calls.")
    ] = 5,
    with_context: Annotated[
        bool, typer.Option("--with-context", help="Prepend each chunk's context to the synthesis prompt.")
    ] = False,
    include_doc: Annotated[
        list[str], typer.Option("--include-doc", help="Whitelist doc-id(s). Only these documents are sampled. Mutually exclusive with --exclude-doc and --auto-split.")
    ] = [],
    exclude_doc: Annotated[
        list[str], typer.Option("--exclude-doc", help="Blacklist doc-id(s). These documents are skipped. Mutually exclusive with --include-doc and --auto-split.")
    ] = [],
    auto_split: Annotated[
        float, typer.Option("--auto-split", help="Fraction (0-1) of documents to randomly select for sampling. Saves a split manifest JSON alongside the output. Mutually exclusive with --include-doc and --exclude-doc.")
    ] = 0.0,
) -> None:
    """Sample chunks and generate a synthetic evaluation test set via LLM."""
    # Validate mutual exclusivity
    active_filters = sum([bool(include_doc), bool(exclude_doc), auto_split > 0])
    if active_filters > 1:
        console.print("[red]Error: --include-doc, --exclude-doc, and --auto-split are mutually exclusive.[/red]")
        raise typer.Exit(code=1)
    if auto_split < 0.0 or auto_split > 1.0:
        console.print("[red]Error: --auto-split must be between 0.0 and 1.0.[/red]")
        raise typer.Exit(code=1)

    asyncio.run(_run_generate_set(
        output, num_chunks, queries_per_chunk, min_length, concurrency, with_context,
        list(include_doc), list(exclude_doc), auto_split,
    ))


@eval_app.command("run")
def run(
    test_set_path: Annotated[str, typer.Argument(help="Path to test set JSON file.")],
    top_k: Annotated[
        int, typer.Option("--top-k", "-k", help="Number of results to retrieve.")
    ] = 10,
    output: Annotated[
        str, typer.Option("--output", "-o", help="Optional JSON report output path.")
    ] = "",
    mode: Annotated[
        str, typer.Option("--mode", "-m", help="Retention mode: prefer_recent | awaken_forgotten"),
    ] = "prefer_recent",
) -> None:
    """Run evaluation on a test set and display metrics."""
    asyncio.run(_run_eval(test_set_path, top_k, output, mode))


# --------------------------------------------------------------------------
# Async implementations
# --------------------------------------------------------------------------


async def _run_generate_set(
    output_path: str,
    num_chunks: int,
    queries_per_chunk: int,
    min_length: int,
    concurrency: int,
    with_context: bool = False,
    include_doc_ids: list[str] | None = None,
    exclude_doc_ids: list[str] | None = None,
    auto_split: float = 0.0,
) -> None:
    import random

    from app.config import settings
    from app.core.repository import DocumentRepository
    from app.evaluation.sampler import sample_chunks_stratified
    from app.evaluation.synthesizer import generate_test_set

    resources = await init_deps()
    try:
        if resources.generator is None:
            console.print("[red]Error: LLM_API_KEY not configured. Cannot generate queries.[/red]")
            raise typer.Exit(code=1)

        generator = resources.generator

        # Resolve auto-split: randomly partition all documents and write split manifest
        if auto_split > 0.0:
            async with resources.session_factory() as session:
                all_docs = await DocumentRepository.list_all(session)

            all_doc_ids = [str(d.document_id) for d in all_docs]
            random.shuffle(all_doc_ids)
            split_at = max(1, round(len(all_doc_ids) * auto_split))
            included = all_doc_ids[:split_at]
            excluded = all_doc_ids[split_at:]

            split_path = Path(output_path).with_stem(Path(output_path).stem + "_split").with_suffix(".json")
            split_path.parent.mkdir(parents=True, exist_ok=True)
            split_path.write_text(
                json.dumps(
                    {"split_ratio": auto_split, "included_doc_ids": included, "excluded_doc_ids": excluded},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            console.print(
                f"Auto-split: [cyan]{len(included)}[/cyan] included / "
                f"[yellow]{len(excluded)}[/yellow] excluded. "
                f"Manifest → [cyan]{split_path}[/cyan]"
            )
            include_doc_ids = included

        # 1. Sample chunks
        async with resources.session_factory() as session:
            sampled = await sample_chunks_stratified(
                session,
                total_n=num_chunks,
                min_content_length=min_length,
                include_doc_ids=include_doc_ids if include_doc_ids else None,
                exclude_doc_ids=exclude_doc_ids if exclude_doc_ids else None,
            )

        if not sampled:
            console.print("[yellow]No eligible chunks found. Aborting.[/yellow]")
            raise typer.Exit(code=1)

        console.print(f"Sampled [cyan]{len(sampled)}[/cyan] chunks from database.")

        # 2. Synthesize queries
        entries = await generate_test_set(
            generator,
            sampled,
            num_queries_per_chunk=queries_per_chunk,
            concurrency=concurrency,
            model_name=settings.llm_model,
            with_context=with_context,
        )

        # 3. Write JSON
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                [e.model_dump() for e in entries],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        console.print(
            f"Wrote [green]{len(entries)}[/green] queries to [cyan]{out}[/cyan]"
        )

    finally:
        await teardown_deps(resources.qdrant_client, resources.embedder, resources.generator)


async def _run_eval(
    test_set_path: str,
    top_k: int,
    output_path: str,
    mode: str,
) -> None:
    from app.core.pipeline_deps import PipelineDeps
    from app.evaluation.runner import run_evaluation
    from app.evaluation.schemas import TestSetEntry
    from app.retrieval import workflows
    from app.retrieval.pipeline import RetrievalPipeline

    # Load test set
    path = Path(test_set_path)
    if not path.exists():
        console.print(f"[red]Test set file not found: {path}[/red]")
        raise typer.Exit(code=1)

    raw = json.loads(path.read_text(encoding="utf-8"))
    test_set = [TestSetEntry.model_validate(item) for item in raw]
    console.print(f"Loaded [cyan]{len(test_set)}[/cyan] queries from [cyan]{path}[/cyan]")

    resources = await init_deps()
    try:
        deps = PipelineDeps(
            embedder=resources.embedder,
            qdrant_client=resources.qdrant_client,
            session_factory=resources.session_factory,
        )
        pipeline = RetrievalPipeline(
            dag=workflows.hybrid(deps),
            embedder=deps.embedder,
            session_factory=deps.session_factory,
        )

        with Progress(
            SpinnerColumn(),
            BarColumn(),
            MofNCompleteColumn(),
            TextColumn("Evaluating"),
            console=console,
        ) as progress:
            eval_task = progress.add_task("Evaluating", total=len(test_set))

            def on_query(current: int, total: int) -> None:
                progress.update(eval_task, completed=current)

            report = await run_evaluation(
                pipeline,
                test_set,
                top_k=top_k,
                retention_mode=mode,  # type: ignore[arg-type]
                query_callback=on_query,
            )

        # Display summary table
        summary = Table(title="Evaluation Summary")
        summary.add_column("Metric", style="cyan")
        summary.add_column("Value", justify="right")
        summary.add_row("Queries", str(report.num_queries))
        summary.add_row("Top-K", str(report.top_k))
        summary.add_row("MRR", f"{report.mrr:.4f}")
        summary.add_row(f"nDCG@{top_k}", f"{report.mean_ndcg_at_k:.4f}")
        summary.add_row(f"Recall@{top_k}", f"{report.mean_recall_at_k:.4f}")
        console.print(summary)

        # Per-query detail table
        detail = Table(title="Per-Query Results")
        detail.add_column("#", style="dim", width=4)
        detail.add_column("Query", max_width=60)
        detail.add_column("RR", justify="right", width=7)
        detail.add_column("nDCG", justify="right", width=7)
        detail.add_column("Recall", justify="right", width=7)
        detail.add_column("Hits", justify="right", width=5)

        for i, r in enumerate(report.per_query, start=1):
            hits = len(set(r.ground_truth_chunk_ids) & set(r.retrieved_chunk_ids))
            query_preview = r.query[:55] + "..." if len(r.query) > 55 else r.query
            detail.add_row(
                str(i),
                query_preview,
                f"{r.reciprocal_rank:.3f}",
                f"{r.ndcg_at_k:.3f}",
                f"{r.recall_at_k:.3f}",
                f"{hits}/{len(r.ground_truth_chunk_ids)}",
            )

        console.print(detail)

        # Optional JSON report
        if output_path:
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(
                report.model_dump_json(indent=2),
                encoding="utf-8",
            )
            console.print(f"Report written to [cyan]{out}[/cyan]")

    finally:
        await teardown_deps(resources.qdrant_client, resources.embedder, resources.generator)
