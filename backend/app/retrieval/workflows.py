"""Predefined retrieval topology factories.

Each function builds a GraphSpec via GraphBuilder and returns a ready-to-execute
RetrievalPipeline. These are the only intended bridge between Settings/config values
and the operator layer; operators themselves never touch Settings.
"""

from __future__ import annotations

from app.config import settings as _settings
from app.core.pipeline_deps import PipelineDeps
from app.retrieval.configs import (
    BM25SearcherConfig,
    ContextualBM25SearcherConfig,
    RerankerConfig,
    RRFMergerConfig,
    VectorSearcherConfig,
)
from app.retrieval.engine import RetrievalPipeline
from app.retrieval.graph import GraphBuilder, GraphSpec
from app.retrieval.merger import RRFMerger
from app.retrieval.registry import list_node_types
from app.retrieval.reranker import Reranker
from app.retrieval.searcher import BM25Searcher, ContextualBM25Searcher, VectorSearcher
from app.retrieval.topology import TopologySpecJSON


def _reranker_config_from_settings() -> RerankerConfig:
    return RerankerConfig(
        alpha=_settings.reranker_alpha,
        beta=_settings.reranker_beta,
        gamma=_settings.reranker_gamma,
        s_base=_settings.reranker_s_base,
        tag_fallback=_settings.reranker_tag_fallback,
        score_threshold=_settings.reranker_score_threshold,
    )


def _vector_config_from_settings() -> VectorSearcherConfig:
    return VectorSearcherConfig(
        score_threshold=_settings.vector_score_threshold,
        collection_name=_settings.qdrant_collection,
    )


def _bm25_config_from_settings() -> BM25SearcherConfig:
    return BM25SearcherConfig(
        score_threshold=_settings.vector_score_threshold,
    )


def _rrf_config_from_settings() -> RRFMergerConfig:
    return RRFMergerConfig(k=_settings.rrf_k)


def _contextual_bm25_config_from_settings() -> ContextualBM25SearcherConfig:
    return ContextualBM25SearcherConfig(
        score_threshold=_settings.vector_score_threshold,
    )



def linear(
    deps: PipelineDeps,
    retriever_cls: type = VectorSearcher,
    retriever_config: VectorSearcherConfig | None = None,
    reranker_config: RerankerConfig | None = None,
) -> RetrievalPipeline:
    """Single-retriever → Reranker topology.

    Topology: retriever ─ Normalizer ─ reranker ─ Normalizer
    """
    return (
        GraphBuilder()
        .add_node("retriever", retriever_cls, retriever_config or _vector_config_from_settings())
        .add_node("reranker", Reranker, reranker_config or _reranker_config_from_settings())
        .add_edge("retriever", "reranker")
        .build(deps)
    )


def linear_spec(
    retriever_cls: type = VectorSearcher,
    retriever_config: VectorSearcherConfig | None = None,
    reranker_config: RerankerConfig | None = None,
) -> GraphSpec:
    return (
        GraphBuilder()
        .add_node("retriever", retriever_cls, retriever_config or _vector_config_from_settings())
        .add_node("reranker", Reranker, reranker_config or _reranker_config_from_settings())
        .add_edge("retriever", "reranker")
    ).spec


def hybrid(
    deps: PipelineDeps,
    vector_config: VectorSearcherConfig | None = None,
    bm25_config: BM25SearcherConfig | None = None,
    rrf_config: RRFMergerConfig | None = None,
    reranker_config: RerankerConfig | None = None,
) -> RetrievalPipeline:
    """Dual-retriever hybrid search: VectorSearcher + BM25 → RRF → Reranker.

    Topology:
        vec  ─ Normalizer ─┐
                            ├─ RRFMerger ─ Normalizer ─ reranker ─ Normalizer
        bm25 ─ Normalizer ─┘
    """
    return (
        GraphBuilder()
        .add_node("vec", VectorSearcher, vector_config or _vector_config_from_settings())
        .add_node("bm25", BM25Searcher, bm25_config or _bm25_config_from_settings())
        .add_node("merge", RRFMerger, rrf_config or _rrf_config_from_settings())
        .add_node("rerank", Reranker, reranker_config or _reranker_config_from_settings())
        .add_edges([
            ("vec",   "merge"),
            ("bm25",  "merge"),
            ("merge", "rerank"),
        ])
        .build(deps)
    )


def hybrid_spec(
    vector_config: VectorSearcherConfig | None = None,
    bm25_config: BM25SearcherConfig | None = None,
    rrf_config: RRFMergerConfig | None = None,
    reranker_config: RerankerConfig | None = None,
) -> GraphSpec:
    return (
        GraphBuilder()
        .add_node("vec", VectorSearcher, vector_config or _vector_config_from_settings())
        .add_node("bm25", BM25Searcher, bm25_config or _bm25_config_from_settings())
        .add_node("merge", RRFMerger, rrf_config or _rrf_config_from_settings())
        .add_node("rerank", Reranker, reranker_config or _reranker_config_from_settings())
        .add_edges([
            ("vec",   "merge"),
            ("bm25",  "merge"),
            ("merge", "rerank"),
        ])
    ).spec


