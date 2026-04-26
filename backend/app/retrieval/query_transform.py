"""Query transform layer: rewrite, expand, and diversify user queries.

Produces a list of TransformedQuery variants with route markers consumed by
QueryDispatcher, which fans them out to the appropriate retrieval pipelines.

Dependency order (no circular imports):
    query_transform.py  ←  pipeline.py (future integration)
"""

from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from app.retrieval.configs import (
    HyDeTransformerConfig,
    RAGFusionTransformerConfig,
    RewriteTransformerConfig,
)
from app.retrieval.operators import (
    PipelineContext,
    SearchHit,
    TransformedQuery,
)

if TYPE_CHECKING:
    from app.generation.generator import LLMGenerator
    from app.ingestion.embedder import BaseEmbedder

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_REWRITE_SYSTEM_PROMPT = (
    "You are a query rewriter. Rewrite the given query to be clearer, more "
    "specific, and better suited for vector-based retrieval. Remove noise words, "
    "expand abbreviations, and resolve ambiguities. Return ONLY the rewritten "
    "query text, with no explanation or prefix."
)

_RAG_FUSION_SYSTEM_PROMPT = (
    "You are a query variant generator. Generate exactly {num_variants} "
    "semantically equivalent but differently worded variants of the input query. "
    "Cover different perspectives and phrasings. Return ONLY a JSON array of "
    "strings, with no explanation. Example: [\"alternative phrasing 1\", "
    "\"alternative phrasing 2\"]"
)

_HYDE_SYSTEM_PROMPT = (
    "You are a technical documentation system. Write a short, authoritative "
    "passage that directly answers the given query, as if it were excerpted "
    "from a technical manual or knowledge base. Do NOT include phrases like "
    "'here is' or 'the following is'. Write the passage directly."
)


def _parse_variants(raw: str) -> list[str]:
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
        if isinstance(parsed, list) and all(isinstance(v, str) for v in parsed):
            return [v.strip() for v in parsed if v.strip()]
        logger.warning("RAG-Fusion: unexpected JSON shape: %r", parsed)
        return []
    except json.JSONDecodeError as exc:
        logger.warning(
            "RAG-Fusion: failed to parse LLM response as JSON: %s | raw=%r",
            exc, raw,
        )
        return []


def _identity_fallback(query_text: str) -> list[TransformedQuery]:
    """Standard fallback: return the original query as a direct-route variant."""
    return [TransformedQuery(text=query_text, route="direct")]


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class BaseQueryTransformer(ABC):
    """Abstract interface for query transformation strategies.

    Subclasses implement transform() to convert a raw query string into
    one or more TransformedQuery variants, each tagged with a route
    marker that the QueryDispatcher uses to fan out to pipelines.
    """

    @property
    def name(self) -> str:
        return self.__class__.__name__

    @abstractmethod
    async def transform(self, query_text: str) -> list[TransformedQuery]: ...


# ---------------------------------------------------------------------------
# Identity (fallback)
# ---------------------------------------------------------------------------


class IdentityTransformer(BaseQueryTransformer):
    """Default fallback: passes the original query through unchanged.

    Used when no LLM API key is configured or all other transformers fail.
    Zero external dependencies.
    """

    async def transform(self, query_text: str) -> list[TransformedQuery]:
        return [TransformedQuery(text=query_text, route="direct")]


# ---------------------------------------------------------------------------
# Rewrite Transformer
# ---------------------------------------------------------------------------


class RewriteTransformer(BaseQueryTransformer):
    """Debiased query rewriter: cleaning, keyword expansion, and disambiguation.

    Uses LLM to produce a single cleaned query string.
    On any failure, silently degrades to IdentityTransformer output.
    """

    def __init__(
        self,
        generator: LLMGenerator,
        config: RewriteTransformerConfig | None = None,
    ) -> None:
        self._generator = generator
        self._config = config or RewriteTransformerConfig()

    async def transform(self, query_text: str) -> list[TransformedQuery]:
        try:
            rewritten = await self._generator.raw_chat(
                messages=[
                    {"role": "system", "content": _REWRITE_SYSTEM_PROMPT},
                    {"role": "user", "content": query_text},
                ],
                max_tokens=self._config.max_tokens,
                temperature=self._config.temperature,
            )
        except Exception:
            logger.warning(
                "RewriteTransformer failed for query=%r, falling back to identity",
                query_text, exc_info=True,
            )
            return _identity_fallback(query_text)

        cleaned = rewritten.strip()
        if not cleaned or cleaned == query_text:
            logger.debug(
                "RewriteTransformer produced null or identical output for query=%r",
                query_text,
            )
            return _identity_fallback(query_text)

        return [TransformedQuery(text=cleaned, route="direct")]


# ---------------------------------------------------------------------------
# RAG Fusion Transformer
# ---------------------------------------------------------------------------


