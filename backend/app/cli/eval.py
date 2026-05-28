"""CLI eval subcommands: generate synthetic test set and run retrieval evaluation."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table

from app.cli._init_deps import AppResources, init_deps, teardown_deps

if TYPE_CHECKING:
    from app.evaluation.schemas import EvalReport, TestSetEntry
    from app.services import EvaluationService

logger = logging.getLogger(__name__)
console = Console()

# Mirror the directories defined in app/main.py so CLI and API see the same artifacts.
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_EVAL_TEST_SET_DIR = _BACKEND_ROOT / "data" / "eval_sets"
_EVAL_REPORT_DIR = _BACKEND_ROOT / "data" / "eval_reports"

eval_app = typer.Typer(help="Evaluate retrieval quality.")
test_sets_app = typer.Typer(help="Manage evaluation test sets on disk.")
reports_app = typer.Typer(help="Manage evaluation reports on disk.")


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
        bool, typer.Option("--with-context", help="Prepend each chunk's context to the synthesis prompt.")  # noqa: E501
    ] = False,
    pool_size: Annotated[
        int, typer.Option("--pool-size", help="Vector-recall pool depth for graded relevance expansion.")  # noqa: E501
    ] = 50,
    skip_grading: Annotated[
        bool, typer.Option("--skip-grading", help="Skip pool grading; output only source-chunk anchor (grade=3). Useful for debugging the synthesis stage.")  # noqa: E501
    ] = False,
    include_doc: Annotated[
        list[str], typer.Option("--include-doc", help="Whitelist doc-id(s). Only these documents are sampled. Mutually exclusive with --exclude-doc and --auto-split.")  # noqa: E501
    ] = None,
    exclude_doc: Annotated[
        list[str], typer.Option("--exclude-doc", help="Blacklist doc-id(s). These documents are skipped. Mutually exclusive with --include-doc and --auto-split.")  # noqa: E501
    ] = None,
    auto_split: Annotated[
        float, typer.Option("--auto-split", help="Fraction (0-1) of documents to randomly select for sampling. Saves a split manifest JSON alongside the output. Mutually exclusive with --include-doc and --exclude-doc.")  # noqa: E501
    ] = 0.0,
) -> None:
    """Sample chunks, synthesize queries, then LLM-grade vector-recall pool for graded qrels."""
    # Validate mutual exclusivity
    if exclude_doc is None:
        exclude_doc = []
    if include_doc is None:
        include_doc = []
    active_filters = sum([bool(include_doc), bool(exclude_doc), auto_split > 0])
    if active_filters > 1:
        console.print("[red]Error: --include-doc, --exclude-doc, and --auto-split are mutually exclusive.[/red]")  # noqa: E501
        raise typer.Exit(code=1)
    if auto_split < 0.0 or auto_split > 1.0:
        console.print("[red]Error: --auto-split must be between 0.0 and 1.0.[/red]")
        raise typer.Exit(code=1)
    if pool_size < 1:
        console.print("[red]Error: --pool-size must be >= 1.[/red]")
        raise typer.Exit(code=1)

    asyncio.run(_run_generate_set(
        output, num_chunks, queries_per_chunk, min_length, concurrency, with_context,
        pool_size, skip_grading,
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
    with_context: bool,
    pool_size: int,
    skip_grading: bool,
    include_doc_ids: list[str] | None = None,
    exclude_doc_ids: list[str] | None = None,
    auto_split: float = 0.0,
) -> None:
    import random

    from app.config import settings
    from app.core.repository import DocumentRepository
    from app.evaluation.sampler import sample_chunks_stratified
    from app.evaluation.synthesizer import expand_with_graded_pool, generate_test_set

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

            split_path = (
                Path(output_path)
                .with_stem(Path(output_path).stem + "_split")
                .with_suffix(".json")
            )
            await asyncio.to_thread(lambda: split_path.parent.mkdir(parents=True, exist_ok=True))
            split_content = json.dumps(
                {
                    "split_ratio": auto_split,
                    "included_doc_ids": included,
                    "excluded_doc_ids": excluded,
                },
                ensure_ascii=False,
                indent=2,
            )
            await asyncio.to_thread(lambda: split_path.write_text(split_content, encoding="utf-8"))
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

        # 3. Expand with graded pool
        if not skip_grading and entries:
            await expand_with_graded_pool(
                entries,
                embedder=resources.embedder,
                qdrant_client=resources.qdrant_client,
                session_factory=resources.session_factory,
                generator=generator,
                pool_size=pool_size,
                concurrency=concurrency,
                grader_model=settings.llm_model,
            )
        elif skip_grading:
            console.print("[dim]Pool grading skipped — entries retain source-chunk anchor only.[/dim]")  # noqa: E501

        # 4. Write JSON
        out = Path(output_path)
        await asyncio.to_thread(lambda: out.parent.mkdir(parents=True, exist_ok=True))
        out_json = json.dumps(
            [e.model_dump() for e in entries],
            ensure_ascii=False,
            indent=2,
        )
        await asyncio.to_thread(lambda: out.write_text(out_json, encoding="utf-8"))  # noqa: ASYNC240
        console.print(
            f"Wrote [green]{len(entries)}[/green] queries to [cyan]{out}[/cyan]"
        )

    finally:
        await teardown_deps(resources)


async def _run_eval(
    test_set_path: str,
    top_k: int,
    output_path: str,
    mode: str,
) -> None:
    from app.evaluation.runner import run_evaluation
    from app.evaluation.schemas import TestSetEntry

    # Load test set
    path = Path(test_set_path)
    if not await asyncio.to_thread(lambda: path.exists()):  # noqa: ASYNC240
        console.print(f"[red]Test set file not found: {path}[/red]")
        raise typer.Exit(code=1)

    raw = await asyncio.to_thread(lambda: json.loads(path.read_text(encoding="utf-8")))  # noqa: ASYNC240
    test_set = [TestSetEntry.model_validate(item) for item in raw]
    console.print(f"Loaded [cyan]{len(test_set)}[/cyan] queries from [cyan]{path}[/cyan]")

    resources = await init_deps()
    try:
        search_service = resources.search_service

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
                search_service,
                test_set,
                top_k=top_k,
                retention_mode=mode,  # type: ignore[arg-type]
                query_callback=on_query,
            )

        _render_report(report, top_k=top_k, test_set=test_set)

        # Optional JSON report
        if output_path:
            out = Path(output_path)
            await asyncio.to_thread(lambda: out.parent.mkdir(parents=True, exist_ok=True))  # noqa: ASYNC240
            await asyncio.to_thread(
                lambda: out.write_text(  # noqa: ASYNC240
                    report.model_dump_json(indent=2), encoding="utf-8"
                )
            )
            console.print(f"Report written to [cyan]{out}[/cyan]")

    finally:
        await teardown_deps(resources)


# --------------------------------------------------------------------------
# Shared rendering / service-construction helpers
# --------------------------------------------------------------------------


def _render_report(
    report: EvalReport,
    top_k: int,
    test_set: list[TestSetEntry] | None = None,
) -> None:
    """Render an EvalReport: aggregate summary table + per-query detail table.

    When `test_set` is provided, the per-query table includes a "Rel>=2 Hits"
    column counting how many rel>=2 chunks were retrieved within top-k. When
    omitted (e.g. `eval reports show`), that column is skipped.
    """
    summary = Table(title="Evaluation Summary")
    summary.add_column("Metric", style="cyan")
    summary.add_column("Value", justify="right")
    summary.add_row("Queries", str(report.num_queries))
    summary.add_row("Top-K", str(report.top_k))
    for metric_name, value in report.aggregate_metrics.items():
        summary.add_row(metric_name, f"{value:.4f}")
    console.print(summary)

    metric_columns = list(report.aggregate_metrics.keys())
    detail = Table(title="Per-Query Results")
    detail.add_column("#", style="dim", width=4)
    detail.add_column("Query", max_width=50)
    for m in metric_columns:
        detail.add_column(m, justify="right")

    entry_by_id: dict[str, TestSetEntry] | None = None
    if test_set is not None:
        detail.add_column("Rel>=2 Hits", justify="right", width=10)
        entry_by_id = {e.query_id: e for e in test_set}

    for i, r in enumerate(report.per_query, start=1):
        query_preview = r.query[:45] + "..." if len(r.query) > 45 else r.query
        row = [str(i), query_preview]
        for m in metric_columns:
            row.append(f"{r.metrics.get(m, 0.0):.3f}")

        if entry_by_id is not None:
            entry_lookup = entry_by_id.get(r.query_id)
            if entry_lookup is None:
                hits_str = "—"
            else:
                rel_set = {
                    cid for cid, g in entry_lookup.relevance.items() if g >= 2
                }
                hits = sum(1 for cid in r.retrieved_chunk_ids[:top_k] if cid in rel_set)
                hits_str = f"{hits}/{len(rel_set)}"
            row.append(hits_str)

        detail.add_row(*row)

    console.print(detail)


def _build_eval_service(resources: AppResources) -> EvaluationService:
    """Build an EvaluationService bound to the same directories as the API."""
    # Import locally to avoid pulling FastAPI/services chain at module import time.
    from app.services import EvaluationService

    return EvaluationService(
        embedder=resources.embedder,
        qdrant_client=resources.qdrant_client,
        session_factory=resources.session_factory,
        generator=resources.generator,
        search_service=resources.search_service,
        test_set_dir=_EVAL_TEST_SET_DIR,
        report_dir=_EVAL_REPORT_DIR,
    )


def _format_size(num_bytes: int) -> str:
    """Format file size with a sensible unit (B / KB / MB)."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes / (1024 * 1024):.2f} MB"


