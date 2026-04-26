"""GenerationService — combines retrieval and LLM generation into one call.

Thin orchestration: search(context) → generator.generate().
Eliminates the need for callers to manually pipeline search + call LLMGenerator.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from app.core.schemas import GenerateResponse, RetrievalResult
from app.generation.generator import LLMGenerator
from app.services.search_service import SearchService

logger = logging.getLogger(__name__)


class GenerationService:
    """Orchestrate retrieval + LLM generation.

    Usage::

        gen_svc = GenerationService(search_service, generator)
        results, response = await gen_svc.search_and_generate("question?", top_k=5)
    """

    def __init__(
        self,
        search_service: SearchService,
        generator: LLMGenerator,
    ) -> None:
        self._search = search_service
        self._generator = generator

    async def search_and_generate(
        self,
        query: str,
        top_k: int = 5,
        mode: str = "prefer_recent",
        gen_mode: str = "strict",
    ) -> tuple[list[RetrievalResult], GenerateResponse]:
        """Retrieve context then generate an answer (non-streaming).

        Returns:
            (retrieved_chunks, generated_response)
        """
        results = await self._search.search(
            query_text=query,
            top_k=top_k,
            retention_mode=mode,
        )
        response = await self._generator.generate(query, results, gen_mode=gen_mode)
        return results, response

    async def search_and_generate_stream(
        self,
        query: str,
        top_k: int = 5,
        mode: str = "prefer_recent",
        gen_mode: str = "strict",
    ) -> tuple[list[RetrievalResult], AsyncIterator[str]]:
        """Retrieve context then stream the answer token-by-token.

        Returns:
            (retrieved_chunks, sse_stream_iterator)
        """
        results = await self._search.search(
            query_text=query,
            top_k=top_k,
            retention_mode=mode,
        )
        stream = self._generator.generate_stream(query, results, gen_mode=gen_mode)
        return results, stream
