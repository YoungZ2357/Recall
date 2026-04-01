"""
Auto-tagger: generates document-level tags via LLM before chunking.

The tagger queries existing tags from SQLite for consistency, then calls
the LLM with the document content and existing tags as reference.
Tags are assigned at the document level; all chunks inherit them.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.repository import ChunkRepository
from app.generation.generator import LLMGenerator

logger = logging.getLogger(__name__)

# Max content characters sent to LLM; truncate beyond this to fit context window
_MAX_CONTENT_CHARS = 8000

_SYSTEM_PROMPT = (
    "You are a document tagging assistant. "
    "Analyze the document and return a JSON array of short, lowercase tag strings. "
    "Tags should capture the main topics, domains, and key concepts. "
    "Output only the JSON array — no explanation, no markdown fences."
)


class AutoTagger:
    """Generate document-level tags via LLM, reusing existing tags where possible."""

    def __init__(
        self,
        generator: LLMGenerator,
        max_content_chars: int = _MAX_CONTENT_CHARS,
    ) -> None:
        self._generator = generator
        self._max_content_chars = max_content_chars

    async def tag(self, content: str, session: AsyncSession) -> list[str]:
        """Generate tags for a document.

        Args:
            content: Full document text (will be truncated if too long).
            session: Active database session for querying existing tags.

        Returns:
            List of tag strings. Returns [] on LLM or parse failure.
        """
        existing_tags = await ChunkRepository.get_all_unique_tags(session)
        truncated = content[: self._max_content_chars]
        user_message = _build_user_message(truncated, existing_tags)

        try:
            raw = await self._generator.raw_chat(
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.3,
            )
        except Exception as exc:
            logger.warning("Auto-tagger LLM call failed: %s", exc)
            return []

        return _parse_tags(raw)


# ============================================================
# Helpers
# ============================================================

def _build_user_message(content: str, existing_tags: list[str]) -> str:
    parts = [f"Document content:\n{content}"]
    if existing_tags:
        parts.append(
            f"\nExisting tags in the knowledge base (reuse when relevant):\n"
            f"{json.dumps(existing_tags, ensure_ascii=False)}"
        )
    parts.append(
        "\nReturn a JSON array of tags for this document. "
        "Example: [\"machine learning\", \"python\", \"tutorial\"]"
    )
    return "\n".join(parts)


def _parse_tags(raw: str) -> list[str]:
    """Parse LLM response into list[str]. Returns [] on any parse failure."""
    raw = raw.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(
            line for line in lines if not line.startswith("```")
        ).strip()
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list) and all(isinstance(t, str) for t in parsed):
            return [t.strip() for t in parsed if t.strip()]
        logger.warning("Auto-tagger: unexpected JSON shape: %r", parsed)
        return []
    except json.JSONDecodeError as exc:
        logger.warning("Auto-tagger: failed to parse LLM response as JSON: %s | raw=%r", exc, raw)
        return []
