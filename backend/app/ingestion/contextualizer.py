"""Context generator for Contextual Retrieval.

Generates a short document-level context for each chunk via LLM,
to be prepended before embedding for improved retrieval accuracy.

Message structure uses a stable 3-message prefix (system + document user + assistant ack)
shared across all chunks of the same document, enabling DeepSeek KV cache hits
from the second chunk onward.

Reference: https://www.anthropic.com/news/contextual-retrieval
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.generation.generator import LLMGenerator

logger = logging.getLogger(__name__)

_SYSTEM_MESSAGE = (
    "You are a document analysis assistant. "
    "You will be given a document, then asked to situate a specific chunk within it."
)

_ASSISTANT_ACK = (
    "I've read the document. Please provide the chunk you'd like me to contextualize."
)

_CHUNK_INSTRUCTION = (
    "Please give a short succinct context to situate this chunk within the "
    "overall document for the purposes of improving search retrieval of the chunk. "
    "Answer only with the succinct context and nothing else."
)


class ContextGenerator:
    """Generate document-level context for individual chunks via LLM."""

    def __init__(self, generator: LLMGenerator) -> None:
        self._generator = generator

    async def generate(
        self,
        document_text: str,
        chunk_content: str,
    ) -> str | None:
        """Generate a short context for a chunk within its document.

        Args:
            document_text: Full document text.
            chunk_content: Text of the target chunk.

        Returns:
            Context string on success, None on failure.
        """
        messages = _build_messages(document_text, chunk_content)
        try:
            result = await self._generator.raw_chat(
                messages=messages,
                temperature=0.0,
            )
            return result.strip() if result and result.strip() else None
        except Exception as exc:
            logger.warning("Context generation failed for chunk: %s", exc)
            return None

    async def generate_batch(
        self,
        document_text: str,
        chunk_contents: list[str],
        chunk_callback: Callable[[int, int], None] | None = None,
    ) -> list[str | None]:
        """Generate context for multiple chunks sharing the same document.

        Calls LLM sequentially per chunk so that DeepSeek's prefix cache can
        be constructed on the first request and hit from the second onward.
        A single chunk failure does not interrupt the batch; that chunk gets None.

        Args:
            document_text: Full document text (shared across all chunks).
            chunk_contents: List of chunk texts.
            chunk_callback: Optional callable invoked after each chunk with
                (completed, total). Useful for driving CLI progress indicators.

        Returns:
            List of context strings (or None for failed chunks), same length
            as chunk_contents.
        """
        if not chunk_contents:
            return []

        total = len(chunk_contents)
        results: list[str | None] = []
        total_cache_hit = 0
        total_cache_miss = 0

        for i, content in enumerate(chunk_contents):
            messages = _build_messages(document_text, content)
            try:
                result, usage = await self._generator.raw_chat_with_usage(
                    messages=messages,
                    temperature=0.0,
                )
                results.append(result.strip() if result and result.strip() else None)
                total_cache_hit += usage.get("prompt_cache_hit_tokens", 0)
                total_cache_miss += usage.get("prompt_cache_miss_tokens", 0)
            except Exception as exc:
                logger.warning(
                    "Context generation failed for chunk %d/%d: %s", i + 1, total, exc
                )
                results.append(None)

            if chunk_callback is not None:
                chunk_callback(i + 1, total)

        if total > 1:
            _log_cache_stats(total, total_cache_hit, total_cache_miss)

        return results


# ============================================================
# Helpers
# ============================================================


def _build_messages(document_text: str, chunk_content: str) -> list[dict[str, str]]:
    """Build the 4-message conversation for chunk contextualization.

    The first three messages are identical for all chunks in the same document,
    forming a stable prefix that DeepSeek can cache.
    """
    return [
        {"role": "system", "content": _SYSTEM_MESSAGE},
        {"role": "user", "content": f"<document>\n{document_text}\n</document>"},
        {"role": "assistant", "content": _ASSISTANT_ACK},
        {
            "role": "user",
            "content": f"<chunk>\n{chunk_content}\n</chunk>\n{_CHUNK_INSTRUCTION}",
        },
    ]


def _log_cache_stats(total_chunks: int, cache_hit: int, cache_miss: int) -> None:
    """Log prompt cache hit/miss statistics for a batch run."""
    total = cache_hit + cache_miss
    if total == 0:
        # Non-DeepSeek backend or usage fields absent; skip logging
        return

    rate = cache_hit / total * 100
    logger.info(
        "Prompt cache stats for %d chunks: hit=%d tokens, miss=%d tokens, hit_rate=%.1f%%",
        total_chunks,
        cache_hit,
        cache_miss,
        rate,
    )

    if total_chunks >= 3 and rate < 50.0:
        logger.warning(
            "Low prompt cache hit rate (%.1f%%) for %d-chunk batch — "
            "prefix structure may not be stable or backend may not support caching.",
            rate,
            total_chunks,
        )