class RAGFusionTransformer(BaseQueryTransformer):
    """Generates multiple rephrased query variants for diversity-aware retrieval.

    Produces up to num_variants semantically-equivalent queries with different
    wordings. All variants carry route="fusion". The QueryDispatcher embeds
    them in batch, runs parallel searches, and merges results via RRF.

    On any failure, silently degrades to IdentityTransformer output.
    """

    def __init__(
        self,
        generator: LLMGenerator,
        config: RAGFusionTransformerConfig | None = None,
    ) -> None:
        self._generator = generator
        self._config = config or RAGFusionTransformerConfig()

    async def transform(self, query_text: str) -> list[TransformedQuery]:
        try:
            raw = await self._generator.raw_chat(
                messages=[
                    {
                        "role": "system",
                        "content": _RAG_FUSION_SYSTEM_PROMPT.format(
                            num_variants=self._config.num_variants,
                        ),
                    },
                    {"role": "user", "content": query_text},
                ],
                max_tokens=self._config.max_tokens,
                temperature=self._config.temperature,
            )
        except Exception:
            logger.warning(
                "RAGFusionTransformer failed for query=%r, falling back to identity",
                query_text, exc_info=True,
            )
            return _identity_fallback(query_text)

        variants = _parse_variants(raw)
        if not variants:
            logger.warning(
                "RAGFusionTransformer produced no valid variants for query=%r",
                query_text,
            )
            return _identity_fallback(query_text)

        return [
            TransformedQuery(text=v, route="fusion")
            for v in variants
        ]


# ---------------------------------------------------------------------------
# HyDE Transformer
# ---------------------------------------------------------------------------


class HyDeTransformer(BaseQueryTransformer):
    """Hypothetical Document Embedding: generate a fake answer then search.

    Two-step process:
    1. LLM generates a hypothetical passage answering the query.
    2. The passage is embedded, and that vector drives retrieval.

    TransformedQuery.text preserves the original query (for logging/debugging).
    TransformedQuery.embedding carries the hypothetical passage vector.

    On any failure (LLM or embedding), silently degrades to Identity output.
    """

    def __init__(
        self,
        generator: LLMGenerator,
        embedder: BaseEmbedder,
        config: HyDeTransformerConfig | None = None,
    ) -> None:
        self._generator = generator
        self._embedder = embedder
        self._config = config or HyDeTransformerConfig()

    async def transform(self, query_text: str) -> list[TransformedQuery]:
        try:
            hypothesis = await self._generator.raw_chat(
                messages=[
                    {"role": "system", "content": _HYDE_SYSTEM_PROMPT},
                    {"role": "user", "content": query_text},
                ],
                max_tokens=self._config.max_tokens,
                temperature=self._config.temperature,
            )
        except Exception:
            logger.warning(
                "HyDeTransformer LLM step failed for query=%r, "
                "falling back to identity",
                query_text, exc_info=True,
            )
            return _identity_fallback(query_text)

        hypothesis = hypothesis.strip()
        if not hypothesis:
            logger.warning(
                "HyDeTransformer produced empty hypothesis for query=%r",
                query_text,
            )
            return _identity_fallback(query_text)

        try:
            vectors = await self._embedder.embed_batch([hypothesis])
            hyp_embedding = vectors[0]
        except Exception:
            logger.warning(
                "HyDeTransformer embedding step failed for query=%r, "
                "falling back to identity",
                query_text, exc_info=True,
            )
            return _identity_fallback(query_text)

        return [
            TransformedQuery(
                text=query_text,  # original query for logging/debugging
                route="hyde",
                embedding=hyp_embedding,
            )
        ]


# ---------------------------------------------------------------------------
# Composed Transformer (reserved for future use)
# ---------------------------------------------------------------------------


class ComposedTransformer(BaseQueryTransformer):
    """Runs multiple transformers concurrently and flattens their outputs.

    Enables mixed strategies (e.g. RAG-Fusion + HyDE) within a single
    dispatch call. Each sub-transformer executes independently; the merged
    list is passed to QueryDispatcher which already handles mixed routes.
    """

    def __init__(self, transformers: list[BaseQueryTransformer]) -> None:
        self._transformers = transformers

    async def transform(self, query_text: str) -> list[TransformedQuery]:
        results = await asyncio.gather(
            *[t.transform(query_text) for t in self._transformers],
        )
        return [q for sublist in results for q in sublist]


# ---------------------------------------------------------------------------
# Query Dispatcher (interface stub)
# ---------------------------------------------------------------------------


class QueryDispatcher:
    """Fan out TransformedQuery variants to the appropriate pipelines.

    Full dispatch logic is implemented in P1-8.  Current stub defines the
    public interface for planning / caller integration.

    Args:
        queries: Transformed query variants from a BaseQueryTransformer.
        original_context: PipelineContext pre-built for the original query
                          (contains original text and embedding).
        pipeline: Full retrieval pipeline wrapper (pipeline.py layer).
        embedder: Embedder for computing vectors on-demand.

    Returns:
        Merged list of SearchHit ready for hydration.
    """

    async def dispatch(
        self,
        queries: list[TransformedQuery],
        original_context: PipelineContext,
        pipeline: object,  # RetrievalPipeline — object to avoid circular import
        embedder: object,  # BaseEmbedder — object to avoid circular import
    ) -> list[SearchHit]:
        del queries, original_context, pipeline, embedder
        raise NotImplementedError(
            "QueryDispatcher.dispatch() will be implemented in P1-8 "
            "(query dispatching and routing)"
        )
