# Adding a New Retrieval Topology

## Overview

A retrieval topology is a directed acyclic graph (DAG) of retrieval operators.
There are **three ways** to create a new topology:

| Method | Use Case | Persistent |
|---|---|---|
| Method 1: Code Registration | New operator or predefined topology | Yes (built-in seed) |
| Method 2: API Preset | Runtime dynamic custom topology | Yes (`topology_configs` table) |
| Method 3: Request Inline | Ad-hoc topology per search/generate request | No |

---

## Architecture Overview

```
TopologySpecJSON (Pydantic, user input)
       │  to_graph_spec(registry)
       ▼
GraphSpec (internal dataclass: nodes + edges)
       │  validate() → inject_normalizers() → instantiate()
       ▼
RetrievalPipeline (executable DAG instance)
       │  execute(context)
       ▼
list[SearchHit]
```

Every creation goes through the same validation chain: structural integrity →
topology constraints → Normalizer auto-injection.

---

## Method 1: Code Registration (`workflows.py`)

### Step 1 — Extend PipelineDeps (optional)

If the topology only uses `embedder`, `qdrant_client`, and `session_factory`,
the existing `PipelineDeps` is sufficient — skip this step.

If extra resources are required (e.g., a custom model, an LLM generator),
extend `PipelineDeps` in `core/pipeline_deps.py`:

```python
# core/pipeline_deps.py
from dataclasses import dataclass

@dataclass(frozen=True)
class MyTopologyDeps(PipelineDeps):
    my_extra_resource: SomeType
```

`PipelineDeps` is a frozen dataclass; subclasses inherit all three base
fields and append their own.

### Step 2 — Implement Operators

Operators live in `retrieval/searcher.py` (retrievers / mergers) or
`retrieval/reranker.py` (rerankers). Each operator subclasses one of the
three abstract bases from `retrieval/operators.py`:

| Base class | `node_type` | Required method |
|---|---|---|
| `BaseRetriever` | `SOURCE` | `async retrieve(context) → list[SearchHit]` |
| `BaseReranker` | `TRANSFORM` | `async rerank(hits, context) → list[SearchHit]` |
| `BaseMerger` | `MERGE` | `async merge(hits_list, context) → list[SearchHit]` |

`GraphBuilder` infers the node type from the base class automatically, so no
explicit `node_type` argument is needed in `add_node`.

Constructor contract — every operator receives two keyword arguments:

```python
def __init__(self, deps: PipelineDeps, config: MyConfig | None) -> None:
    ...
```

`deps` will be the specific deps object passed to `workflows.*`; cast or
annotate to the subtype if extra fields are needed:

```python
class MySearcher(BaseRetriever):
    def __init__(self, deps: MyTopologyDeps, config=None) -> None:
        self._extra = deps.my_extra_resource
        self._qdrant = deps.qdrant_client
```

Configs are frozen Pydantic models in `retrieval/configs.py`. Add one if the
operator exposes tunable parameters; otherwise pass `None`.

### Step 3 — Register a Factory in workflows.py

Add a factory function in `retrieval/workflows.py`:

```python
def my_topology(
    deps: PipelineDeps,
    my_config: MySearcherConfig | None = None,
    reranker_config: RerankerConfig | None = None,
) -> RetrievalPipeline:
    return (
        GraphBuilder()
        .add_node("search", MySearcher, my_config)
        .add_node("rerank", Reranker, reranker_config)
        .add_edge("search", "rerank")
        .build(deps)
    )
```

`GraphBuilder.build(deps)` handles validation, optimization, normalizer
injection, and instantiation automatically.

### Step 4 — Register as a Built-in Preset (optional)

Also provide a `_spec` variant and add to `builtin_topology_seeds()`:

```python
def my_topology_spec(
    my_config: MySearcherConfig | None = None,
    reranker_config: RerankerConfig | None = None,
) -> GraphSpec:
    return (
        GraphBuilder()
        .add_node("search", MySearcher, my_config)
        .add_node("rerank", Reranker, reranker_config)
        .add_edge("search", "rerank")
    ).spec
```

Append to `builtin_topology_seeds()`:

```python
registry = {info.node_type: info for info in list_node_types()}
for name, description, graph_spec in [
    ("my_topology", "Custom topology description", my_topology_spec()),
]:
    topo_json = TopologySpecJSON.from_graph_spec(graph_spec, registry)
    seeds.append({
        "name": name,
        "description": description,
        "spec_json": topo_json.model_dump_json(),
        "is_builtin": True,
    })
```

On startup, `backend/app/main.py:28-43` writes missing built-in seeds into
the `topology_configs` table.

---

## Method 2: API Preset (Runtime, Persistent)

Create topologies via HTTP without modifying code.

### Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/topology/node-types` | List all registered node types with JSON Schema |
| `POST` | `/api/topology/validate` | Validate topology JSON structure + constraints |
| `GET` | `/api/topology/presets` | List all presets (including built-in) |
| `POST` | `/api/topology/presets` | Create a new preset |
| `DELETE` | `/api/topology/presets/{id}` | Delete a preset (built-in cannot be deleted) |

### Create Preset Example

