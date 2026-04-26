# 添加新检索拓扑

## 概述

检索拓扑是一个由检索操作符组成的有向无环图（DAG）。目前支持 **三种方式** 创建新拓扑：

| 方式 | 适用场景 | 是否持久化 |
|---|---|---|
| 方法一：代码注册 | 新增操作符或预定义拓扑 | 是（内置种子） |
| 方法二：API 预设 | 运行时动态创建自定义拓扑 | 是（`topology_configs` 表） |
| 方法三：请求内联 | 每次检索/生成请求传递临时拓扑 | 否 |

---

## 架构概述

```
TopologySpecJSON (Pydantic, 用户输入)
       │  to_graph_spec(registry)
       ▼
GraphSpec (内部数据类: nodes + edges)
       │  validate() → inject_normalizers() → instantiate()
       ▼
RetrievalPipeline (可执行的 DAG 实例)
       │  execute(context)
       ▼
list[SearchHit]
```

每次创建都经过相同的验证链：结构完整性 → 拓扑约束 → Normalizer 自动注入。

---

## 方法一：代码注册（`workflows.py`）

### 步骤 1 — 扩展 PipelineDeps（可选）

若拓扑仅使用 `embedder`、`qdrant_client`、`session_factory`，可直接使用现有 `PipelineDeps`，跳过此步。

若需要额外资源（如自定义模型、LLM 生成器），在 `core/pipeline_deps.py` 中扩展：

```python
# core/pipeline_deps.py
from dataclasses import dataclass

@dataclass(frozen=True)
class MyTopologyDeps(PipelineDeps):
    my_extra_resource: SomeType
```

`PipelineDeps` 是冻结数据类，子类继承全部三个基础字段并追加自有字段。

### 步骤 2 — 实现操作符

操作符放在 `retrieval/searcher.py`（检索器 / 合并器）或 `retrieval/reranker.py`（重排序器）。每个操作符继承 `retrieval/operators.py` 中的三个抽象基类之一：

| 基类 | `node_type` | 必须实现的方法 |
|---|---|---|
| `BaseRetriever` | `SOURCE` | `async retrieve(context) → list[SearchHit]` |
| `BaseReranker` | `TRANSFORM` | `async rerank(hits, context) → list[SearchHit]` |
| `BaseMerger` | `MERGE` | `async merge(hits_list, context) → list[SearchHit]` |

`GraphBuilder` 会根据基类自动推断节点类型，无需在 `add_node` 中手动指定。

构造函数契约——每个操作符接受两个关键字参数：

```python
def __init__(self, deps: PipelineDeps, config: MyConfig | None) -> None:
    ...
```

`deps` 为传递给 `workflows.*` 的具体 deps 对象；如需额外字段，可类型标注为子类型：

```python
class MySearcher(BaseRetriever):
    def __init__(self, deps: MyTopologyDeps, config=None) -> None:
        self._extra = deps.my_extra_resource
        self._qdrant = deps.qdrant_client
```

配置是 `retrieval/configs.py` 中的普通 Pydantic 模型（`frozen=True`）。若操作符无需可调参数，传入 `None` 即可。

### 步骤 3 — 在 workflows.py 中注册工厂

在 `retrieval/workflows.py` 中添加工厂函数：

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

`GraphBuilder.build(deps)` 自动完成：验证 → 优化 → 注入 Normalizer → 实例化。

### 步骤 4 — 注册为内置预设（可选）

同时提供一个 `_spec` 变体并加入 `builtin_topology_seeds()`：

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

在 `builtin_topology_seeds()` 中追加：

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

启动时 `backend/app/main.py:28-43` 会自动将缺失的内置种子写入 `topology_configs` 表。

---

## 方法二：API 预设（运行时持久化）

无需修改代码即可通过 HTTP API 创建拓扑。

### 相关端点

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/topology/node-types` | 列出所有已注册节点类型及其 JSON Schema |
| `POST` | `/api/topology/validate` | 验证拓扑 JSON 结构 + 拓扑约束 |
| `GET` | `/api/topology/presets` | 列出所有预设（包含内置） |
| `POST` | `/api/topology/presets` | 创建新预设 |
| `DELETE` | `/api/topology/presets/{id}` | 删除预设（内置不可删除） |

### 创建预设示例

```http
POST /api/topology/presets
Content-Type: application/json

