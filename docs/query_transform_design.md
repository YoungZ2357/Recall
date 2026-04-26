# 查询变换通信结构设计

2026-04-25

## 概述

查询变换层位于用户原始 query 与检索 pipeline 之间。其输出为带路由标记的变体列表，由 `QueryDispatcher` 负责将不同类型的变体分发至相应的下游链路。

本文档定义该层涉及的数据结构、接口契约及数据流。

---

## 数据结构

### `QueryRoute`（位于 `operators.py`）

```python
QueryRoute = Literal["direct", "fusion", "hyde"]
```

| 值 | 语义 |
|----|------|
| `"direct"` | 原始查询或基础改写，直接进入主检索通路 |
| `"fusion"` | RAG-Fusion 变体之一，需并行检索后 RRF 合并 |
| `"hyde"` | HyDE 变体，携带假设文档的预计算向量，以该向量驱动检索 |

与现有 `retention_mode: Literal[...]` 风格保持一致，不引入额外 Enum。

### `TransformedQuery`（位于 `operators.py`）

```python
@dataclass
class TransformedQuery:
    text: str                             # 变体文本
    route: QueryRoute                     # 路由标记
    embedding: list[float] | None = None  # 预计算向量；None 表示由 Dispatcher 按需嵌入
```

字段约束：

- `text`：所有 route 类型均须提供。`hyde` 中 text 为原始 query，仅供日志/调试，检索实际使用 `embedding`
- `embedding`：仅 `hyde` 类型在变换阶段预计算（假设文档的嵌入向量）；`direct`/`fusion` 留 `None`，由 Dispatcher 调用 Embedder 补全

---

## `PipelineContext` 扩展（位于 `operators.py`）

`fusion` 和 `hyde` 均存在"检索用变体向量、重排序用原始 query"的需求。通过在现有 `PipelineContext` 上增加两个可选覆盖字段处理：

```python
@dataclass
class PipelineContext:
    # ... 现有字段不变 ...
    rerank_query_text: str | None = None
    rerank_query_embedding: list[float] | None = None
```

读取规则：

- `Reranker` 在计算 `metadata_score`（tag 语义相似度）时，优先读 `rerank_query_embedding`，fallback 到 `query_embedding`
- VectorSearcher、BM25Searcher 只读 `query_embedding`，不感知覆盖字段
- `direct` 类型两覆盖字段均为 `None`，现有所有调用路径行为不变

> 覆盖字段为可选而非必填，保证 CLI / API / MCP 三条调用路径无需任何修改。

---

## 变换接口（位于 `query_transform.py`）

### 基类 `BaseQueryTransformer`

```python
class BaseQueryTransformer(ABC):
    @property
    def name(self) -> str:
        return self.__class__.__name__

    @abstractmethod
    async def transform(self, query_text: str) -> list[TransformedQuery]: ...
```

`name` 属性用于日志标识，子类可覆盖以提供自定义名称。

### 失败处理策略

所有依赖 LLM 调用的变换器，在 LLM 调用失败、网络错误或 JSON 解析失败时，均**静默降级**为 `IdentityTransformer` 的输出（返回原始 query，`route="direct"`），记录 `WARNING` 日志，不向上抛出异常。

与 `AutoTagger` 的失败处理策略一致，保证查询变换失败不阻断检索主流程。

### Config 类

```python
class RewriteTransformerConfig(BaseModel, frozen=True):
    max_tokens: int = 256
    temperature: float = 0.3       # 改写任务要求确定性，温度低

class RAGFusionTransformerConfig(BaseModel, frozen=True):
    num_variants: int = 4
    max_tokens: int = 512
    temperature: float = 0.7       # 变体生成需要多样性，温度略高

class HyDeTransformerConfig(BaseModel, frozen=True):
    max_tokens: int = 512
    temperature: float = 0.5
```

### 各实现输出契约

