"""Predefined retrieval topology factories.

Each function builds a GraphSpec via GraphBuilder and returns a ready-to-execute
RetrievalPipeline. These are the only intended bridge between Settings/config values
and the operator layer; operators themselves never touch Settings.
"""

from __future__ import annotations

from app.core.pipeline_deps import PipelineDeps
from app.retrieval.configs import (
    BM25SearcherConfig,
    RerankerConfig,
    RRFMergerConfig,
    VectorSearcherConfig,
)
from app.retrieval.engine import RetrievalPipeline
from app.retrieval.graph import GraphBuilder
from app.retrieval.merger import RRFMerger
from app.retrieval.reranker import Reranker
from app.retrieval.searcher import BM25Searcher, VectorSearcher




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
        .add_node("retriever", retriever_cls, retriever_config)
        .add_node("reranker", Reranker, reranker_config)
        .add_edge("retriever", "reranker")
        .build(deps)
    )


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
        .add_node("vec", VectorSearcher, vector_config)
        .add_node("bm25", BM25Searcher, bm25_config)
        .add_node("merge", RRFMerger, rrf_config)
        .add_node("rerank", Reranker, reranker_config)
        .add_edges([
            ("vec",   "merge"),
            ("bm25",  "merge"),
            ("merge", "rerank"),
        ])
        .build(deps)
    )