def _confirm_or_exit(prompt_text: str, *, skip: bool) -> None:
    """Prompt for 'y' confirmation; exit 0 on anything else. No-op when skip=True."""
    if skip:
        return
    console.print(prompt_text)
    confirm = typer.prompt("Type 'y' to confirm", default="n")
    if confirm.lower() != "y":
        console.print("Aborted.")
        raise typer.Exit(code=0)


# --------------------------------------------------------------------------
# test-sets sub-app
# --------------------------------------------------------------------------


@test_sets_app.command("list")
def test_sets_list() -> None:
    """List all test sets stored under backend/data/eval_sets/."""
    asyncio.run(_run_test_sets_list())


async def _run_test_sets_list() -> None:
    resources = await init_deps()
    try:
        svc = _build_eval_service(resources)
        summaries = svc.list_test_sets()
        if not summaries:
            console.print("[dim]No test sets found.[/dim]")
            return

        table = Table(title=f"Test Sets ({len(summaries)} total)")
        table.add_column("Name", style="cyan")
        table.add_column("Entries", justify="right", width=8)
        table.add_column("Size", justify="right", width=10)
        table.add_column("Created At", width=19)
        for s in summaries:
            table.add_row(
                s.name,
                str(s.entry_count),
                _format_size(s.size_bytes),
                s.created_at[:19].replace("T", " "),
            )
        console.print(table)
    finally:
        await teardown_deps(resources)