| 实现 | 输出 | route | embedding |
|------|------|-------|-----------|
| `IdentityTransformer` | `[TQ(text=query)]` | `direct` | `None` |
| `RewriteTransformer` | `[TQ(text=cleaned)]` | `direct` | `None` |
| `RAGFusionTransformer` | `[TQ(text=v₁), …, TQ(text=vₙ)]` | `fusion` × N | `None` |
| `HyDeTransformer` | `[TQ(text=original, embedding=hyp_vec)]` | `hyde` | 假设文档向量 |

`IdentityTransformer` 作为默认 fallback：无 LLM API Key 或变换模块未配置时自动降级。

---

### `IdentityTransformer`

无外部依赖，原样透传原始 query。

```python
class IdentityTransformer(BaseQueryTransformer):
    async def transform(self, query_text: str) -> list[TransformedQuery]:
        return [TransformedQuery(text=query_text, route="direct")]
```

---

### `RewriteTransformer`

```python
class RewriteTransformer(BaseQueryTransformer):
    def __init__(
        self,
        generator: LLMGenerator,
        config: RewriteTransformerConfig | None = None,
    ) -> None:
        self._generator = generator
        self._config = config or RewriteTransformerConfig()

    async def transform(self, query_text: str) -> list[TransformedQuery]:
        # on any failure → fallback to [TransformedQuery(text=query_text, route="direct")]
        ...
```

**LLM 调用方向**：

- System prompt：要求去噪、关键词补全、消除歧义，仅返回改写后的 query 字符串，无任何解释性前缀
- 若 LLM 返回结果为空或与原始 query 完全一致，直接使用原始 query（不视为失败，但无实际改写效果）
- JSON 解析不涉及此变换器（输出为纯文本字符串）

---

### `RAGFusionTransformer`

```python
class RAGFusionTransformer(BaseQueryTransformer):
    def __init__(
        self,
        generator: LLMGenerator,
        config: RAGFusionTransformerConfig | None = None,
    ) -> None:
        self._generator = generator
        self._config = config or RAGFusionTransformerConfig()

    async def transform(self, query_text: str) -> list[TransformedQuery]:
        # on any failure → fallback to [TransformedQuery(text=query_text, route="direct")]
        ...
```

**LLM 调用方向**：

- System prompt：生成 `config.num_variants` 条表述各异的变体 query，要求覆盖不同侧面和措辞，以 JSON array of strings 格式返回，无解释
- JSON 解析模式参考 `AutoTagger._parse_tags()`（处理 markdown 代码块包裹）
- 实际解析出的变体数量少于 `num_variants` 时不报错，使用实际数量；解析失败时 fallback

**输出约束**：每条变体的 `route="fusion"`，`embedding=None`（由 Dispatcher 批量嵌入）。

---

### `HyDeTransformer`

```python
class HyDeTransformer(BaseQueryTransformer):
    def __init__(
        self,
        generator: LLMGenerator,
        embedder: BaseEmbedder,
        config: HyDeTransformerConfig | None = None,
    ) -> None:
        self._generator = generator
        self._embedder = embedder
        self._config = config or HyDeTransformerConfig()

    async def transform(self, query_text: str) -> list[TransformedQuery]:
        # on any failure → fallback to [TransformedQuery(text=query_text, route="direct")]
        ...
```

**两步调用**：

1. LLM 生成假设文档片段：system prompt 方向为以权威文档摘录的口吻直接回答问题，不加"以下是……"等解释性前缀
2. `embedder.embed_batch([hypothesis])` 获取向量

`TransformedQuery.text` 保留原始 `query_text`（供日志/调试），`embedding` 为假设文档向量。任一步失败时 fallback。

---

### `ComposedTransformer`（预留）

当需要同时执行多种变换策略（如 RAG-Fusion + HyDE 混合）时：

```python
class ComposedTransformer(BaseQueryTransformer):
    def __init__(self, transformers: list[BaseQueryTransformer]) -> None:
        self._transformers = transformers

    async def transform(self, query_text: str) -> list[TransformedQuery]:
        results = await asyncio.gather(*[t.transform(query_text) for t in self._transformers])
        return [q for sublist in results for q in sublist]
```

