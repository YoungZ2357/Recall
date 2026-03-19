# Recall — Backlog

优先级排序的任务列表，按 P0 → P3 排列。每个任务独立可交付，无固定迭代周期。

状态标记：✅ 已完成 / 🔶 部分完成 / ❌ 未开始

---

## 已完成

以下任务已落地，不再跟踪。列出供上下文参考。

| # | 任务 | 说明 |
|---|------|------|
| ✅ | 项目脚手架 | pyproject.toml、目录结构、CLAUDE.md、docker-compose.yml、.env.example |
| ✅ | config.py | Pydantic Settings，环境变量加载 |
| ✅ | database.py | async engine + session factory (aiosqlite) |
| ✅ | models.py | Document、Chunk，Mapped[] 2.0 风格，UUID 主键，sync_status，content_hash |
| ✅ | schemas.py | 请求/响应 Pydantic 模型 |
| ✅ | exceptions.py | 自定义异常层级 |
| ✅ | vectordb.py | Qdrant async client 封装 |
| ✅ | chunk_manager.py | SQLite ↔ Qdrant 双写、删除、sync_status 状态机、一致性检查 |
| ✅ | repository.py | Document / Chunk 数据访问层（计划外产出） |
| ✅ | parser — text/pdf | TextFileConverter + MarkerCliConverter，parsers/ 子目录 |
| ✅ | chunker.py | RecursiveSplitStrategy（overlap 可配置）、FixedCountStrategy |
| ✅ | embedder.py | BaseEmbedder 抽象类 + APIEmbedder（GLM Embedding-3） |
| ✅ | ingestion pipeline | parser → chunker → embedder → chunk_manager 端到端 |
| ✅ | CLI ingest | `python -m app.cli ingest <path>`，单文件和目录 |
| ✅ | CLI reindex | 模型切换后批量 re-embedding |
| ✅ | VectorSearcher | Qdrant ANN 搜索，metadata filter，score threshold |
| ✅ | BM25Searcher stub | 接口定义，未实现 |
| ✅ | DB 连接测试 | test_sqalchemy_conn |

---

## P0 — 检索核心

项目的核心价值。没有这部分，系统只是一个文档存储。

| # | 任务 | 类型 | 描述 | 依赖 |
|---|------|------|------|------|
| P0-1 | reranker — 加权评分框架 | feature | `final_score = α·vector_sim + β·metadata_score + γ·retention`，α/β/γ 可配置，默认 0.6/0.2/0.2 | — |
| P0-2 | reranker — metadata_score | feature | tag 语义相似度（chunk tags vs query embedding cosine），文档级权重 | P0-1 |
| P0-3 | reranker — Ebbinghaus 记忆衰减 | feature | retention 基于最近访问时间和频次的遗忘曲线，支持"优先近期"和"唤醒遗忘"模式 | P0-1 |
| P0-4 | 访问记录追踪 | feature | SQLite 记录 chunk 被检索/命中的时间戳，供 Ebbinghaus 计算 | P0-3 |
| P0-5 | 检索 pipeline 编排 | feature | 串联 query_transform → searcher → reranker，返回排序后的 chunk 列表 | P0-1 |
| P0-6 | CLI search 命令 | feature | `python -m app.cli search "query"`，输出 top-k 结果及评分明细 | P0-5 |

---

## P1 — 查询变换 + API 层

提升检索质量并暴露 HTTP 接口。

| # | 任务 | 类型 | 描述 | 依赖 |
|---|------|------|------|------|
| P1-1 | query_transform — 查询改写 | feature | 基础查询清洗（去噪、关键词提取），作为其他策略的 fallback | — |
| P1-2 | query_transform — RAG-Fusion | feature | LLM 生成 N 个变体查询 → 结果合并去重 → Reciprocal Rank Fusion | P1-1 |
| P1-3 | query_transform — HyDE | feature | LLM 生成假设答案 → 嵌入 → 用假设向量检索 | P1-1 |
| P1-4 | FastAPI 应用初始化 | feature | main.py：app 实例、CORS、lifespan、dependencies.py | — |
| P1-5 | documents API | feature | POST 上传（触发 ingestion）、GET 列表、GET 详情、DELETE | P1-4 |
| P1-6 | search API | feature | POST /search（全链路）、POST /search/raw（跳过 refine） | P0-5, P1-4 |
| P1-7 | generate API（minimal） | feature | POST /generate，接收 context + query → LLM 回答 | P1-4 |