@test_sets_app.command("show")
def test_sets_show(
    name: Annotated[str, typer.Argument(help="Test set name (filename stem).")],
    preview: Annotated[
        int, typer.Option("--preview", "-p", min=0, max=100, help="Number of entries to preview.")
    ] = 5,
) -> None:
    """Show a test set's metadata and a preview of its entries."""
    asyncio.run(_run_test_sets_show(name, preview))


async def _run_test_sets_show(name: str, preview: int) -> None:
    from app.core.exceptions import InvalidTestSetNameError, TestSetNotFoundError

    resources = await init_deps()
    try:
        svc = _build_eval_service(resources)
        try:
            summary = svc.load_test_set_summary(name)
            entries = svc.load_test_set(name, preview=preview)
        except (TestSetNotFoundError, InvalidTestSetNameError) as e:
            console.print(f"[red]Error:[/red] {e.message}")
            raise typer.Exit(code=1) from e

        meta = Table(title=f"Test Set: {summary.name}")
        meta.add_column("Field", style="cyan")
        meta.add_column("Value")
        meta.add_row("Entries", str(summary.entry_count))
        meta.add_row("Size", _format_size(summary.size_bytes))
        meta.add_row("Created At", summary.created_at[:19].replace("T", " "))
        console.print(meta)

        if not entries:
            return

        detail = Table(title=f"First {len(entries)} entries")
        detail.add_column("#", style="dim", width=4)
        detail.add_column("Query", max_width=60)
        detail.add_column("Type", width=12)
        detail.add_column("Source Chunk", style="dim", max_width=36)
        detail.add_column("Rel>=2", justify="right", width=8)
        for i, entry in enumerate(entries, start=1):
            rel_count = sum(1 for g in entry.relevance.values() if g >= 2)
            query_preview = entry.query if len(entry.query) <= 55 else entry.query[:55] + "..."
            detail.add_row(
                str(i),
                query_preview,
                entry.metadata.query_type,
                entry.source_chunk_id,
                str(rel_count),
            )
        console.print(detail)
    finally:
        await teardown_deps(resources)


@test_sets_app.command("delete")
def test_sets_delete(
    name: Annotated[str, typer.Argument(help="Test set name (filename stem).")],
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Skip confirmation prompt.")
    ] = False,
) -> None:
    """Delete a test set (and its split manifest if present)."""
    asyncio.run(_run_test_sets_delete(name, yes))


