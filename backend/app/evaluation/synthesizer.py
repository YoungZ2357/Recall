"""LLM-based synthetic query generation and graded pool expansion.

Three-stage pipeline:
    1. synthesize_queries — generate candidate queries from a source chunk
    2. expand_with_graded_pool — for each query, vector-only recall top-N
       candidates, then LLM-grade them on a 0-3 scale
    3. Source chunk is always anchored at grade=3 (the query was constructed
       to be answerable from it)
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Callable
from contextlib import nullcontext
from uuid import UUID

from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.pipeline_deps import PipelineDeps
from app.core.repository import ChunkRepository
from app.core.vectordb import QdrantService
from app.evaluation.grader import grade_candidates
from app.evaluation.sampler import SampledChunk
from app.evaluation.schemas import QueryMetadata, TestSetEntry
from app.generation.generator import LLMGenerator
from app.ingestion.embedder import BaseEmbedder
from app.retrieval.configs import VectorSearcherConfig
from app.retrieval.searcher import SearchQuery, VectorSearcher

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a query generation assistant for evaluating an academic paper retrieval system. "
    "Given an article title and a text passage (chunk) from that article, generate natural "
    "language questions whose answers can be found in the passage.\n\n"

    "SKIP RULES — return an empty JSON array [] if ANY of the following apply:\n"
    "- The passage is a reference list, acknowledgements, table of contents, or author affiliations.\n"  # noqa: E501
    "- The passage is predominantly formulas, tables, or figures with no surrounding explanatory prose.\n"  # noqa: E501
    "- The passage is a fragmentary segment that does not convey a self-contained point or claim "
    "(e.g., a sentence split mid-thought, boilerplate headers, or formatting artifacts).\n\n"

    "GENERATION RULES:\n"
    "- Generate questions in the SAME LANGUAGE as the passage.\n"
    "- Questions must be relevant to the article topic indicated by the title.\n"
    "- Questions must be natural language queries — full questions, colloquial phrasings, or "
    "keyword-style queries a researcher might type into a search bar.\n"
    "- Do NOT generate lookup questions whose answer is a specific number, percentage, score, "
    "or experimental result (e.g., 'What accuracy did X achieve on Y?'). Instead, focus on "
    "conceptual, mechanistic, and comparative questions (e.g., 'Why does X outperform Y?' or "
    "'How does the clipping mechanism stabilize training?').\n"
    "- Do NOT copy verbatim phrases from the passage into the question.\n"
    "- Vary question types: factual (what/how), structural (why designed this way), "
    "comparative (how does X differ from Y).\n\n"

    "Respond with ONLY a JSON array. No markdown fences, no explanation, no preamble.\n"
    "If skipping, respond with exactly: []\n\n"

    'Output format: [{"query": "...", "query_type": "factual|structural|comparative"}]'
)


def _build_user_message(
    chunk_content: str,
    num_queries: int,
    document_title: str,
    context: str | None = None,
) -> str:
    parts = [f"Article title: {document_title}\n"]
    if context:
        parts.append(f"Passage context (background):\n{context}\n")
    parts.append(
        f"Based on the following passage from this article, "
        f"generate {num_queries} diverse questions.\n\n"
        f"Passage:\n{chunk_content}"
    )
    return "\n".join(parts)


def _parse_llm_response(raw: str) -> list[dict[str, str]]:
    """Parse JSON array from LLM response, stripping markdown fences if present."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        text = "\n".join(lines).strip()
    return json.loads(text)


def _make_entry(
    query_text: str,
    query_type: str,
    chunk: SampledChunk,
    model_name: str,
) -> TestSetEntry:
    """Build a TestSetEntry with the source chunk anchored at grade=3."""
    return TestSetEntry(
        query_id=str(uuid.uuid4()),
        query=query_text,
        relevance={chunk.chunk_id: 3},
        source_document_id=chunk.document_id,
        source_chunk_id=chunk.chunk_id,
        metadata=QueryMetadata(
            query_type=query_type,
            generator_model=model_name,
        ),
    )


