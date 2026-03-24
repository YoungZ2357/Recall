"""分块模块：将解析后的纯文本按策略切分为 ChunkData 列表，供 embedder 下游消费。"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from app.core.exceptions import IngestionError

logger = logging.getLogger(__name__)

# Separators tried in order from coarsest to finest
DEFAULT_SEPARATORS = ["\n\n", "\n", "。", ".", "；", ";", "，", ",", " ", ""]


# ============================================================
# Data Transfer Object
# ============================================================

@dataclass
class ChunkData:
    """单个 chunk 的数据容器，由分块策略产出，传递给 embedder。"""

    content: str
    chunk_index: int
    metadata: dict[str, Any] = field(default_factory=dict)


# ============================================================
# Abstract Base
# ============================================================

@dataclass
class BaseChunker(ABC):
    """所有分块策略的抽象基类。"""

    strategy_name: ClassVar[str]

    @abstractmethod
    def split(self, text: str, metadata: dict[str, Any] | None = None) -> list[ChunkData]:
        """将文本切分为 ChunkData 列表。

        Args:
            text: 待切分的纯文本。
            metadata: 附加到每个 chunk 的元数据（来自 parser）。

        Returns:
            ChunkData 列表；text 为空时返回空列表。
        """
        ...

    def _guard_empty(self, text: str | None) -> bool:
        """Return True if text is empty / None (caller should return [])."""
        return not text or not text.strip()


# ============================================================
# RecursiveSplitStrategy
# ============================================================

@dataclass
class RecursiveSplitStrategy(BaseChunker):
    """递归分隔符分块策略：从粗粒度分隔符向细粒度回退，保证每个 chunk 不超过 chunk_size。"""

    strategy_name: ClassVar[str] = "recursive"

    chunk_size: int = 512
    chunk_overlap: int = 64
    separators: list[str] | None = None
    min_chunk_size: int = 50

    def split(self, text: str, metadata: dict[str, Any] | None = None) -> list[ChunkData]:
        """将文本按递归分隔符策略切分，追加 overlap，并合并尾部碎片。"""
        if self._guard_empty(text):
            return []

        seps = self.separators if self.separators is not None else DEFAULT_SEPARATORS
        raw_chunks = self._recursive_split(text, seps)

        # Apply overlap
        actual_overlap = min(self.chunk_overlap, int(self.chunk_size * 0.4))
        merged = self._apply_overlap(raw_chunks, actual_overlap)

        # Merge trailing fragment
        if len(merged) > 1 and len(merged[-1]) < self.min_chunk_size:
            merged[-2] = merged[-2] + merged[-1]
            merged = merged[:-1]

        base_meta = dict(metadata) if metadata else {}
        chunks = [
            ChunkData(
                content=c,
                chunk_index=i,
                metadata={
                    **base_meta,
                    "chunk_strategy": self.strategy_name,
                    "chunk_size_configured": self.chunk_size,
                    "char_count": len(c),
                },
            )
            for i, c in enumerate(merged)
        ]
        logger.debug(
            "RecursiveSplitStrategy produced %d chunks (chunk_size=%d, overlap=%d)",
            len(chunks),
            self.chunk_size,
            actual_overlap,
        )
        return chunks

    def _recursive_split(self, text: str, separators: list[str]) -> list[str]:
        """Recursively split text using separators from coarsest to finest."""
        if not separators:
            # Hard-cut fallback when all separators are exhausted
            return self._hard_cut(text)

        sep = separators[0]

        # Empty string separator: hard-cut by chunk_size
        if sep == "":
            return self._hard_cut(text)

        fragments = [f for f in text.split(sep) if f]

        result: list[str] = []
        current: list[str] = []
        current_len = 0

        for frag in fragments:
            frag_len = len(frag)

            if frag_len > self.chunk_size:
                # Flush current accumulation first
                if current:
                    result.append(sep.join(current))
                    current = []
                    current_len = 0
                # Recurse into sub-separators
                sub = self._recursive_split(frag, separators[1:])
                result.extend(sub)
            elif current_len + len(sep) + frag_len > self.chunk_size and current:
                result.append(sep.join(current))
                current = [frag]
                current_len = frag_len
            else:
                current.append(frag)
                current_len += (len(sep) if current_len > 0 else 0) + frag_len

        if current:
            result.append(sep.join(current))

        return result if result else [text]

    def _hard_cut(self, text: str) -> list[str]:
        """Hard-cut text into chunks of chunk_size characters."""
        return [text[i: i + self.chunk_size] for i in range(0, len(text), self.chunk_size)]

    def _apply_overlap(self, chunks: list[str], overlap: int) -> list[str]:
        """Prepend the tail of the previous chunk to each subsequent chunk."""
        if overlap <= 0 or len(chunks) <= 1:
            return chunks
        result = [chunks[0]]
        for i in range(1, len(chunks)):
            tail = chunks[i - 1][-overlap:]
            result.append(tail + chunks[i])
        return result


# ============================================================
# FixedCountStrategy
# ============================================================

@dataclass
class FixedCountStrategy(BaseChunker):
    """固定数量分块策略：尽量将文本切成 target_chunks 个大小相近的 chunk。"""

    strategy_name: ClassVar[str] = "fixed_count"

    target_chunks: int = 10
    max_chunk_size: int = 1024
    min_doc_size: int = 256
    overlap_ratio: float = 0.1
    min_overlap: int = 50
    max_overlap: int = 200
    min_split_size: int = 50

    def split(self, text: str, metadata: dict[str, Any] | None = None) -> list[ChunkData]:
        """将文本切分为接近 target_chunks 个 chunk，尾部碎片合并到前一个。"""
        if self._guard_empty(text):
            return []

        doc_len = len(text)
        base_chunk_size = doc_len // self.target_chunks if self.target_chunks > 0 else doc_len

        # Short document: return as single chunk
        if doc_len <= self.min_doc_size or base_chunk_size < 20:
            base_meta = dict(metadata) if metadata else {}
            return [
                ChunkData(
                    content=text,
                    chunk_index=0,
                    metadata={
                        **base_meta,
                        "chunk_strategy": self.strategy_name,
                        "chunk_size_configured": doc_len,
                        "char_count": doc_len,
                    },
                )
            ]

        actual_chunk_size = min(base_chunk_size, self.max_chunk_size)

        # Compute overlap, clamped to [min_overlap, max_overlap]
        raw_overlap = int(actual_chunk_size * self.overlap_ratio)
        actual_overlap = max(self.min_overlap, min(raw_overlap, self.max_overlap))

        # Overlap must be strictly less than chunk size
        if actual_overlap >= actual_chunk_size:
            actual_overlap = 0

        step = actual_chunk_size - actual_overlap
        chunks_text: list[str] = []
        start = 0
        while start < doc_len:
            end = start + actual_chunk_size
            chunks_text.append(text[start:end])
            if end >= doc_len:
                break
            start += step

        # Merge trailing fragment
        if len(chunks_text) > 1 and len(chunks_text[-1]) < self.min_split_size:
            chunks_text[-2] = chunks_text[-2] + chunks_text[-1]
            chunks_text = chunks_text[:-1]

        base_meta = dict(metadata) if metadata else {}
        chunks = [
            ChunkData(
                content=c,
                chunk_index=i,
                metadata={
                    **base_meta,
                    "chunk_strategy": self.strategy_name,
                    "chunk_size_configured": actual_chunk_size,
                    "char_count": len(c),
                },
            )
            for i, c in enumerate(chunks_text)
        ]
        logger.debug(
            "FixedCountStrategy produced %d chunks (target=%d, actual_size=%d, overlap=%d)",
            len(chunks),
            self.target_chunks,
            actual_chunk_size,
            actual_overlap,
        )
        return chunks


# ============================================================
# Factory
# ============================================================

_STRATEGY_MAP: dict[str, type[BaseChunker]] = {
    "recursive": RecursiveSplitStrategy,
    "fixed_count": FixedCountStrategy,
}


def get_chunker(strategy: str = "recursive", **kwargs: Any) -> BaseChunker:
    """根据策略名称返回对应的分块器实例。

    Args:
        strategy: 策略名称，支持 "recursive" 和 "fixed_count"。
        **kwargs: 传递给具体策略类的构造参数。

    Returns:
        BaseChunker 实例。

    Raises:
        IngestionError: 不支持的策略名称。
    """
    if strategy not in _STRATEGY_MAP:
        raise IngestionError(f"不支持的分块策略：{strategy}")
    return _STRATEGY_MAP[strategy](**kwargs)
