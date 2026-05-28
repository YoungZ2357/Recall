## Core



## Ingestion

### Auto-tagger

2026-03-30

- pipeline 位置：`parser → tagger → chunker → embedder → chunk_manager`，在 parse 后、chunk 前执行
- 输入：parser 产出的全文（超过 8000 字符时截断）；从 SQLite 查询系统已有的全部 unique tags 作为参考
- LLM 调用：复用 `LLMGenerator.raw_chat()`，system prompt 强制英文，要求仅返回 JSON array
- 输出：`list[str]` 写入所有 chunks 的 `tags` 字段（document 级别，所有 chunk 继承相同 tags）
- 失败处理：LLM 调用失败或 JSON 解析失败时 fallback 为 `[]`，记录 warning，不阻断 ingestion
- 可选启用：`tagger: AutoTagger | None`，`LLM_API_KEY` 未配置时自动跳过，零侵入

> tags 同时写入 SQLite `chunks.tags`（JSON 字符串）和 Qdrant point payload，两者保持一致。已有 tags 列表仅作参考——鼓励复用以保持一致性，允许 LLM 新建 tag。`get_all_unique_tags()` 扫描全表去重，个人知识库规模下无性能问题。

## Retrieve

### Cosine similarity dual-threshold filtering

2026-03-18

- VectorSearcher 和 Reranker 各持有独立的余弦相似度阈值，同时启用
- VectorSearcher 阈值宽松（默认 0.35），目的是粗筛掉明显不相关的噪声，保护召回率
- Reranker 阈值严格（默认 0.60，作用于加权 final_score），目的是保证最终输出精确率

> 两道阈值职责分离：召回阶段宁多勿漏，排序阶段宁缺勿滥。具体数值待评估脚本（P2-6）上线后根据 MRR/nDCG 调优。

### Reranker weighted scoring

2026-03-18

- 加权公式 `final_score = α·retrieval_score + β·metadata_score + γ·retention`，默认 α=0.6 / β=0.2 / γ=0.2
- metadata_score：查询时 Max-Pooling，收集 chunk tags 批量嵌入，取与 query embedding 最大余弦相似度，归一化到 [0,1] 后乘以 document weight
- retention：经典 Ebbinghaus 遗忘曲线，支持 prefer_recent（R）和 awaken_forgotten（1−R）两种模式
- fallback 策略：无 tags → metadata_score = 0.5，无访问记录 → prefer_recent 给 0 / awaken_forgotten 给 1

> tags 同时存 SQLite（source of truth）和 Qdrant payload（冗余，方便 payload filter 扩展）。α/β/γ 不做归一化约束，由配置者负责。

Ebbinghaus retention
$$
R = e^{-t/S}, \quad S = S_{\text{base}} \times (1 + \ln(1 + n))
$$

> $t$：距上次访问的小时数，$n$：累计访问次数，$S_{\text{base}}$ 默认 24h。访问越频繁 S 越大，遗忘越慢。

Metadata score
$$
\text{metadata\_score} = \max_{tag \in tags} \frac{\cos(\mathbf{q},\, \mathbf{e}_{tag}) + 1}{2} \times w_{doc}
$$

> $\mathbf{q}$：query embedding，$\mathbf{e}_{tag}$：tag embedding，$w_{doc}$：document weight ∈ [0, 1]。

### Reciprocal Rank Fusion (RRF)

2026-03-18

- `reciprocal_rank_fusion()` 是无状态函数，接收 `list[list[SearchHit]]`，输出合并后的 `list[SearchHit]`
- 守卫条件：≤1 条检索路径时不触发，原样透传
- RRF 公式：`score(d) = Σ 1/(k + rank_i(d))`，k 默认 60（`RRF_K` 环境变量可配置）
- 输出经 Min-Max 归一化到 [0, 1]，使其与 Reranker 的 metadata_score / retention_score 量级一致
- 合并后 SearchHit.source 设为 `"rrf"`

> RRF 是位置泛用的合并操作，设计上可用于检索层（合并 vector + BM25）和重排序层（合并多种 reranker，未来扩展）。当前默认拓扑：多路检索 → RRF → Reranker。Reranker 的 α 项已从 `vector_sim` 泛化为 `retrieval_score`，不再假设输入是余弦相似度。

