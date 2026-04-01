"""Context generator for Contextual Retrieval.

Generates a short document-level context for each chunk via LLM,
to be prepended before embedding for improved retrieval accuracy.

Reference: https://www.anthropic.com/news/contextual-retrieval
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.generation.generator import LLMGenerator

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = (
    "<document>\n"
    "{document_text}\n"
    "</document>\n"
    "Here is the chunk we want to situate within the whole document:\n"
    "<chunk>\n"
    "{chunk_content}\n"
    "</chunk>\n"
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
        user_message = _PROMPT_TEMPLATE.format(
            document_text=document_text,
            chunk_content=chunk_content,
        )
        try:
            result = await self._generator.raw_chat(
                messages=[{"role": "user", "content": user_message}],
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
    ) -> list[str | None]:
        """Generate context for multiple chunks sharing the same document.

        Calls LLM sequentially per chunk. A single chunk failure does not
        interrupt the batch; that chunk gets None.

        Args:
            document_text: Full document text (shared across all chunks).
            chunk_contents: List of chunk texts.

        Returns:
            List of context strings (or None for failed chunks), same length
            as chunk_contents.
        """
        results: list[str | None] = []
        for content in chunk_contents:
            ctx = await self.generate(document_text, content)
            results.append(ctx)
        return results
