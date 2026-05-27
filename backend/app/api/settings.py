"""Settings API — runtime override of API keys backed by RuntimeOverrideManager."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, SecretStr

from app.api.dependencies import SettingsDep
from app.config import Settings
from app.core.exceptions import (
    ConfigError,
    EmbeddingError,
    GenerationError,
    RecallError,
)
from app.core.runtime_overrides import KeySource, RuntimeOverrideManager
from app.generation.generator import LLMGenerator
from app.ingestion.embedder import APIEmbedder

logger = logging.getLogger(__name__)

router = APIRouter()


class ApiKeyValidationError(RecallError):
    """The supplied API key was rejected by its provider during liveness check."""

    status_code = 400
    message = "API key validation failed"


class ApplyKeysRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    embedding_api_key: SecretStr | None = None
    llm_api_key: SecretStr | None = None
    mineru_api_key: SecretStr | None = None


class KeyStatusResponse(BaseModel):
    embedding_api_key: KeySource
    llm_api_key: KeySource
    mineru_api_key: KeySource


def _get_manager(request: Request) -> RuntimeOverrideManager:
    return request.app.state.overrides


ManagerDep = Annotated[RuntimeOverrideManager, Depends(_get_manager)]


@router.get("/api-keys/status", response_model=KeyStatusResponse)
async def get_status(
    manager: ManagerDep,
    settings: SettingsDep,
) -> KeyStatusResponse:
    return KeyStatusResponse(**manager.status(settings))


@router.post("/api-keys", response_model=KeyStatusResponse)
async def apply_keys(
    payload: ApplyKeysRequest,
    request: Request,
    manager: ManagerDep,
    settings: SettingsDep,
) -> KeyStatusResponse:
    """Validate and commit runtime overrides for the supplied API keys.

    Liveness check runs before any mutation. If any key is rejected, the whole
    request fails atomically and no override is applied.
    """
    candidates: dict[str, str] = {}
    if payload.embedding_api_key is not None:
        candidates["embedding_api_key"] = payload.embedding_api_key.get_secret_value()
    if payload.llm_api_key is not None:
        candidates["llm_api_key"] = payload.llm_api_key.get_secret_value()
    if payload.mineru_api_key is not None:
        candidates["mineru_api_key"] = payload.mineru_api_key.get_secret_value()

    if not candidates:
        raise ApiKeyValidationError(message="No API key provided")

    if "embedding_api_key" in candidates:
        await _validate_embedding_key(settings, candidates["embedding_api_key"])
    if "llm_api_key" in candidates:
        await _validate_llm_key(settings, candidates["llm_api_key"])

    manager.apply(settings, **candidates)
    if "embedding_api_key" in candidates:
        await _swap_embedder(request, settings)
    if "llm_api_key" in candidates:
        await _swap_generator(request, settings)

    logger.info("Applied runtime API-key overrides: %s", sorted(candidates.keys()))
    return KeyStatusResponse(**manager.status(settings))


@router.delete("/api-keys", response_model=KeyStatusResponse)
async def clear_keys(
    request: Request,
    manager: ManagerDep,
    settings: SettingsDep,
) -> KeyStatusResponse:
    """Restore all overridden keys back to their .env baseline and rebuild affected clients."""
    cleared_fields = {f for f in manager.overridable_fields if manager.is_overridden(f)}
    manager.clear(settings)

    if "embedding_api_key" in cleared_fields:
        await _swap_embedder(request, settings)
    if "llm_api_key" in cleared_fields:
        await _swap_generator(request, settings)

    logger.info("Cleared runtime API-key overrides: %s", sorted(cleared_fields))
    return KeyStatusResponse(**manager.status(settings))


# ----------------------------------------------------------------------
# Internal helpers — liveness checks and hot-swap.
# ----------------------------------------------------------------------


async def _validate_embedding_key(settings: Settings, candidate_key: str) -> None:
    probe_settings = settings.model_copy(update={"embedding_api_key": candidate_key})
    probe = APIEmbedder(probe_settings)
    try:
        await probe.embed_batch(["ping"])
    except (EmbeddingError, ConfigError) as exc:
        raise ApiKeyValidationError(
            message="Embedding API key rejected by provider",
            detail=str(exc),
        ) from exc
    finally:
        await probe.aclose()


async def _validate_llm_key(settings: Settings, candidate_key: str) -> None:
    probe_settings = settings.model_copy(update={"llm_api_key": candidate_key})
    probe = LLMGenerator(probe_settings)
    try:
        await probe.raw_chat(
            [{"role": "user", "content": "ping"}],
            max_tokens=1,
        )
    except (GenerationError, ConfigError) as exc:
        raise ApiKeyValidationError(
            message="LLM API key rejected by provider",
            detail=str(exc),
        ) from exc
    finally:
        await probe.aclose()


async def _swap_embedder(request: Request, settings: Settings) -> None:
    old: APIEmbedder = request.app.state.embedder
    new = APIEmbedder(settings)
    request.app.state.embedder = new
    await old.aclose()


async def _swap_generator(request: Request, settings: Settings) -> None:
    old: LLMGenerator | None = request.app.state.generator
    new: LLMGenerator | None = LLMGenerator(settings) if settings.llm_api_key else None
    request.app.state.generator = new
    if old is not None:
        await old.aclose()