```http
POST /api/topology/presets
Content-Type: application/json

{
  "name": "my_hybrid",
  "description": "Vector + BM25 hybrid search with RRF fusion and reranking",
  "spec": {
    "nodes": [
      {"node_id": "vec",     "node_type": "VectorSearcher",           "config": {"top_k": 50}},
      {"node_id": "bm25",    "node_type": "BM25Searcher",             "config": {"top_k": 50}},
      {"node_id": "merge",   "node_type": "RRFMerger",                "config": {"k": 60}},
      {"node_id": "rerank",  "node_type": "Reranker",                 "config": {"alpha": 0.7, "beta": 0.15, "gamma": 0.15}}
    ],
    "edges": [
      {"from_node": "vec",     "to_node": "merge"},
      {"from_node": "bm25",    "to_node": "merge"},
      {"from_node": "merge",   "to_node": "rerank"}
    ]
  }
}
```

Returns 200 on success, 409 on duplicate name.

### JSON Field Reference

| Field | Type | Description |
|---|---|---|
| `name` | `str` | Unique preset name |
| `description` | `str \| None` | Optional description |
| `spec.nodes[].node_id` | `str` | Unique node identifier (unique within the graph) |
| `spec.nodes[].node_type` | `str` | Operator type (e.g. `"VectorSearcher"`) |
| `spec.nodes[].config` | `dict` | Operator configuration (can be empty `{}`) |
| `spec.edges[].from_node` | `str` | Edge source node_id |
| `spec.edges[].to_node` | `str` | Edge target node_id |

### Resolution Priority

```
SearchRequest.topology  >  default_topology (Settings)  >  code factory
```

See `resolve_topology()` in `backend/app/retrieval/topology.py:212-225`.

---

## Method 3: Request Inline (Ad-hoc)

Both `SearchRequest` and `GenerateRequest` accept an optional `topology` field:

```json
{
  "query_text": "What is RAG?",
  "top_k": 10,
  "topology": {
    "nodes": [
      {"node_id": "vec", "node_type": "VectorSearcher", "config": {}}
    ],
    "edges": []
  }
}
```

Passed inline per request, no persistence. Falls back to `default_topology`
when omitted.

---

## Available Operators

| `node_type` | Role | Config Class | Fields |
|---|---|---|---|
| `VectorSearcher` | SOURCE | `VectorSearcherConfig` | `score_threshold`, `top_k`, `collection_name` |
| `BM25Searcher` | SOURCE | `BM25SearcherConfig` | `score_threshold`, `top_k`, `recall_multiplier` |
| `ContextualBM25Searcher` | SOURCE | `ContextualBM25SearcherConfig` | `score_threshold`, `top_k`, `recall_multiplier` |
| `RRFMerger` | MERGE | `RRFMergerConfig` | `k`, `weights` |
| `Reranker` | TRANSFORM | `RerankerConfig` | `alpha`, `beta`, `gamma`, `score_threshold`, `retention_mode`, `s_base`, `tag_fallback` |
| `QueryRewriter` | SOURCE | — | Not implemented (`available=False`) |

List all available types and full JSON Schema:

```http
GET /api/topology/node-types
```

---

## Topology Constraints

`validate()` (`retrieval/graph.py:183-262`) rejects graphs that violate these
rules (raises on first violation):

- No manually added Normalizer nodes
- Every edge src/dst must reference existing nodes
- `SOURCE` nodes must have in-degree 0
- `TRANSFORM` nodes must have in-degree exactly 1
- `MERGE` nodes must have in-degree ≥ 2
- Exactly one sink node (out-degree 0)
- No directed cycles (Kahn's algorithm)

Pre-validate without creating a preset:

```http
POST /api/topology/validate
{"nodes": [...], "edges": [...]}
```

---

## Persistence

Presets are stored in the SQLite table `topology_configs` (ORM model:
`app/core/models.py:133-145`):

| Column | Type | Description |
|---|---|---|
| `id` | `int` | Auto-increment primary key |
| `name` | `str` | Unique name |
| `description` | `str \| None` | Optional description |
| `spec_json` | `str` (TEXT) | Serialized `TopologySpecJSON` |
| `is_builtin` | `bool` | Whether built-in (cannot be deleted) |
| `created_at` | `datetime` | Creation timestamp |

---

## Switching the Active Topology

### Via Configuration

Set `default_topology` in `Settings` to any preset name (built-in or custom):

```bash
DEFAULT_TOPOLOGY=my_hybrid
```

Search/generate requests use this preset when no `topology` field is provided.

### Via Code

Modify the `match` branch in `build_from_settings()` (`workflows.py:264-274`),
or replace the factory call directly in CLI / MCP / dependency injection sites.

---

## Pre-instantiating Multiple Topologies

```python
from app.core.pipeline_deps import PipelineDeps
from app.retrieval import workflows
from app.retrieval.engine import RetrievalPipeline

base_deps = PipelineDeps(embedder, qdrant, session_factory)

pipelines = {
    "linear":  RetrievalPipeline(workflows.linear(base_deps).__dict__),
    "hybrid":  RetrievalPipeline(workflows.hybrid(base_deps).__dict__),
}
# Note: copying RetievalPipeline internal fields directly is fragile.
#       Prefer loading presets from DB and instantiating on demand.
results = await pipelines["hybrid"].execute(context)
```
