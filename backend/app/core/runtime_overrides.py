"""Runtime override manager for API keys.

Snapshots .env-loaded API keys at startup, then allows runtime override of the
shared Settings singleton. Restart restores the .env baseline because the
manager is rebuilt fresh in the FastAPI lifespan.
"""

from __future__ import annotations

from typing import Literal

from app.config import Settings

KeySource = Literal["env", "override", "missing"]

# Pydantic field names on Settings that this manager governs.
_OVERRIDABLE_FIELDS: tuple[str, ...] = (
    "embedding_api_key",
    "llm_api_key",
    "mineru_api_key",
)


class RuntimeOverrideManager:
    """Track which API-key fields are currently runtime-overridden and their baseline values."""

    def __init__(self, settings: Settings) -> None:
        self._baseline: dict[str, str | None] = {
            field: getattr(settings, field) for field in _OVERRIDABLE_FIELDS
        }
        self._overridden: set[str] = set()

    @property
    def overridable_fields(self) -> tuple[str, ...]:
        return _OVERRIDABLE_FIELDS

    def baseline(self, field: str) -> str | None:
        return self._baseline[field]

    def is_overridden(self, field: str) -> bool:
        return field in self._overridden

    def source(self, settings: Settings, field: str) -> KeySource:
        if field in self._overridden:
            return "override"
        return "env" if getattr(settings, field) else "missing"

    def status(self, settings: Settings) -> dict[str, KeySource]:
        return {field: self.source(settings, field) for field in _OVERRIDABLE_FIELDS}

    def apply(
        self,
        settings: Settings,
        **new_values: str | None,
    ) -> dict[str, str | None]:
        """Apply overrides to the Settings singleton. Return only the fields that changed.

        A value of None means "skip this field". To clear a single field back to baseline
        use clear_field() — this method only sets fresh values.
        """
        changed: dict[str, str | None] = {}
        for field, value in new_values.items():
            if field not in _OVERRIDABLE_FIELDS:
                raise ValueError(f"Unknown overridable field: {field}")
            if value is None:
                continue
            current = getattr(settings, field)
            if current != value:
                setattr(settings, field, value)
                changed[field] = value
            self._overridden.add(field)
        return changed

    def clear(self, settings: Settings) -> dict[str, str | None]:
        """Restore all overridden fields to their .env baseline. Return changed fields."""
        changed: dict[str, str | None] = {}
        for field in list(self._overridden):
            baseline = self._baseline[field]
            if getattr(settings, field) != baseline:
                setattr(settings, field, baseline)
                changed[field] = baseline
        self._overridden.clear()
        return changed
