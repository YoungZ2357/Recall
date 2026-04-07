# DAG 算子接口重构变动记录

**分支**：`feat/dag-engine`  
**涉及文件**：`retrieval/operators.py`、`retrieval/searcher.py`、`retrieval/reranker.py`、`retrieval/pipeline.py`、`core/schemas.py`、`docs/instructions/retrieval/topo_abstract.md`

---

## 背景

本次重构的目标是消除 `topo_abstract.md` 所设计的 DAG 算子系统与现有代码之间的两处结构性 gap，使现有算子实现统一的抽象接口，为后续 DAG 执行引擎的接入做好准备。

---

## 变更详情

### 1. `operators.py` — 成为检索模块的类型与接口中心

**之前**：定义 `PipelineContext`、`BaseRetriever`、`BaseReranker`，并从 `searcher.py` 导入 `SearchHit`。

**之后**：
- `SearchHit` **移入** `operators.py`（原定义位于 `searcher.py`），成为整个检索链路的唯一中间数据结构
- `SearchHit` 新增三个可选 breakdown 字段：`retrieval_score`、`metadata_score`、`retention_score`（由 Reranker 填充，其余阶段为 `None`）
- 依赖方向明确：`operators.py` ← `searcher.py` ← `reranker.py` ← `pipeline.py`，无循环依赖

`SearchHit` 各阶段的 `score` 语义：

| 阶段 | `source` | `score` 含义 |
|------|----------|--------------|
| 检索后 | `"vector"` / `"bm25"` | 余弦相似度 / BM25 原始分 |
| RRF 后 | `"rrf"` | 归一化 RRF 融合分 |
| Reranker 后 | `"rerank"` | 最终加权分（= α·retrieval + β·metadata + γ·retention） |

---

### 2. `searcher.py` — 移除 `SearchHit` 定义，Retriever 实现 `BaseRetriever`

**之前**：
- `SearchHit` 定义在此
- `BaseSearcher` 抽象类（`search(SearchQuery)`）
- `VectorSearcher(BaseSearcher)`、`BM25Searcher(BaseSearcher)`

**之后**：
- `SearchHit` 改为从 `operators.py` 导入
- `BaseSearcher` **移除**，由 `BaseRetriever` 取代
- `VectorSearcher(BaseRetriever)`、`BM25Searcher(BaseRetriever)`：
  - 新增 `retrieve(context: PipelineContext) → list[SearchHit]` 作为公共 DAG 接口
  - 原 `search(SearchQuery)` 改为内部方法 `_search(SearchQuery)`
  - `score_threshold` 从 `SearchQuery` 移至各 Searcher 的 `__init__` 参数（默认 0.35）
- `normalize_scores()` 和 `reciprocal_rank_fusion()` 保持不变；`normalize_scores()` 新增对 breakdown 字段的透传

---

### 3. `reranker.py` — 实现 `BaseReranker`，返回 `list[SearchHit]`

**之前**：
- 签名：`rerank(session, query_embedding, hits, retention_mode) → list[RerankResult]`
- `session` 由调用方（`pipeline.py`）管理生命周期并显式传入

**之后**：
- 实现 `BaseReranker`
- 签名：`rerank(hits: list[SearchHit], context: PipelineContext) → list[SearchHit]`
- `session` 生命周期内移：Reranker 通过 `context.session_factory` 自行开启和关闭 session
- 返回 `list[SearchHit]`（`source="rerank"`），breakdown 字段填充

---

### 4. `core/schemas.py` — 移除 `RerankResult`

**之前**：存在独立的 `RerankResult(BaseModel)` 用于承载 Reranker 输出。

**之后**：`RerankResult` **移除**。其功能完全由扩展后的 `SearchHit` 承担。

`RetrievalResult` 保持不变（仍是 pipeline 的最终输出，在内容注水阶段从 `SearchHit` 组装）。

---

### 5. `pipeline.py` — 使用新接口，统一 session 管理

**之前**：
- 直接构造 `SearchQuery` 传入 `searcher.search()`
- 显式开启 session 传入 `reranker.rerank()`

**之后**：
- 构造 `PipelineContext` 一次，传给所有算子
- 调用 `retriever.retrieve(context)` 和 `reranker.rerank(hits, context)`
- 移除 pipeline 层的 rerank session 管理代码（已内移至 Reranker）
- RRF 融合后增加一次 `normalize_scores()`，符合 `topo_abstract.md` 的标准化约束规则

---

### 6. `topo_abstract.md` — 修订过时描述

两处更新：

1. **Reranker 输出类型**：补充说明输出的 `SearchHit` 中 `score` = `final_score`，并携带三个 breakdown 可选字段。原文仅写 `list[SearchHit]` 不够准确。

2. **MergeDetector**：补充说明其守卫逻辑已内嵌于 `reciprocal_rank_fusion()` 函数，无需单独实现为独立算子。

---

## 接口对照表

| 算子 | 重构前签名 | 重构后签名 |
|------|-----------|-----------|
| `VectorSearcher` | `search(SearchQuery) → list[SearchHit]` | `retrieve(PipelineContext) → list[SearchHit]` |
| `BM25Searcher` | `search(SearchQuery) → list[SearchHit]` | `retrieve(PipelineContext) → list[SearchHit]` |
| `Reranker` | `rerank(session, embedding, hits, mode) → list[RerankResult]` | `rerank(hits, context) → list[SearchHit]` |

---

## 功能保障

- CLI `search` 命令（`--verbose` 评分明细）：无需改动，其读取的是 `RetrievalResult`，字段不变
- Ebbinghaus 访问记录：仍由 `pipeline.py` 在内容注水阶段统一写入，不受本次重构影响
- 双阈值过滤（VectorSearcher 粗筛 + Reranker 精筛）：`score_threshold` 移至 `__init__` 后行为完全等价
