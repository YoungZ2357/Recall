from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

import httpx

from app.config import Settings
from app.core.exceptions import ConfigError, GenerationError
from app.core.schemas import GenerateResponse, RetrievalResult

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0

_SYSTEM_PROMPT = (
    "You are a helpful assistant. Answer the user's question based on the provided context. "
    "If the context does not contain enough information, say so honestly."
)


class LLMGenerator:
    """Async LLM client for OpenAI-compatible chat completions API."""

    def __init__(self, settings: Settings) -> None:
        if not settings.llm_api_key:
            raise ConfigError(message="llm_api_key is not configured")

        self._api_key: str = settings.llm_api_key
        self._model: str = settings.llm_model
        self._max_tokens: int = settings.llm_max_tokens
        self._temperature: float = settings.llm_temperature
        self._client = httpx.AsyncClient(
            base_url=settings.llm_base_url,
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=httpx.Timeout(60.0, connect=10.0),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate(
        self,
        query: str,
        context: list[RetrievalResult],
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> GenerateResponse:
        """Non-streaming generation. Returns complete response."""
        messages = self._build_messages(query, context)
        payload = {
            "model": self._model,
            "messages": messages,
            "max_tokens": max_tokens or self._max_tokens,
            "temperature": temperature if temperature is not None else self._temperature,
            "stream": False,
        }

        data = await self._post_with_retry(payload)

        choice = data["choices"][0]
        usage = data.get("usage")
        return GenerateResponse(
            answer=choice["message"]["content"],
            model=data.get("model", self._model),
            usage={
                "prompt_tokens": usage["prompt_tokens"],
                "completion_tokens": usage["completion_tokens"],
                "total_tokens": usage["total_tokens"],
            } if usage else None,
        )

    async def generate_stream(
        self,
        query: str,
        context: list[RetrievalResult],
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        """SSE streaming generation. Yields SSE-formatted strings."""
        messages = self._build_messages(query, context)
        payload = {
            "model": self._model,
            "messages": messages,
            "max_tokens": max_tokens or self._max_tokens,
            "temperature": temperature if temperature is not None else self._temperature,
            "stream": True,
        }

        try:
            async with self._client.stream(
                "POST", "/v1/chat/completions", json=payload,
            ) as resp:
                if resp.status_code != 200:
                    await resp.aread()
                    raise GenerationError(
                        message=f"LLM API returned HTTP {resp.status_code}",
                        detail=resp.text,
                    )

                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[len("data: "):]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    delta = chunk["choices"][0]["delta"].get("content", "")
                    if delta:
                        yield f"data: {json.dumps({'content': delta})}\n\n"

        except httpx.TransportError as exc:
            raise GenerationError(
                message="Network error when calling LLM API",
                detail=str(exc),
            ) from exc

        yield "data: [DONE]\n\n"

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_messages(
        self, query: str, context: list[RetrievalResult],
    ) -> list[dict[str, str]]:
        """Construct chat messages from context chunks and user query."""
        if context:
            context_text = "\n\n---\n\n".join(
                f"[{c.document_title or 'Untitled'}] (score: {c.final_score:.2f})\n{c.content}"
                for c in context
            )
            user_content = f"Context:\n{context_text}\n\nQuestion: {query}"
        else:
            user_content = query

        return [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

    async def _post_with_retry(self, payload: dict) -> dict:
        """POST to chat completions endpoint with retry on 429."""
        last_error: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.post(
                    "/v1/chat/completions", json=payload,
                )
            except httpx.TransportError as exc:
                raise GenerationError(
                    message="Network error when calling LLM API",
                    detail=str(exc),
                ) from exc

            if response.status_code == 429:
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "LLM API rate-limited (429). Retrying in %.1fs (attempt %d/%d)",
                    delay, attempt + 1, _MAX_RETRIES,
                )
                await asyncio.sleep(delay)
                last_error = GenerationError(
                    message="LLM API rate limit exceeded after retries",
                )
                continue

            if response.status_code != 200:
                raise GenerationError(
                    message=f"LLM API returned HTTP {response.status_code}",
                    detail=response.text,
                )

            return response.json()

        raise last_error or GenerationError(message="LLM API failed after retries")
