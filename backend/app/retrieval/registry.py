"""Operator registry for the retrieval DAG system.

Maps node_type strings (as used in JSON pipeline definitions) to their
corresponding Python classes, Pydantic config classes, and metadata.

Constraint:
    Do NOT use __init__.py re-exports. Callers import via full module path:
        from app.retrieval.registry import get_node_type, list_node_types

Note: Heavy third-party imports (searcher, reranker, merger) are deferred
      to break circular import chains through repository.py and schemas.py.
"""

from dataclasses import dataclass

from app.retrieval.configs import (
    BM25SearcherConfig,
    ContextualBM25SearcherConfig,
    RerankerConfig,
    RRFMergerConfig,
    VectorSearcherConfig,
)


@dataclass(frozen=True)
class NodeTypeInfo:
    """Immutable descriptor for a single pipeline operator type."""

    node_type: str
    node_cls: type | None
    config_cls: type | None
    node_role: str
    display_name: str
    available: bool = True


_registry: dict[str, NodeTypeInfo] | None = None


def _build_registry() -> dict[str, NodeTypeInfo]:
    from app.retrieval.merger import RRFMerger
    from app.retrieval.reranker import Reranker
    from app.retrieval.searcher import BM25Searcher, ContextualBM25Searcher, VectorSearcher

    return {
        "VectorSearcher": NodeTypeInfo(
            node_type="VectorSearcher",
            node_cls=VectorSearcher,
            config_cls=VectorSearcherConfig,
            node_role="SOURCE",
            display_name="Vector Searcher",
        ),
        "BM25Searcher": NodeTypeInfo(
            node_type="BM25Searcher",
            node_cls=BM25Searcher,
            config_cls=BM25SearcherConfig,
            node_role="SOURCE",
            display_name="BM25 Searcher",
        ),
        "ContextualBM25Searcher": NodeTypeInfo(
            node_type="ContextualBM25Searcher",
            node_cls=ContextualBM25Searcher,
            config_cls=ContextualBM25SearcherConfig,
            node_role="SOURCE",
            display_name="Contextual BM25 Searcher",
        ),
        "RRFMerger": NodeTypeInfo(
            node_type="RRFMerger",
            node_cls=RRFMerger,
            config_cls=RRFMergerConfig,
            node_role="MERGE",
            display_name="RRF Merger",
        ),
        "Reranker": NodeTypeInfo(
            node_type="Reranker",
            node_cls=Reranker,
            config_cls=RerankerConfig,
            node_role="TRANSFORM",
            display_name="Reranker",
        ),
        "QueryRewriter": NodeTypeInfo(
            node_type="QueryRewriter",
            node_cls=None,
            config_cls=None,
            node_role="SOURCE",
            display_name="Query Rewriter",
            available=False,
        ),
    }


def _get_registry() -> dict[str, NodeTypeInfo]:
    global _registry
    if _registry is None:
        _registry = _build_registry()
    return _registry


def get_node_type(name: str) -> NodeTypeInfo:
    """Look up a node type by registered name.

    Args:
        name: The node_type string (e.g. "VectorSearcher").

    Returns:
        Matching NodeTypeInfo.

    Raises:
        KeyError: If the name is not found in the registry.
    """
    reg = _get_registry()
    try:
        return reg[name]
    except KeyError:
        available_names = ", ".join(sorted(reg))
        raise KeyError(
            f"Unknown node type {name!r}. Available types: {available_names}"
        ) from None


def list_node_types() -> list[NodeTypeInfo]:
    """Return all registered entries, including unavailable ones."""
    return list(_get_registry().values())


def list_available_node_types() -> list[NodeTypeInfo]:
    """Return only entries where available=True."""
    return [info for info in _get_registry().values() if info.available]


if __name__ == "__main__":
    for info in list_node_types():
        print(f"{info.node_type}: available={info.available}")
