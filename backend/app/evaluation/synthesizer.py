"""LLM-based synthetic query generation from sampled chunks."""

from __future__ import annotations

import asyncio
import json
import logging

from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn

from app.evaluation.sampler import SampledChunk
from app.evaluation.schemas import QueryMetadata, TestSetEntry
from app.generation.generator import LLMGenerator

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a query generation assistant. Given an article title and a text passage from that "
    "article, generate natural language questions whose answers can be found in the passage.\n\n"
    "Rules:\n"
    "- Generate questions in the SAME LANGUAGE as the passage.\n"
    "- Questions must be relevant to the article topic indicated by the title.\n"
    "- Questions must be natural language queries (keyword-style, full questions, or colloquial).\n"
    "- Do NOT copy verbatim phrases from the passage.\n"
    "- Vary question types: factual, structural, comparative.\n"
    "- Respond with ONLY a JSON array, no markdown fences or explanation.\n\n"
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
        f"Based on the following passage from this article, generate {num_queries} diverse questions.\n\n"
        f"Passage:\n{chunk_content}"
    )
    return "\n".join(parts)


def _parse_llm_response(raw: str, model_name: str) -> list[dict[str, str]]:
    """Parse JSON array from LLM response, stripping markdown fences if present."""
    text = raw.strip()
    if text.startswith("```"):
        # Strip ```json ... ``` fences
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()
    return json.loads(text)


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
        {"role": "user", "content": _build_user_message(chunk.content, num_queries, chunk.document_title, context)},
    ]

    entries: list[TestSetEntry] = []
    raw = ""

    for attempt in range(2):
        raw = await generator.raw_chat(messages, temperature=0.7)
        try:
            items = _parse_llm_response(raw, model_name)
            for item in items:
                query_text = item.get("query", "").strip()
                if not query_text:
                    logger.debug("Skipping empty query from chunk %s", chunk.chunk_id)
                    continue
                entries.append(TestSetEntry(
                    query=query_text,
                    ground_truth_chunk_ids=[chunk.chunk_id],
                    source_document_id=chunk.document_id,
                    metadata=QueryMetadata(
                        query_type=item.get("query_type", "factual"),
                        generator_model=model_name,
                    ),
                ))
            return entries
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            if attempt == 0:
                logger.debug(
                    "JSON parse failed for chunk %s (attempt 1), retrying: %s",
                    chunk.chunk_id, exc,
                )
                continue
            # Fallback: use raw text as a single query
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
            entries.append(TestSetEntry(
                query=fallback_text,
                ground_truth_chunk_ids=[chunk.chunk_id],
                source_document_id=chunk.document_id,
                metadata=QueryMetadata(
                    query_type="factual",
                    generator_model=model_name,
                ),
            ))

    return entries


async def generate_test_set(
    generator: LLMGenerator,
    sampled_chunks: list[SampledChunk],
    num_queries_per_chunk: int = 2,
    concurrency: int = 5,
    model_name: str = "",
    with_context: bool = False,
) -> list[TestSetEntry]:
    """Generate a full test set from sampled chunks with concurrency control.

    Args:
        generator: LLMGenerator instance with raw_chat() support.
        sampled_chunks: Chunks to generate queries from.
        num_queries_per_chunk: Number of queries to generate per chunk.
        concurrency: Max parallel LLM calls.
        model_name: Model identifier recorded in metadata.
        with_context: If True, prepend each chunk's context field to the synthesis prompt.

    Returns:
        List of TestSetEntry ready for JSON serialization.
    """
    semaphore = asyncio.Semaphore(concurrency)
    all_entries: list[TestSetEntry] = []
    lock = asyncio.Lock()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
    ) as progress:
        task = progress.add_task("Synthesizing queries", total=len(sampled_chunks))

        async def _process(chunk: SampledChunk) -> None:
            async with semaphore:
                entries = await synthesize_queries(
                    generator, chunk, num_queries_per_chunk, model_name, with_context
                )
            async with lock:
                all_entries.extend(entries)
            progress.advance(task)

        await asyncio.gather(*[_process(c) for c in sampled_chunks])

    logger.info(
        "Generated %d queries from %d chunks", len(all_entries), len(sampled_chunks)
    )
    return all_entries