---

## P2 — 精炼管道 + 测试补全

提升输出质量，补齐测试欠账。

| # | 任务 | 类型 | 描述 | 依赖 |
|---|------|------|------|------|
| P2-1 | deduplicator.py | feature | content_hash 精确去重 + embedding cosine 模糊去重 | — |
| P2-2 | context_compressor.py | feature | 句子级相关性过滤，移除与 query 无关的内容 | — |
| P2-3 | summarizer.py | feature | LLM 摘要，控制输出 token 数 | — |
| P2-4 | refiner pipeline 编排 | feature | dedup → compress → summarize，每步可选跳过 | P2-1, P2-2, P2-3 |
| P2-5 | ingestion 单元测试 | test | parser 各格式、chunker 分块边界、embedder mock、pipeline 集成 | — |
| P2-6 | 检索质量评估脚本 | test | 手工 query-relevance 测试集（10–20 条），MRR/nDCG 基线 | P0-6 |
| P2-7 | API 集成测试 | test | httpx AsyncClient 测试各端点 | P1-4 |

---

## P3 — MCP + 前端 + Portfolio

对外集成和展示层。

| # | 任务 | 类型 | 描述 | 依赖 |
|---|------|------|------|------|
| P3-1 | MCP server — stdio | feature | mcp SDK stdio server，`python -m app.mcp.server` | P0-5 |
| P3-2 | MCP server — SSE | feature | 挂载到 FastAPI 的 SSE endpoint | P1-4, P3-1 |
| P3-3 | MCP tools | feature | search / ingest / list_documents / reindex 四个工具 | P3-1 |
| P3-4 | 前端初始化 | setup | Vite + React + TS + Ant Design，proxy 配置 | P1-4 |
| P3-5 | 文档管理页面 | feature | 列表、上传、删除 | P3-4 |
| P3-6 | 搜索页面 | feature | 搜索框 + 结果列表 + 评分明细 | P3-4 |
| P3-7 | 评分可视化 | feature | α/β/γ 各信号贡献比例展示 | P3-6 |
| P3-8 | Dockerfile + docker-compose | chore | 后端容器化，一键 `docker compose up` 全栈 | P3-4 |
| P3-9 | README + 演示 | chore | 架构图、GIF 演示、设计决策、Getting Started | P3-8 |

---

## Backlog（未排期）

不在 MVP 范围内，按需插入。

| 任务 | 说明 |
|------|------|
| BM25Searcher 实现 | SQLite FTS5 稀疏检索，混合召回（BM25 + 向量双路） |
| LocalEmbedder | BGE + ONNX Runtime 本地嵌入，优先级低于混合检索 |
| Tag embedding 预计算缓存 | ingestion 阶段将 tag embedding 持久化到 SQLite（tag_embeddings 表：tag_text, embedding, embedding_model），搜索时直接查表跳过 API 调用。cache miss（新 tag / 模型切换）时 fallback 到 API 并回填。模型切换时整表重算，复用现有 reindex 流程触发。不做频率淘汰——个人知识库 unique tag 规模有限（千级 ≈ 12MB），全量缓存比频率追踪更简单且命中率 100% |
| Graph signals | 知识图谱信号融入 reranker |
| Cross-Encoder reranker | 替代当前加权评分，需额外模型 |
| 单元测试覆盖率 ≥ 70% | 重点：reranker 评分、refiner pipeline、chunk_manager 状态转换 |
| 代码质量 | ruff lint + format、type hints 检查、docstring 补全 |

---

## 风险备忘

- **Ebbinghaus 参数调优**：缺乏标准答案，α/β/γ 先硬编码 0.6/0.2/0.2，后续通过评估脚本迭代
- **范围蔓延**：Graph signals、Cross-Encoder 已从 MVP 砍掉，不挤入当前 backlog
- **测试欠账**：ingestion 模块基本无测试覆盖，需在 P2 补齐