> RRF 的操作对象无硬性类别限制——只要能投影为 SearchHit（chunk_id + score）即可参与合并。例如将 RerankResult 转为 SearchHit 后与另一路 retrieve 结果做 RRF 是被允许的。当前不单独定义拓扑模块；pipeline 内硬编码唯一拓扑，待出现多拓扑切换需求时再提取。

### Retrieval data structures carry no chunk text

2026-03-18

- 检索和重排序过程中的所有数据结构（SearchHit、RerankResult 等）只携带 chunk_id + 分数，不携带 chunk 文本
- content 的获取统一延迟到 pipeline 最终输出阶段，用 top-k chunk_ids 批量查询一次

> 职责分离：排序层只关心"谁排第几"，不关心"内容是什么"。同时为多路检索合并（BM25 + Vector + 未来路径）保持中间数据结构轻量，避免每条路径重复携带文本导致合并臃肿。

### Pipeline topology (hardcoded)

2026-03-19

- 当前拓扑：VectorSearcher → Normalizer → Reranker → output
- 拓扑在 `pipeline.py` 中硬编码，不可运行时切换
- 算子抽象设计见 `docs/instructions/retrieval/topo_abstract.md`
- 未来 DAG 编排引擎就绪后，当前拓扑将成为默认配置

> Pipeline 末端统一完成内容填充（content hydration）和访问记录（access recording），保证所有调用方（CLI/API/MCP）自动获得 Ebbinghaus 追踪。Rerank session 与写操作 session 分离：rerank 只读，access recording 写入后 commit。

## Evaluation

### Graded relevance via LLM-pooled qrels

2026-05-28

- 数据集生成三段式：`sample_chunks → synthesize_queries → expand_with_graded_pool`
- 源 chunk（生成 query 的那条）强制 grade=3，不送 LLM 评分（query 定义上必然可由它回答）
- 候选池来源：**vector-only** 召回 top-50（默认），绕开 reranker 避免把当前 reranker 的行为泄漏到 ground truth。`score_threshold=0.0` 取满池，不预过滤
- 评分粒度：每个 query 一次 LLM 调用，候选 chunk 以 `[#1] / [#2] / ...` 编号列出，要求返回 `[{id, grade}]`。批量横向比较 + 节省调用量。content 截断 1200 字符防止上下文过长
- Grading rubric（0-3）：3 直接回答 / 2 必要支撑信息 / 1 仅背景 / 0 无关。指令要求"宁可保守判 0"
- 失败 fallback：JSON 解析失败重试 1 次，仍失败则该 query 全部候选默认 grade=0（源 chunk 锚定不受影响）

> Pool bias 缓解：vector-only + 大池 + 源 chunk 锚定。三层叠加后，剩余偏差主要是"当前 retriever 完全召不回的真相关 chunk"，可接受。模型切换或检索器升级后建议重新生成数据集。

### Metrics via ir_measures

2026-05-28

- 标准指标套件：`nDCG@k`, `R(rel=2)@k`, `RR(rel=2)`, `AP(rel=2)`
- `rel>=2` 阈值用于二元指标（Recall / MRR / MAP）—— grade 1（仅背景）不计入相关
- nDCG 默认指数 gain（`2^rel - 1`），原生支持 graded relevance
- Schema 用 `metrics: dict[str, float]` 动态承载，便于扩展新指标而不改 ORM
- Run score 直接用 reranker 的 `final_score`，平局由 ir_measures 内部按 docid 字典序打破

> 抛弃自实现 metrics.py。ir_measures 是 TREC 标准库，pure Python，对接 IR 评估社区做法，避免自己重复造轮子和潜在的指标定义分歧。

### TestSetEntry schema

2026-05-28

- 字段：`query_id` (UUID4), `query`, `relevance: dict[chunk_id, grade]`, `source_document_id`, `source_chunk_id`, `metadata`
- `metadata.grader_model` 在 pool 扩展后填入；`generator_model` 在 synthesis 阶段填入
- annotate.py（人工标注）输出同样 schema，但 `relevance` 仅含 `{source_chunk_id: 3}`——不引入交互式 pool 评分，保持人工流程轻量
- 旧 binary schema（`ground_truth_chunk_ids: list[str]`）已断舍离，不做向后兼容
