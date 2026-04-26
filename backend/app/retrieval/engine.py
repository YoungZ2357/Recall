"""DAG execution engine.

Exports:
    RetrievalPipeline — instantiated, executable DAG produced by GraphBuilder.build()
    instantiate()     — GraphSpec + PipelineDeps → RetrievalPipeline
"""

from __future__ import annotations

from collections import deque
from typing import Any

from app.core.pipeline_deps import PipelineDeps
from app.retrieval.graph import GraphSpec, Normalizer
from app.retrieval.operators import NodeType, PipelineContext, SearchHit
from app.retrieval.scoring import normalize_scores


class RetrievalPipeline:
    """Instantiated executable DAG. Produced by GraphBuilder.build().

    Execute in topological order; return the sink node's output.
    Future parallel execution: same interface, asyncio.gather on independent layers.
    """

    def __init__(
        self,
        execution_order: list[str],
        nodes: dict[str, Any],            # node_id → operator instance
        adjacency: dict[str, list[str]],   # node_id → downstream node IDs
        reverse_adj: dict[str, list[str]], # node_id → upstream node IDs
    ) -> None:
        self.execution_order = execution_order
        self.nodes = nodes
        self.adjacency = adjacency
        self.reverse_adj = reverse_adj

    async def execute(self, context: PipelineContext) -> list[SearchHit]:
        """Execute all nodes in topological order; return sink node output."""
        results: dict[str, list[SearchHit]] = {}

        for node_id in self.execution_order:
            node = self.nodes[node_id]
            upstream_ids = self.reverse_adj.get(node_id, [])

            match node.node_type:
                case NodeType.SOURCE:
                    results[node_id] = await node.retrieve(context)

                case NodeType.TRANSFORM:
                    [parent_id] = upstream_ids
                    results[node_id] = await node.rerank(results[parent_id], context)

                case NodeType.MERGE:
                    multi_hits = [results[pid] for pid in upstream_ids]
                    results[node_id] = await node.merge(multi_hits, context)

                case NodeType.NORMALIZER:
                    [parent_id] = upstream_ids
                    results[node_id] = normalize_scores(results[parent_id])

        return results[self.execution_order[-1]]


# ---------------------------------------------------------------------------
# Instantiation helpers
# ---------------------------------------------------------------------------

def instantiate(spec: GraphSpec, deps: PipelineDeps) -> RetrievalPipeline:
    """Traverse an injected GraphSpec and create the executable pipeline."""
    nodes: dict[str, Any] = {}
    for node_id, node_spec in spec.nodes.items():
        if node_spec.node_type == NodeType.NORMALIZER:
            nodes[node_id] = Normalizer()
        else:
            nodes[node_id] = node_spec.node_cls(deps=deps, config=node_spec.config)

    execution_order = topological_sort(spec)
    adjacency = build_adjacency(spec.edges)
    reverse_adj = build_reverse_adjacency(spec.edges)

    return RetrievalPipeline(
        execution_order=execution_order,
        nodes=nodes,
        adjacency=adjacency,
        reverse_adj=reverse_adj,
    )


def topological_sort(spec: GraphSpec) -> list[str]:
    """Return node IDs in topological order (Kahn's algorithm)."""
    adj: dict[str, list[str]] = {nid: [] for nid in spec.nodes}
    in_degree: dict[str, int] = {nid: 0 for nid in spec.nodes}

    for src, dst in spec.edges:
        adj[src].append(dst)
        in_degree[dst] += 1

    queue: deque[str] = deque(nid for nid, deg in in_degree.items() if deg == 0)
    order: list[str] = []

    while queue:
        node = queue.popleft()
        order.append(node)
        for neighbor in adj[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    return order


def build_adjacency(edges: list[tuple[str, str]]) -> dict[str, list[str]]:
    """node_id → list of downstream node IDs."""
    adj: dict[str, list[str]] = {}
    for src, dst in edges:
        adj.setdefault(src, []).append(dst)
    return adj


def build_reverse_adjacency(edges: list[tuple[str, str]]) -> dict[str, list[str]]:
    """node_id → list of upstream node IDs (in edge-insertion order)."""
    rev: dict[str, list[str]] = {}
    for src, dst in edges:
        rev.setdefault(dst, []).append(src)
    return rev
