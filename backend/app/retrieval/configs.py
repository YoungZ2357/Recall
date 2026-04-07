"""Configuration models for retrieval pipeline operators.

All fields have defaults matching the original hardcoded / Settings defaults,
so operators work correctly with `Config()` (no arguments required).
"""

from typing import Literal

from pydantic import BaseModel


class VectorSearcherConfig(BaseModel, frozen=True):
    score_threshold: float = 0.35
    top_k: int = 10
    collection_name: str = "recall"


class BM25SearcherConfig(BaseModel, frozen=True):
    score_threshold: float = 0.35
    top_k: int = 10
    recall_multiplier: int = 2


class RerankerConfig(BaseModel, frozen=True):
    alpha: float = 0.6
    beta: float = 0.2
    gamma: float = 0.2
    score_threshold: float = 0.60
    retention_mode: Literal["prefer_recent", "awaken_forgotten"] = "prefer_recent"
    s_base: float = 24.0
    tag_fallback: float = 0.5


class RRFMergerConfig(BaseModel, frozen=True):
    k: int = 60