def hybrid_contextual_bm25(
    deps: PipelineDeps,
    vector_config: VectorSearcherConfig | None = None,
    c_bm25_config: ContextualBM25SearcherConfig | None = None,
    rrf_config: RRFMergerConfig | None = None,
    reranker_config: RerankerConfig | None = None,
) -> RetrievalPipeline:
    """Dual-retriever hybrid search: VectorSearcher + BM25 → RRF → Reranker.

    Topology:
        vec             ─ Normalizer ─┐
                                      ├─ RRFMerger ─ Normalizer ─ reranker ─ Normalizer
        contextual_bm25 ─ Normalizer ─┘
    """
    return (
        GraphBuilder()
        .add_node("vector", VectorSearcher, vector_config or _vector_config_from_settings())
        .add_node(
            "c_bm25",
            ContextualBM25Searcher,
            c_bm25_config or _contextual_bm25_config_from_settings(),
        )
        .add_node("merge", RRFMerger, rrf_config or _rrf_config_from_settings())
        .add_node("rerank", Reranker, reranker_config or _reranker_config_from_settings())
        .add_edges([
            ("vector", "merge"),
            ("c_bm25", "merge"),
            ("merge", "rerank"),
        ])
        .build(deps)
    )


def hybrid_contextual_bm25_spec(
    vector_config: VectorSearcherConfig | None = None,
    c_bm25_config: ContextualBM25SearcherConfig | None = None,
    rrf_config: RRFMergerConfig | None = None,
    reranker_config: RerankerConfig | None = None,
) -> GraphSpec:
    return (
        GraphBuilder()
        .add_node("vector", VectorSearcher, vector_config or _vector_config_from_settings())
        .add_node(
            "c_bm25",
            ContextualBM25Searcher,
            c_bm25_config or _contextual_bm25_config_from_settings(),
        )
        .add_node("merge", RRFMerger, rrf_config or _rrf_config_from_settings())
        .add_node("rerank", Reranker, reranker_config or _reranker_config_from_settings())
        .add_edges([
            ("vector", "merge"),
            ("c_bm25", "merge"),
            ("merge", "rerank"),
        ])
    ).spec


def full_hybrid(
    deps: PipelineDeps,
    vector_config: VectorSearcherConfig | None = None,
    bm25_config: BM25SearcherConfig | None = None,
    c_bm25_config: ContextualBM25SearcherConfig | None = None,
    rrf_config: RRFMergerConfig | None = None,
    reranker_config: RerankerConfig | None = None,
) -> RetrievalPipeline:
    """Triple-retriever hybrid: VectorSearcher + BM25 + ContextualBM25 → RRF → Reranker.

    hits_list index for RRFMergerConfig.weights alignment:
        0 → VectorSearcher
        1 → BM25Searcher
        2 → ContextualBM25Searcher
    """
    return (
        GraphBuilder()
        .add_node("vec", VectorSearcher, vector_config or _vector_config_from_settings())
        .add_node("bm25", BM25Searcher, bm25_config or _bm25_config_from_settings())
        .add_node(
            "c_bm25",
            ContextualBM25Searcher,
            c_bm25_config or _contextual_bm25_config_from_settings(),
        )
        .add_node("merge", RRFMerger, rrf_config or _rrf_config_from_settings())
        .add_node(
            "rerank",
            Reranker,
            reranker_config or _reranker_config_from_settings(),
        )
        .add_edges([
            ("vec",    "merge"),
            ("bm25",   "merge"),
            ("c_bm25", "merge"),
            ("merge",  "rerank"),
        ])
        .build(deps)
    )


def builtin_topology_seeds() -> list[dict]:
    registry = {info.node_type: info for info in list_node_types()}
    specs = [
        ("linear", "Single vector search path", linear_spec()),
        ("hybrid", "Vector + BM25 with RRF fusion", hybrid_spec()),
        (
            "hybrid_contextual_bm25",
            "Vector + BM25 + ContextualBM25 with RRF fusion",
            hybrid_contextual_bm25_spec(),
        ),
    ]
    seeds: list[dict] = []
    for name, description, graph_spec in specs:
        topo_json = TopologySpecJSON.from_graph_spec(graph_spec, registry)
        seeds.append({
            "name": name,
            "description": description,
            "spec_json": topo_json.model_dump_json(),
            "is_builtin": True,
        })
    return seeds


def build_from_settings(deps: PipelineDeps) -> RetrievalPipeline:
    """Build a RetrievalPipeline using the topology specified in Settings.topology_mode."""
    match _settings.topology_mode:
        case "linear":
            return linear(deps)
        case "hybrid":
            return hybrid(deps)
        case "hybrid_contextual_bm25":
            return hybrid_contextual_bm25(deps)
        case "full_hybrid":
            return full_hybrid(deps)