async def _run_test_sets_delete(name: str, yes: bool) -> None:
    from app.core.exceptions import InvalidTestSetNameError, TestSetNotFoundError

    resources = await init_deps()
    try:
        svc = _build_eval_service(resources)
        try:
            summary = svc.load_test_set_summary(name)
        except (TestSetNotFoundError, InvalidTestSetNameError) as e:
            console.print(f"[red]Error:[/red] {e.message}")
            raise typer.Exit(code=1) from e

        _confirm_or_exit(
            f"Delete test set [cyan]{summary.name}[/cyan] "
            f"({summary.entry_count} entries, {_format_size(summary.size_bytes)})? "
            "This cannot be undone.",
            skip=yes,
        )

        try:
            svc.delete_test_set(name)
        except TestSetNotFoundError as e:
            # Race condition: file disappeared between load_summary and delete.
            console.print(f"[red]Error:[/red] {e.message}")
            raise typer.Exit(code=1) from e

        console.print(f"[green]Deleted:[/green] {summary.name}")
    finally:
        await teardown_deps(resources)


# --------------------------------------------------------------------------
# reports sub-app
# --------------------------------------------------------------------------


@reports_app.command("list")
def reports_list() -> None:
    """List all evaluation reports stored under backend/data/eval_reports/."""
    asyncio.run(_run_reports_list())


async def _run_reports_list() -> None:
    resources = await init_deps()
    try:
        svc = _build_eval_service(resources)
        summaries = svc.list_reports()
        if not summaries:
            console.print("[dim]No reports found.[/dim]")
            return

        # Collect the union of metric names so columns are stable across reports.
        all_metrics: list[str] = []
        seen: set[str] = set()
        for s in summaries:
            for m in s.aggregate_metrics:
                if m not in seen:
                    all_metrics.append(m)
                    seen.add(m)

        table = Table(title=f"Reports ({len(summaries)} total)")
        table.add_column("Name", style="cyan")
        table.add_column("Queries", justify="right", width=8)
        table.add_column("Top-K", justify="right", width=6)
        table.add_column("Created At", width=19)
        for m in all_metrics:
            table.add_column(m, justify="right")

        for s in summaries:
            row = [
                s.name,
                str(s.num_queries),
                str(s.top_k),
                s.created_at[:19].replace("T", " "),
            ]
            for m in all_metrics:
                v = s.aggregate_metrics.get(m)
                row.append(f"{v:.4f}" if v is not None else "—")
            table.add_row(*row)
        console.print(table)
    finally:
        await teardown_deps(resources)


@reports_app.command("show")
def reports_show(
    name: Annotated[str, typer.Argument(help="Report name (filename stem).")],
) -> None:
    """Show an evaluation report's aggregate metrics and per-query details."""
    asyncio.run(_run_reports_show(name))


async def _run_reports_show(name: str) -> None:
    from app.core.exceptions import InvalidTestSetNameError, ReportNotFoundError

    resources = await init_deps()
    try:
        svc = _build_eval_service(resources)
        try:
            report = svc.load_report(name)
        except (ReportNotFoundError, InvalidTestSetNameError) as e:
            console.print(f"[red]Error:[/red] {e.message}")
            raise typer.Exit(code=1) from e

        console.print(f"Report: [cyan]{name}[/cyan]")
        _render_report(report, top_k=report.top_k, test_set=None)
    finally:
        await teardown_deps(resources)


@reports_app.command("delete")
def reports_delete(
    name: Annotated[str, typer.Argument(help="Report name (filename stem).")],
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Skip confirmation prompt.")
    ] = False,
) -> None:
    """Delete an evaluation report."""
    asyncio.run(_run_reports_delete(name, yes))


async def _run_reports_delete(name: str, yes: bool) -> None:
    from app.core.exceptions import InvalidTestSetNameError, ReportNotFoundError

    resources = await init_deps()
    try:
        svc = _build_eval_service(resources)
        try:
            report = svc.load_report(name)
        except (ReportNotFoundError, InvalidTestSetNameError) as e:
            console.print(f"[red]Error:[/red] {e.message}")
            raise typer.Exit(code=1) from e

        _confirm_or_exit(
            f"Delete report [cyan]{name}[/cyan] "
            f"({report.num_queries} queries, top-{report.top_k})? "
            "This cannot be undone.",
            skip=yes,
        )

        try:
            svc.delete_report(name)
        except ReportNotFoundError as e:
            console.print(f"[red]Error:[/red] {e.message}")
            raise typer.Exit(code=1) from e

        console.print(f"[green]Deleted:[/green] {name}")
    finally:
        await teardown_deps(resources)


# --------------------------------------------------------------------------
# Sub-app registration
# --------------------------------------------------------------------------

eval_app.add_typer(test_sets_app, name="test-sets")
eval_app.add_typer(reports_app, name="reports")