各子变换器并发执行，输出列表平铺合并。Dispatcher 已能处理混合 route 列表，无需任何下游修改。当前 backlog 未要求此类，作为结构预留。

---

## Dispatcher（位于 `query_transform.py`）

```python
class QueryDispatcher:
    async def dispatch(
        self,
        queries: list[TransformedQuery],
        original_context: PipelineContext,  # 始终携带原始 query 的 text 和 embedding
        pipeline: RetrievalPipeline,
        embedder: BaseEmbedder,
    ) -> list[SearchHit]: ...
```

`original_context` 由调用方（`RetrievalPipeline.search()`）负责构造并传入；Dispatcher 不负责原始嵌入。

### 路由逻辑

#### `direct`

1. 若 `text == original_context.query_text`：直接复用 `original_context`，调用 `pipeline.execute(context)`
2. 若 text 已改写（≠ 原始）：用 `embedder` 重新嵌入，构造新 `PipelineContext`（`query_text/embedding` 为改写值，`rerank_query_*` 为原始值），调用 `pipeline.execute(context)`

#### `fusion`

1. 对 N 条变体并行嵌入（`embedder.embed_batch`）
2. 为每条变体构造独立 `PipelineContext`（变体的 text/embedding，`rerank_query_*` 指向原始 query）
3. 仅执行**检索阶段**，得到 N 组 `list[SearchHit]`
4. RRF 合并为单一 `list[SearchHit]`
5. 以 `original_context` 执行 Reranker

> fusion 仅在检索阶段使用变体向量扩大召回覆盖；重排序统一回归原始 query，保证评分语义一致。

#### `hyde`

1. 构造 `PipelineContext`（`query_embedding = TransformedQuery.embedding`，`query_text` 保持原始，`rerank_query_*` 为原始值）
2. 调用 `pipeline.execute(context)`（VectorSearcher 使用假设向量，Reranker 经由覆盖字段回退到原始 embedding）

#### 多 route 共存

单次调用中若同时存在多种 route（如 fusion + hyde 混合策略），各组独立执行后 RRF 合并，以 `original_context` 统一 rerank。当前 backlog 未涉及此场景，作为预留扩展路径，Dispatcher 接口已能承接。

---

## 数据流

```
user query_text
        │
        ▼
BaseQueryTransformer.transform()
        │
        ▼
list[TransformedQuery]        ← 本文档定义的通信结构
        │
        ▼
QueryDispatcher.dispatch(queries, original_context, pipeline, embedder)
        │
        ├── direct  ──→ pipeline.execute(context)
        │                       └── VectorSearcher + Reranker（全链路）
        │
        ├── fusion  ──→ embed × N（并行）
        │               └──→ VectorSearcher × N（并行）
        │                       └──→ RRF merge
        │                               └──→ Reranker(original_context)
        │
        └── hyde    ──→ pipeline.execute(context[query_emb=hyp_vec])
                                └── Reranker 读 rerank_query_embedding（原始）
        │
        ▼
list[SearchHit]
        │
        ▼
hydrate_results()             ← 现有管道，无需修改
```

---

## 实现约束与待决事项

### fusion 需要"仅检索"执行入口

当前 `RetrievalPipeline.execute()` 为全链路执行（检索 + Reranker），fusion 路由需要在 RRF 合并后统一 rerank，无法直接复用。

**待 P1-8 实现时处理**：为 `RetrievalPipeline` 增加 `retrieve_only()` 方法，在最后一个 `NodeType.SOURCE`/`MERGE` 节点后停止，不进入 `TRANSFORM`（Reranker）阶段。Dispatcher 持有 pipeline 引用，调用 `retrieve_only()` 而非 `execute()`，再手动调用 Reranker。

### Reranker 读覆盖字段

`Reranker.rerank()` 当前直接读 `context.query_embedding` 计算 `metadata_score`。实现覆盖字段后，该处需改为：

```python
rerank_emb = context.rerank_query_embedding or context.query_embedding
```

此为局部改动，不影响 Reranker 其他逻辑。