async def synthesize_queries(
    generator: LLMGenerator,
    chunk: SampledChunk,
    num_queries: int = 2,
    model_name: str = "",
    with_context: bool = False,
) -> list[TestSetEntry]:
    """Generate synthetic queries for a single chunk via LLM.

    On JSON parse failure, retries once. If still failing, falls back to
    treating raw text as a single factual query.
    """
    context = chunk.context if with_context else None
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": _build_user_message(
                chunk.content, num_queries, chunk.document_title, context
            ),
        },
    ]

    entries: list[TestSetEntry] = []
    raw = ""

    for attempt in range(2):
        raw = await generator.raw_chat(messages, temperature=0.7)
        try:
            items = _parse_llm_response(raw)
            for item in items:
                query_text = item.get("query", "").strip()
                if not query_text:
                    logger.debug("Skipping empty query from chunk %s", chunk.chunk_id)
                    continue
                entries.append(_make_entry(
                    query_text,
                    item.get("query_type", "factual"),
                    chunk,
                    model_name,
                ))
            return entries
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            if attempt == 0:
                logger.debug(
                    "JSON parse failed for chunk %s (attempt 1), retrying: %s",
                    chunk.chunk_id, exc,
                )
                continue
            fallback_text = raw.strip()[:500]
            if not fallback_text:
                logger.warning(
                    "Empty LLM response for chunk %s, skipping", chunk.chunk_id
                )
                return entries
            logger.warning(
                "JSON parse failed for chunk %s after retry, using raw text fallback",
                chunk.chunk_id,
            )
            entries.append(_make_entry(fallback_text, "factual", chunk, model_name))

    return entries


async def generate_test_set(
    generator: LLMGenerator,
    sampled_chunks: list[SampledChunk],
    num_queries_per_chunk: int = 2,
    concurrency: int = 5,
    model_name: str = "",
    with_context: bool = False,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[TestSetEntry]:
    """Generate queries from sampled chunks (without pool grading).

    When ``progress_callback`` is provided, the rich terminal progress bar is
    suppressed and the callback is invoked as ``callback(done, total)`` after
    each chunk completes — used by the API task runner to drive HTTP-pollable
    progress. CLI callers pass None and keep the terminal UI.
    """
    semaphore = asyncio.Semaphore(concurrency)
    all_entries: list[TestSetEntry] = []
    lock = asyncio.Lock()
    total = len(sampled_chunks)
    done = 0
    use_rich = progress_callback is None

    progress_cm = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
    ) if use_rich else nullcontext()

    with progress_cm as progress:
        rich_task = (
            progress.add_task("Synthesizing queries", total=total) if use_rich else None
        )

        async def _process(chunk: SampledChunk) -> None:
            nonlocal done
            async with semaphore:
                entries = await synthesize_queries(
                    generator, chunk, num_queries_per_chunk, model_name, with_context
                )
            async with lock:
                all_entries.extend(entries)
                done += 1
                done_snapshot = done
            if use_rich:
                progress.advance(rich_task)
            else:
                progress_callback(done_snapshot, total)

        await asyncio.gather(*[_process(c) for c in sampled_chunks])

    logger.info(
        "Generated %d queries from %d chunks", len(all_entries), len(sampled_chunks)
    )
    return all_entries


# ---------------------------------------------------------------------------
# Pool expansion + grading
# ---------------------------------------------------------------------------


async def _vector_recall_pool(
    searcher: VectorSearcher,
    embedder: BaseEmbedder,
    query: str,
    pool_size: int,
) -> list[str]:
    """Vector-only recall of `pool_size` candidate chunk_ids for a query."""
    vectors = await embedder.embed_batch([query])
    search_query = SearchQuery(
        text=query,
        embedding=vectors[0],
        top_k=pool_size,
        score_threshold=0.0,  # full pool, no early filtering
        filters=None,
    )
    hits = await searcher._search(search_query)
    return [h.chunk_id for h in hits]


