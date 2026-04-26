"""JSON ↔ GraphSpec bridge layer.

Pydantic models for serializing/deserializing retrieval pipeline topologies,
plus converters that map between user-facing JSON and internal GraphSpec.

    TopologySpecJSON  ←→  GraphSpec + NodeSpec
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self

from pydantic import BaseModel, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.retrieval.graph import GraphSpec, NodeSpec
from app.retrieval.operators import NodeType
from app.retrieval.registry import NodeTypeInfo

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class EdgeJSON(BaseModel):
    from_node: str
    to_node: str


class NodeSpecJSON(BaseModel):
    node_id: str
    node_type: str
    config: dict


class TopologySpecJSON(BaseModel):
    name: str | None = None
    nodes: list[NodeSpecJSON]
    edges: list[EdgeJSON]

    @model_validator(mode="after")
    def _check_structural_constraints(self) -> Self:
        node_ids = [n.node_id for n in self.nodes]
        seen: set[str] = set()
        for nid in node_ids:
            if nid in seen:
                raise ValueError(f"Duplicate node_id: {nid!r}")
            seen.add(nid)

        valid_ids = {n.node_id for n in self.nodes}
        for edge in self.edges:
            if edge.from_node not in valid_ids:
                raise ValueError(
                    f"Edge from_node {edge.from_node!r} not found in nodes"
                )
            if edge.to_node not in valid_ids:
                raise ValueError(
                    f"Edge to_node {edge.to_node!r} not found in nodes"
                )

        return self

    # -----------------------------------------------------------------------
    # Converters
    # -----------------------------------------------------------------------

    def to_graph_spec(self, registry: dict[str, NodeTypeInfo]) -> GraphSpec:
        node_specs: list[NodeSpec] = []

        for node in self.nodes:
            try:
                info = registry[node.node_type]
            except KeyError:
                raise ValueError(
                    f"Unknown node_type {node.node_type!r} for node {node.node_id!r}"
                ) from None

            if not info.available:
                raise ValueError(
                    f"Node {node.node_id!r} uses node_type {node.node_type!r} "
                    "which is not yet implemented"
                )

            if info.config_cls is None:
                raise ValueError(
                    f"Node {node.node_id!r} of type {node.node_type!r} "
                    "has no config class registered"
                )

            config_instance = info.config_cls(**node.config)

            node_type_enum = NodeType[info.node_role]

            node_specs.append(
                NodeSpec(
                    node_id=node.node_id,
                    node_type=node_type_enum,
                    node_cls=info.node_cls,
                    config=config_instance,
                )
            )

        edges = [(e.from_node, e.to_node) for e in self.edges]

        return GraphSpec(
            nodes={spec.node_id: spec for spec in node_specs},
            edges=edges,
        )

    @classmethod
    def from_graph_spec(
        cls, spec: GraphSpec, registry: dict[str, NodeTypeInfo]
    ) -> TopologySpecJSON:
        cls_to_type: dict[type, str] = {
            info.node_cls: info.node_type
            for info in registry.values()
            if info.node_cls is not None
        }

        node_json_list: list[NodeSpecJSON] = []
        for node_spec in spec.nodes.values():
            if node_spec.node_type == NodeType.NORMALIZER:
                continue

            try:
                node_type_str = cls_to_type[node_spec.node_cls]
            except KeyError:
                raise ValueError(
                    f"Cannot serialize node {node_spec.node_id!r}: "
                    "node_cls not found in registry"
                ) from None

            config_dict = (
                node_spec.config.model_dump()
                if node_spec.config is not None
                else {}
            )

            node_json_list.append(
                NodeSpecJSON(
                    node_id=node_spec.node_id,
                    node_type=node_type_str,
                    config=config_dict,
                )
            )

        edge_json_list = _reconstruct_user_edges(spec)

        return cls(nodes=node_json_list, edges=edge_json_list)


# ---------------------------------------------------------------------------
# Edge reconstruction helper
# ---------------------------------------------------------------------------


def _reconstruct_user_edges(spec: GraphSpec) -> list[EdgeJSON]:
    adj: dict[str, list[str]] = {nid: [] for nid in spec.nodes}
    for src, dst in spec.edges:
        adj[src].append(dst)

    result: list[EdgeJSON] = []
    for src_nid, src_node in spec.nodes.items():
        if src_node.node_type == NodeType.NORMALIZER:
            continue

        for neighbor in adj.get(src_nid, []):
            neighbor_node = spec.nodes.get(neighbor)
            if neighbor_node is None:
                continue

            if neighbor_node.node_type == NodeType.NORMALIZER:
                for nn in adj.get(neighbor, []):
                    nn_node = spec.nodes.get(nn)
                    if nn_node and nn_node.node_type != NodeType.NORMALIZER:
                        result.append(
                            EdgeJSON(from_node=src_nid, to_node=nn)
                        )
            elif neighbor_node.node_type != NodeType.NORMALIZER:
                result.append(
                    EdgeJSON(from_node=src_nid, to_node=neighbor)
                )

    return result


# ---------------------------------------------------------------------------
# Topology resolution helpers (T5)
# ---------------------------------------------------------------------------


async def load_topology_by_name(name: str, session: AsyncSession) -> TopologySpecJSON:
    from sqlalchemy import select

    from app.core.models import TopologyConfig

    result = await session.execute(
        select(TopologyConfig).where(TopologyConfig.name == name)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise RuntimeError(f"Default topology '{name}' not found in database")
    return TopologySpecJSON.model_validate_json(row.spec_json)


async def resolve_topology(
    spec: TopologySpecJSON | None,
    default_name: str,
    session: AsyncSession,
) -> GraphSpec:
    from app.retrieval.registry import list_node_types

    registry = {info.node_type: info for info in list_node_types()}

    if spec is not None:
        return spec.to_graph_spec(registry)

    topo_json = await load_topology_by_name(default_name, session)
    return topo_json.to_graph_spec(registry)


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from app.retrieval.registry import list_node_types

    registry = {info.node_type: info for info in list_node_types()}

    topology = TopologySpecJSON(
        name="hybrid",
        nodes=[
            NodeSpecJSON(node_id="vec", node_type="VectorSearcher", config={}),
            NodeSpecJSON(node_id="bm25", node_type="BM25Searcher", config={}),
            NodeSpecJSON(node_id="merge", node_type="RRFMerger", config={}),
            NodeSpecJSON(node_id="rerank", node_type="Reranker", config={}),
        ],
        edges=[
            EdgeJSON(from_node="vec", to_node="merge"),
            EdgeJSON(from_node="bm25", to_node="merge"),
            EdgeJSON(from_node="merge", to_node="rerank"),
        ],
    )

    graph_spec = topology.to_graph_spec(registry)
    print(f"GraphSpec: nodes={len(graph_spec.nodes)}, edges={len(graph_spec.edges)}")

    restored = TopologySpecJSON.from_graph_spec(graph_spec, registry)
    assert len(restored.nodes) == len(
        topology.nodes
    ), f"Node count mismatch: {len(restored.nodes)} vs {len(topology.nodes)}"
    assert len(restored.edges) == len(
        topology.edges
    ), f"Edge count mismatch: {len(restored.edges)} vs {len(topology.edges)}"
    print("round-trip OK")