{
  "name": "my_hybrid",
  "description": "Vector + BM25 混合检索带 RRF 融合",
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

创建成功返回 200，重复名称返回 409。

### JSON 字段说明

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | `str` | 预设唯一名称（不能与已有重复） |
| `description` | `str \| None` | 可选描述 |
| `spec.nodes[].node_id` | `str` | 节点唯一标识（全图唯一） |
| `spec.nodes[].node_type` | `str` | 操作符类型（如 `"VectorSearcher"`） |
| `spec.nodes[].config` | `dict` | 操作符配置（可为空 `{}`） |
| `spec.edges[].from_node` | `str` | 边起点 node_id |
| `spec.edges[].to_node` | `str` | 边终点 node_id |

### 配置优先级

```
SearchRequest.topology  >  default_topology（Settings）  >  代码内工厂
```

详见 `backend/app/retrieval/topology.py:212-225` 中的 `resolve_topology()`。

---

## 方法三：请求内联（即用即抛）

`SearchRequest` 和 `GenerateRequest` 均支持可选的 `topology` 字段：

```json
{
  "query_text": "什么是 RAG?",
  "top_k": 10,
  "topology": {
    "nodes": [
      {"node_id": "vec", "node_type": "VectorSearcher", "config": {}}
    ],
    "edges": []
  }
}
```

直接传入 JSON，单次有效，不持久化。为空时回退到 `default_topology`。

---

## 可用操作符

| `node_type` | 角色 | 配置类 | 字段 |
|---|---|---|---|
| `VectorSearcher` | SOURCE | `VectorSearcherConfig` | `score_threshold`, `top_k`, `collection_name` |
| `BM25Searcher` | SOURCE | `BM25SearcherConfig` | `score_threshold`, `top_k`, `recall_multiplier` |
| `ContextualBM25Searcher` | SOURCE | `ContextualBM25SearcherConfig` | `score_threshold`, `top_k`, `recall_multiplier` |
| `RRFMerger` | MERGE | `RRFMergerConfig` | `k`, `weights` |
| `Reranker` | TRANSFORM | `RerankerConfig` | `alpha`, `beta`, `gamma`, `score_threshold`, `retention_mode`, `s_base`, `tag_fallback` |
| `QueryRewriter` | SOURCE | — | 未实现（`available=False`） |

查询所有可用类型及完整 JSON Schema：

```http
GET /api/topology/node-types
```

---

## 拓扑约束

`validate()`（`retrieval/graph.py:183-262`）对以下违规立即报错：

- 不允许手动添加 Normalizer 节点
- 所有边的起止点必须引用存在的节点
- `SOURCE` 节点入度必须为 0
- `TRANSFORM` 节点入度必须为 1
- `MERGE` 节点入度必须 ≥ 2
- 有且仅有一个汇点（出度为 0）
- 无有向环（Kahn 算法检测）

可先行验证而不创建预设：

```http
POST /api/topology/validate
{"nodes": [...], "edges": [...]}
```

---

## 数据持久化

预设存入 SQLite 表 `topology_configs`（ORM 模型：`app/core/models.py:133-145`）：

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | `int` | 自增主键 |
| `name` | `str` | 唯一名称 |
| `description` | `str \| None` | 可选描述 |
| `spec_json` | `str` (TEXT) | 序列化的 `TopologySpecJSON` |
| `is_builtin` | `bool` | 是否内置（内置不可删除） |
| `created_at` | `datetime` | 创建时间 |

---

## 切换当前拓扑

### 通过配置

在 `Settings` 中设置 `default_topology` 指向任一预设名称（内置或自定义）：

```bash
DEFAULT_TOPOLOGY=my_hybrid
```

检索/生成请求在未指定 `topology` 字段时自动使用该预设。

### 通过代码

修改 `build_from_settings()`（`workflows.py:264-274`）中的 `match` 分支，或直接在 CLI / MCP / 依赖注入处替换工厂调用。

---

## 预实例化多个拓扑

```python
from app.core.pipeline_deps import PipelineDeps
from app.retrieval import workflows
from app.retrieval.engine import RetrievalPipeline

base_deps = PipelineDeps(embedder, qdrant, session_factory)

pipelines = {
    "linear":  RetrievalPipeline(workflows.linear(base_deps).__dict__),
    "hybrid":  RetrievalPipeline(workflows.hybrid(base_deps).__dict__),
}
# 注意：直接复用 RetrievalPipeline 内部结构需调用工厂后提取字段，
#       推荐改为从 DB 加载预设再实例化。
results = await pipelines["hybrid"].execute(context)
```
