"""DAG graph definition, validation, optimization, and normalizer injection.

Public API:
    NodeSpec      — immutable logical node descriptor
    GraphSpec     — nodes + edges
    GraphBuilder  — fluent builder; .build(deps) returns a RetrievalPipeline
    Normalizer    — internal normalization operator (injected automatically)
    validate()    — topology checks; raises on first violation
    optimize()    — optimization pass placeholder (identity)
    inject_normalizers() — auto-insert Normalizer after every SOURCE/TRANSFORM/MERGE node
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.retrieval.operators import (
    BaseMerger,
    BaseReranker,
    BaseRetriever,
    NodeType,
    SearchHit,
)
from app.retrieval.searcher import normalize_scores

if TYPE_CHECKING:
    from app.core.pipeline_deps import PipelineDeps
    from app.retrieval.engine import RetrievalPipeline


# ---------------------------------------------------------------------------
# Graph exceptions
# ---------------------------------------------------------------------------

class DuplicateNodeError(ValueError):
    """Raised when a node_id is added more than once."""


class UnknownNodeError(ValueError):
    """Raised when an edge references a node_id not present in the graph."""


class GraphCycleError(ValueError):
    """Raised when the graph contains a directed cycle."""


class TopologyError(ValueError):
    """Raised when node in-/out-degree constraints are violated."""


class ManualNormalizerError(ValueError):
    """Raised when a user attempts to manually add a Normalizer node."""


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NodeSpec:
    """Logical node descriptor. Describes what a node *is*, not an instance."""

    node_id: str
    node_type: NodeType
    node_cls: type
    config: Any = None


@dataclass
class GraphSpec:
    """Logical graph: node registry + directed edge list."""

    nodes: dict[str, NodeSpec] = field(default_factory=dict)
    edges: list[tuple[str, str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal Normalizer operator
# ---------------------------------------------------------------------------

class Normalizer:
    """Auto-injected score normalization operator. Stateless; no deps or config."""

    node_type = NodeType.NORMALIZER

    async def execute(self, hits: list[SearchHit]) -> list[SearchHit]:
        return normalize_scores(hits)


# ---------------------------------------------------------------------------
# GraphBuilder
# ---------------------------------------------------------------------------

_INFER_MAP = {
    BaseRetriever: NodeType.SOURCE,
    BaseReranker: NodeType.TRANSFORM,
    BaseMerger: NodeType.MERGE,
}


class GraphBuilder:
    """Fluent DAG builder. Call .build(deps) to validate, inject, and instantiate."""

    def __init__(self) -> None:
        self._spec = GraphSpec()

    def add_node(
        self,
        node_id: str,
        node_cls: type,
        config: Any = None,
        node_type: NodeType | None = None,
    ) -> GraphBuilder:
        """Register a logical node.

        node_type is inferred from node_cls if not supplied:
            BaseRetriever subclass → SOURCE
            BaseReranker  subclass → TRANSFORM
            BaseMerger    subclass → MERGE

        Raises:
            DuplicateNodeError: node_id already registered.
            TypeError: node_cls cannot be inferred and node_type is not given.
        """
        if node_id in self._spec.nodes:
            raise DuplicateNodeError(f"Node '{node_id}' is already registered")

        if node_type is None:
            for base_cls, inferred in _INFER_MAP.items():
                if issubclass(node_cls, base_cls):
                    node_type = inferred
                    break
            else:
                raise TypeError(
                    f"Cannot infer node_type for {node_cls!r}: "
                    "must be a subclass of BaseRetriever, BaseReranker, or BaseMerger, "
                    "or pass node_type explicitly"
                )

        self._spec.nodes[node_id] = NodeSpec(
            node_id=node_id,
            node_type=node_type,
            node_cls=node_cls,
            config=config,
        )
        return self

    def add_edge(self, from_id: str, to_id: str) -> GraphBuilder:
        """Add a directed edge from_id → to_id."""
        self._spec.edges.append((from_id, to_id))
        return self

    def add_edges(self, edges: list[tuple[str, str]]) -> GraphBuilder:
        """Batch-add directed edges."""
        for from_id, to_id in edges:
            self._spec.edges.append((from_id, to_id))
        return self

    def build(self, deps: PipelineDeps) -> RetrievalPipeline:
        """Validate → optimize → inject normalizers → instantiate.

        Returns a ready-to-execute RetrievalPipeline.
        """
        from app.retrieval.engine import instantiate  # local import breaks circular dep

        spec = self._spec
        validate(spec)
        spec = optimize(spec)
        spec = inject_normalizers(spec)
        return instantiate(spec, deps)


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

def validate(spec: GraphSpec) -> None:
    """Check topology constraints. Raises on the first violation.

    Rules:
        - No manually added Normalizer nodes
        - Every edge src/dst must exist in nodes
        - SOURCE nodes must have in-degree 0
        - TRANSFORM nodes must have in-degree 1
        - MERGE nodes must have in-degree >= 2
        - Exactly one sink node (out-degree 0)
        - No directed cycles (Kahn's algorithm)
    """
    # 1. No manual Normalizer nodes
    for node_id, node_spec in spec.nodes.items():
        if node_spec.node_type == NodeType.NORMALIZER:
            raise ManualNormalizerError(
                f"Node '{node_id}' is a Normalizer; "
                "Normalizer nodes are injected automatically and must not be added manually"
            )

    # 2. Edge reference validity
    for src, dst in spec.edges:
        if src not in spec.nodes:
            raise UnknownNodeError(f"Edge source '{src}' does not exist in nodes")
        if dst not in spec.nodes:
            raise UnknownNodeError(f"Edge destination '{dst}' does not exist in nodes")

    # Compute degree info
    in_degree: dict[str, int] = {nid: 0 for nid in spec.nodes}
    out_degree: dict[str, int] = {nid: 0 for nid in spec.nodes}
    for src, dst in spec.edges:
        out_degree[src] += 1
        in_degree[dst] += 1

    # 3. SOURCE in-degree = 0
    for nid, nspec in spec.nodes.items():
        if nspec.node_type == NodeType.SOURCE and in_degree[nid] != 0:
            raise TopologyError(
                f"SOURCE node '{nid}' must have in-degree 0, got {in_degree[nid]}"
            )

    # 4. TRANSFORM in-degree = 1
    for nid, nspec in spec.nodes.items():
        if nspec.node_type == NodeType.TRANSFORM and in_degree[nid] != 1:
            raise TopologyError(
                f"TRANSFORM node '{nid}' must have in-degree 1, got {in_degree[nid]}"
            )

    # 5. MERGE in-degree >= 2
    for nid, nspec in spec.nodes.items():
        if nspec.node_type == NodeType.MERGE and in_degree[nid] < 2:
            raise TopologyError(
                f"MERGE node '{nid}' must have in-degree >= 2, got {in_degree[nid]}"
            )

    # 6. Exactly one sink (out-degree = 0)
    sinks = [nid for nid, deg in out_degree.items() if deg == 0]
    if len(sinks) != 1:
        raise TopologyError(
            f"Expected exactly 1 sink node (out-degree 0), got {len(sinks)}: {sinks}"
        )

    # 7. No directed cycles (Kahn's algorithm)
    adj: dict[str, list[str]] = {nid: [] for nid in spec.nodes}
    for src, dst in spec.edges:
        adj[src].append(dst)

    in_deg = dict(in_degree)
    queue: deque[str] = deque(nid for nid, deg in in_deg.items() if deg == 0)
    visited = 0
    while queue:
        node = queue.popleft()
        visited += 1
        for neighbor in adj[node]:
            in_deg[neighbor] -= 1
            if in_deg[neighbor] == 0:
                queue.append(neighbor)

    if visited != len(spec.nodes):
        raise GraphCycleError("Graph contains a directed cycle")


# ---------------------------------------------------------------------------
# optimize
# ---------------------------------------------------------------------------

def optimize(spec: GraphSpec) -> GraphSpec:
    """Optimization pass placeholder. Currently identity."""
    return spec


# ---------------------------------------------------------------------------
# inject_normalizers
# ---------------------------------------------------------------------------

def inject_normalizers(spec: GraphSpec) -> GraphSpec:
    """Insert a Normalizer node after every SOURCE, TRANSFORM, and MERGE node.

    Algorithm:
        For each edge (src, dst):
            if src.node_type in {SOURCE, TRANSFORM, MERGE}:
                insert _norm_{src} between src and dst
                (node is created once even if src has multiple outgoing edges)
            else:
                keep edge as-is
        After the loop, if the sink is not already a Normalizer, append one.
    """
    new_nodes: dict[str, NodeSpec] = dict(spec.nodes)
    new_edges: list[tuple[str, str]] = []

    _inject_types = {NodeType.SOURCE, NodeType.TRANSFORM, NodeType.MERGE}

    for src, dst in spec.edges:
        if spec.nodes[src].node_type in _inject_types:
            norm_id = f"_norm_{src}"
            if norm_id not in new_nodes:
                new_nodes[norm_id] = NodeSpec(
                    node_id=norm_id,
                    node_type=NodeType.NORMALIZER,
                    node_cls=Normalizer,
                    config=None,
                )
                new_edges.append((src, norm_id))  # added only once per src
            new_edges.append((norm_id, dst))
        else:
            new_edges.append((src, dst))

    # Find the current sink (out-degree 0 in the updated edge set)
    out_degrees: dict[str, int] = {nid: 0 for nid in new_nodes}
    for s, _ in new_edges:
        out_degrees[s] += 1

    sinks = [nid for nid, deg in out_degrees.items() if deg == 0]
    sink = sinks[0]  # validate() already guaranteed exactly one sink in original spec

    # If the sink is not already a Normalizer and not a TRANSFORM (e.g. Reranker),
    # append one. TRANSFORM sinks (Reranker) produce calibrated absolute scores;
    # re-normalizing would map the lowest result to 0.0 and destroy score semantics.
    if new_nodes[sink].node_type not in {NodeType.NORMALIZER, NodeType.TRANSFORM}:
        norm_id = f"_norm_{sink}"
        new_nodes[norm_id] = NodeSpec(
            node_id=norm_id,
            node_type=NodeType.NORMALIZER,
            node_cls=Normalizer,
            config=None,
        )
        new_edges.append((sink, norm_id))

    return GraphSpec(nodes=new_nodes, edges=new_edges)
