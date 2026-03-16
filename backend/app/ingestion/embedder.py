from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod

import httpx

from app.config import Settings
from app.core.exceptions import (
    ConfigError,
    EmbeddingDimensionMismatchError,
    EmbeddingError,
)

logger = logging.getLogger(__name__)

_BATCH_SIZE = 25
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 1.0

_GLM_EMBEDDINGS_URL = "https://open.bigmodel.cn/api/paas/v4/embeddings"


class BaseEmbedder(ABC):
    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...

    @property
    @abstractmethod
    def dimension(self) -> int: ...


class APIEmbedder(BaseEmbedder):
    def __init__(self, settings: Settings) -> None:
        if not settings.embedding_api_key:
            raise ConfigError(message="embedding_api_key is not configured")

        self._api_key: str = settings.embedding_api_key
        self._model: str = settings.embedding_model
        self._dimension: int = settings.embedding_dimension
        self._client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=30.0,
        )

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed texts in batches, return vectors in input order."""
        all_vectors: list[tuple[int, list[float]]] = []

        for batch_start in range(0, len(texts), _BATCH_SIZE):
            batch = texts[batch_start : batch_start + _BATCH_SIZE]
            vectors = await self._call_api(batch)
            for local_idx, vec in enumerate(vectors):
                all_vectors.append((batch_start + local_idx, vec))

        all_vectors.sort(key=lambda x: x[0])
        return [vec for _, vec in all_vectors]

    async def _call_api(self, batch: list[str]) -> list[list[float]]:
        """POST a single batch to GLM embedding endpoint with retry on 429."""
        last_error: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.post(
                    _GLM_EMBEDDINGS_URL,
                    json={"model": self._model, "input": batch},
                )
            except httpx.TransportError as exc:
                raise EmbeddingError(
                    message="Network error when calling embedding API",
                    detail=str(exc),
                ) from exc

            if response.status_code == 429:
                delay = _RETRY_BASE_DELAY * (2**attempt)
                logger.warning(
                    "Embedding API rate-limited (429). Retrying in %.1fs (attempt %d/%d)",
                    delay,
                    attempt + 1,
                    _MAX_RETRIES,
                )
                await asyncio.sleep(delay)
                last_error = EmbeddingError(
                    message="Embedding API rate limit exceeded after retries"
                )
                continue

            if response.status_code != 200:
                raise EmbeddingError(
                    message=f"Embedding API returned HTTP {response.status_code}",
                    detail=response.text,
                )

            data = response.json()
            vectors: list[list[float]] = []
            for item in sorted(data["data"], key=lambda x: x["index"]):
                vec: list[float] = item["embedding"]
                if len(vec) != self._dimension:
                    raise EmbeddingDimensionMismatchError(
                        expected=self._dimension,
                        actual=len(vec),
                    )
                vectors.append(vec)
            return vectors

        raise last_error or EmbeddingError(message="Embedding API failed after retries")

    async def aclose(self) -> None:
        """Close the underlying HTTP client. Call during app lifespan shutdown."""
        await self._client.aclose()