async def _expand_one_entry(
    entry: TestSetEntry,
    searcher: VectorSearcher,
    embedder: BaseEmbedder,
    generator: LLMGenerator,
    session_factory: async_sessionmaker,
    pool_size: int,
    grader_model: str,
) -> None:
    """Mutate `entry.relevance` in place with graded pool relevance.

    The source chunk stays anchored at grade=3 regardless of LLM judgment.
    """
    # 1. Vector recall
    candidate_ids = await _vector_recall_pool(searcher, embedder, entry.query, pool_size)

    # 2. Drop the source chunk from the grading pool (already grade=3)
    candidate_ids = [cid for cid in candidate_ids if cid != entry.source_chunk_id]

    if not candidate_ids:
        entry.metadata.grader_model = grader_model
        return

    # 3. Hydrate content
    uuid_ids = [UUID(cid) for cid in candidate_ids]
    async with session_factory() as session:
        content_map = await ChunkRepository.get_content_by_ids(session, uuid_ids)
    candidates = [
        (cid, content_map.get(cid, ""))
        for cid in candidate_ids
        if content_map.get(cid)
    ]

    # 4. LLM grading
    graded = await grade_candidates(generator, entry.query, candidates)

    # 5. Merge — source chunk anchor stays grade=3
    for cid, grade in graded.items():
        if cid == entry.source_chunk_id:
            continue
        entry.relevance[cid] = grade
    entry.metadata.grader_model = grader_model


async def expand_with_graded_pool(
    entries: list[TestSetEntry],
    embedder: BaseEmbedder,
    qdrant_client: QdrantService,
    session_factory: async_sessionmaker,
    generator: LLMGenerator,
    pool_size: int = 50,
    concurrency: int = 5,
    grader_model: str = "",
    progress_callback: Callable[[int, int], None] | None = None,
) -> None:
    """Expand each entry's relevance dict with graded vector-pool candidates.

    Mutates entries in place. Concurrency is per-query; within each query the
    search → hydrate → grade steps run sequentially.

    When ``progress_callback`` is provided, the rich terminal progress bar is
    suppressed and the callback is invoked as ``callback(done, total)`` after
    each entry completes — used by the API task runner to drive HTTP-pollable
    progress. CLI callers pass None and keep the terminal UI.

    Args:
        entries: Test set entries to expand. Source chunk grade=3 is preserved.
        embedder: Used to embed queries for vector recall.
        qdrant_client: For vector search.
        session_factory: For content hydration.
        generator: LLM for grading.
        pool_size: Number of candidates to recall per query before grading.
        concurrency: Max parallel query expansions.
        grader_model: Model identifier recorded in QueryMetadata.grader_model.
        progress_callback: Optional callback for non-terminal progress reporting.
    """
    deps = PipelineDeps(
        embedder=embedder,
        qdrant_client=qdrant_client,
        session_factory=session_factory,
    )
    searcher = VectorSearcher(deps, VectorSearcherConfig(score_threshold=0.0))

    semaphore = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    total = len(entries)
    done = 0
    use_rich = progress_callback is None

    progress_cm = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
    ) if use_rich else nullcontext()

    with progress_cm as progress:
        rich_task = (
            progress.add_task("Grading pool candidates", total=total) if use_rich else None
        )

        async def _process(entry: TestSetEntry) -> None:
            nonlocal done
            async with semaphore:
                try:
                    await _expand_one_entry(
                        entry, searcher, embedder, generator,
                        session_factory, pool_size, grader_model,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Pool expansion failed for query_id=%s: %s — entry retains "
                        "only source chunk anchor", entry.query_id, exc,
                    )
            async with lock:
                done += 1
                done_snapshot = done
            if use_rich:
                progress.advance(rich_task)
            else:
                progress_callback(done_snapshot, total)

        await asyncio.gather(*[_process(e) for e in entries])

    logger.info(
        "Expanded %d entries with graded pool (size=%d)", len(entries), pool_size,
    )
