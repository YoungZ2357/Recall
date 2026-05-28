"""LLM-based graded relevance scoring for query-chunk pairs.

For each query, scores a pool of candidate chunks on a 0-3 scale in a single
LLM call. Used by the synthesizer pipeline to build TREC-style pooled qrels.
"""

from __future__ import annotations

import json
import logging

from app.generation.generator import LLMGenerator

logger = logging.getLogger(__name__)

_CONTENT_CHAR_LIMIT = 1200

_SYSTEM_PROMPT = (
    "You are a relevance assessor for an academic retrieval system. Given a question "
    "and a list of candidate passages, grade each passage on its relevance to the "
    "question.\n\n"

    "GRADING SCALE (0-3):\n"
    "- 3: The passage DIRECTLY ANSWERS the question. The answer is explicitly present.\n"
    "- 2: The passage contains NECESSARY SUPPORTING INFORMATION for the answer "
    "(definition, premise, mechanism, derivation step) but does not directly state "
    "the answer.\n"
    "- 1: The passage has BACKGROUND or CONTEXTUAL relevance to the topic but is "
    "insufficient to ground any part of the answer.\n"
    "- 0: The passage is IRRELEVANT to the question.\n\n"

    "RULES:\n"
    "- Grade strictly. Default to 0 when in doubt.\n"
    "- Judge each passage independently; do not assume one passage's content fills "
    "another's gap.\n"
    "- Ignore stylistic quality; judge only informational relevance to the question.\n\n"

    "Respond with ONLY a JSON array, no markdown fences, no preamble. "
    "Include exactly one object per candidate, in the order presented.\n"
    'Output format: [{"id": <integer>, "grade": <0|1|2|3>}, ...]'
)


def _build_user_message(query: str, candidates: list[tuple[str, str]]) -> str:
    """Build the user message containing the question and numbered passages."""
    numbered_blocks = []
    for i, (_, content) in enumerate(candidates, start=1):
        snippet = content[:_CONTENT_CHAR_LIMIT]
        if len(content) > _CONTENT_CHAR_LIMIT:
            snippet += "..."
        numbered_blocks.append(f"[#{i}]\n{snippet}")

    passages_block = "\n\n---\n\n".join(numbered_blocks)
    return (
        f"Question:\n{query}\n\n"
        f"Candidate passages (each prefixed by its [#id]):\n\n"
        f"{passages_block}\n\n"
        f"Grade all {len(candidates)} passages."
    )


def _parse_grading_response(raw: str) -> list[dict]:
    """Parse JSON array from LLM response, stripping markdown fences if present."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        text = "\n".join(lines).strip()
    return json.loads(text)


async def grade_candidates(
    generator: LLMGenerator,
    query: str,
    candidates: list[tuple[str, str]],
) -> dict[str, int]:
    """Grade a pool of candidate chunks for a single query.

    Args:
        generator: LLMGenerator instance.
        query: The query text.
        candidates: List of (chunk_id, content) tuples in fixed order.

    Returns:
        Dict mapping chunk_id → grade (0-3). Candidates missing from the LLM
        response default to grade 0. On total parse failure (after retry), all
        candidates default to 0 — callers should overlay any anchor grades
        (e.g. source chunk = 3) on top of this result.
    """
    if not candidates:
        return {}

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_message(query, candidates)},
    ]

    raw = ""
    for attempt in range(2):
        raw = await generator.raw_chat(messages, temperature=0.0)
        try:
            items = _parse_grading_response(raw)
        except json.JSONDecodeError as exc:
            if attempt == 0:
                logger.debug(
                    "Grading JSON parse failed for query=%r (attempt 1), retrying: %s",
                    query[:60], exc,
                )
                continue
            logger.warning(
                "Grading JSON parse failed after retry for query=%r — defaulting "
                "all %d candidates to grade=0",
                query[:60], len(candidates),
            )
            return {chunk_id: 0 for chunk_id, _ in candidates}

        # Build result: walk LLM output, validate id and grade range
        graded: dict[str, int] = {chunk_id: 0 for chunk_id, _ in candidates}
        for item in items:
            if not isinstance(item, dict):
                continue
            idx = item.get("id")
            grade = item.get("grade")
            if not isinstance(idx, int) or not isinstance(grade, int):
                continue
            if idx < 1 or idx > len(candidates):
                continue
            if grade < 0 or grade > 3:
                continue
            chunk_id = candidates[idx - 1][0]
            graded[chunk_id] = grade
        return graded

    # Unreachable, but satisfies type checker
    return {chunk_id: 0 for chunk_id, _ in candidates}
