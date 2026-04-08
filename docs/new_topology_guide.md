# Adding a New Retrieval Topology

## Overview

A topology is a directed acyclic graph (DAG) of retrieval operators. Adding one
involves three steps: define deps (if the topology needs resources beyond the
standard set), implement operators, and register the topology as a factory
function in `workflows.py`.

---

## Step 1 — Define deps (optional)

If the topology only uses `embedder`, `qdrant_client`, and `session_factory`,
the existing `PipelineDeps` is sufficient — skip this step.

If extra resources are required (e.g. a reranker model, an LLM generator),
extend `PipelineDeps` in `core/pipeline_deps.py`:

```python
# core/pipeline_deps.py
@dataclass(frozen=True)
class MyTopologyDeps(PipelineDeps):
    my_extra_resource: SomeType
```

`PipelineDeps` is a frozen dataclass, so subclasses inherit all three base
fields and add their own.

---

## Step 2 — Implement operators

Operators live in `retrieval/searcher.py` (retrievers / mergers) or
`retrieval/reranker.py` (rerankers). Each operator subclasses one of the three
abstract bases from `retrieval/operators.py`:

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

Configs are plain dataclasses in `retrieval/configs.py`. Add one if the
operator exposes tuneable parameters; otherwise pass `None`.

---

## Step 3 — Register in workflows.py

Add a factory function to `retrieval/workflows.py`. The function receives deps,
builds the graph via `GraphBuilder`, and returns `engine.RetrievalPipeline`:

```python
def my_topology(
    deps: MyTopologyDeps,
    my_config: MySearcherConfig | None = None,
    reranker_config: RerankerConfig | None = None,
) -> engine.RetrievalPipeline:
    """Short description of the topology.

    Topology: MySearcher ─ Normalizer ─ Reranker ─ Normalizer
    """
    return (
        GraphBuilder()
        .add_node("search", MySearcher, my_config)
        .add_node("rerank", Reranker, reranker_config)
        .add_edge("search", "rerank")
        .build(deps)
    )
```

`GraphBuilder.build(deps)` handles validation, normalizer injection, and
instantiation automatically.

---

## Step 4 — Instantiate RetrievalPipeline

`RetrievalPipeline` (in `retrieval/pipeline.py`) accepts the pre-built DAG plus
the two resources it uses directly:

```python
from app.retrieval import workflows
from app.retrieval.pipeline import RetrievalPipeline

deps = MyTopologyDeps(
    embedder=embedder,
    qdrant_client=qdrant,
    session_factory=session_factory,
    my_extra_resource=resource,
)

pipeline = RetrievalPipeline(
    dag=workflows.my_topology(deps),
    embedder=deps.embedder,
    session_factory=deps.session_factory,
)
```

`pipeline.search(...)` is then identical to the standard usage.

---

## Pre-instantiating multiple topologies

Build each pipeline independently and hold them in a dict or similar structure:

```python
base_deps = PipelineDeps(embedder, qdrant, session_factory)
extra_deps = MyTopologyDeps(embedder, qdrant, session_factory, my_extra_resource=r)

pipelines = {
    "hybrid":      RetrievalPipeline(workflows.hybrid(base_deps),      embedder, session_factory),
    "linear":      RetrievalPipeline(workflows.linear(base_deps),      embedder, session_factory),
    "my_topology": RetrievalPipeline(workflows.my_topology(extra_deps), embedder, session_factory),
}

active = pipelines["my_topology"]
results = await active.search(query_text="...")
```

---

## Switching the active topology

The active topology is hardcoded in **5 call sites**. Change `workflows.hybrid(deps)` to
the desired factory at each location:

| File | Line | Context |
|---|---|---|
| `backend/app/cli/search.py` | 56 | `search` CLI command |
| `backend/app/cli/generate.py` | 67 | `generate` CLI command |
| `backend/app/cli/eval.py` | 221 | `eval run` command |
| `backend/app/api/dependencies.py` | 62 | FastAPI HTTP endpoints |
| `backend/app/mcp/server.py` | 59 | MCP server |

Example — switch all CLI commands and API to `hybrid_contextual_bm25`:

```python
dag=workflows.hybrid_contextual_bm25(deps),
```

No changes to `deps` are needed; `PipelineDeps` is sufficient for all currently
defined topologies.

---

## Topology constraints enforced by GraphBuilder

`validate()` rejects graphs that violate these rules (raises on first violation):

- `SOURCE` nodes must have in-degree 0
- `TRANSFORM` nodes must have in-degree exactly 1
- `MERGE` nodes must have in-degree ≥ 2
- Exactly one sink node (out-degree 0)
- No directed cycles
- Normalizer nodes must not be added manually (auto-injected after every SOURCE / TRANSFORM / MERGE)
