## Core



## Ingestion



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

> tags 仅存 SQLite，不存 Qdrant payload，避免 payload 膨胀和双写一致性问题。α/β/γ 不做归一化约束，由配置者负责。

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

##