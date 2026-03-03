# Recall — Sprint 规划

基于 2 周迭代，共 6 个 Sprint，预计 12 周完成 MVP。

全部推翻重来，从旧代码中挑选可复用部分改造。MVP 范围内砍掉 Graph signals，Cross-Encoder 用加权评分替代，前端推迟到 CLI/API 验证完成后再做。

---

## Sprint 1：基础设施（Week 1–2）

**目标：** 搭好地基——数据库、向量库连接、ORM 模型、配置管理，跑通最小写入链路（手动脚本写入一条 chunk 到 SQLite + Qdrant）。

| # | Issue | 类型 | 描述 |
|---|-------|------|------|
| 1.1 | 项目脚手架初始化 | setup | pyproject.toml、目录结构、CLAUDE.md、docker-compose.yml（Qdrant）、.env.example |
| 1.2 | config.py 配置模块 | feature | Pydantic Settings，环境变量加载（API keys、DB 路径、Qdrant 地址、embedding 模型选择） |
| 1.3 | SQLite + SQLAlchemy async 连接 | feature | database.py：async engine + session factory，alembic 不做（个人项目直接 create_all） |
| 1.4 | ORM 模型定义 | feature | models.py：Document、Chunk 表，Mapped[] 2.0 风格，UUID 主键，sync_status 字段，content_hash |
| 1.5 | Pydantic schemas | feature | schemas.py：请求/响应模型，与 ORM 解耦 |
| 1.6 | Qdrant 客户端封装 | feature | vectordb.py：collection 创建/检查、upsert、search、delete，async client |
| 1.7 | chunk_manager 生命周期管理 | feature | chunk_manager.py：写入流程（SQLite → Qdrant 双写）、删除流程、sync_status 状态机、一致性检查 |
| 1.8 | exceptions 模块 | feature | 自定义异常层级：DocumentNotFound、EmbeddingError、VectorDBError 等 |
| 1.9 | 冒烟测试 | test | 手动脚本验证：创建 Document + Chunk → 写入 SQLite → 写入 Qdrant → 查询验证双边一致 |

**Sprint 1 交付标准：** `python -m scripts.smoke_test` 跑通，SQLite 和 Qdrant 中能看到同一条数据。

---

## Sprint 2：文档摄入（Week 3–4）

**目标：** 完成 ingestion 全链路——文件解析、分块、嵌入，通过 CLI 命令导入一个文档并在 Qdrant 中可搜索。

| # | Issue | 类型 | 描述 |
|---|-------|------|------|
| 2.1 | 文件解析器 parser.py | feature | DocumentConverter 基类 + TextFileConverter（.txt/.md）+ MarkerCliConverter（PDF，复用旧代码改造） |
| 2.2 | 分块策略 chunker.py | feature | ChunkStrategy 基类（策略模式）、RecursiveSplitStrategy（overlap 可配置）、FixedCountStrategy |
| 2.3 | 在线嵌入 embedder.py — APIEmbedder | feature | GLM Embedding-3 调用封装，async httpx，批量嵌入，维度校验，速率限制 |
| 2.4 | 离线嵌入 embedder.py — LocalEmbedder | feature | BGE 系列 + ONNX Runtime，避免 PyTorch 依赖，懒加载模型 |
| 2.5 | Embedder 基类与切换逻辑 | feature | BaseEmbedder 抽象类，config 驱动模型选择，维度不匹配时阻止混用 |
| 2.6 | ingestion pipeline 编排 | feature | 串联 parser → chunker → embedder → chunk_manager，单文档端到端导入 |
| 2.7 | CLI 导入命令 | feature | `python -m app.cli ingest <file_path>`，支持单文件和目录批量导入 |
| 2.8 | 重新嵌入流程 | feature | reindex 命令：模型切换后批量重新 embedding，chunk_manager 标记 dirty → 重新处理 → 更新状态 |
| 2.9 | ingestion 单元测试 | test | parser 各格式解析、chunker 分块边界、embedder mock 测试、pipeline 集成测试 |

**Sprint 2 交付标准：** CLI 导入一个 PDF 文档后，`qdrant-web-ui` 中能看到对应向量，SQLite 中 sync_status 全部为 synced。

---

## Sprint 3：检索核心（Week 5–6）

**目标：** 实现完整检索链路——查询变换、向量召回、多信号重排序。这是项目最核心的 Sprint。

| # | Issue | 类型 | 描述 |
|---|-------|------|------|
| 3.1 | searcher.py 向量召回 | feature | Qdrant ANN 搜索封装，支持 top-k 配置、score threshold 过滤、metadata filter |
| 3.2 | query_transform.py — RAG-Fusion | feature | 多查询生成（LLM 调用生成 N 个变体查询），结果合并去重，Reciprocal Rank Fusion |
| 3.3 | query_transform.py — HyDE | feature | Hypothetical Document Embedding：LLM 生成假设答案 → 嵌入 → 用假设向量检索 |
| 3.4 | query_transform.py — 查询改写 | feature | 基础查询清洗（去噪、关键词提取），作为 RAG-Fusion/HyDE 的 fallback |
| 3.5 | reranker.py — 加权评分框架 | feature | `final_score = α·vector_similarity + β·metadata_score + γ·retention`，α/β/γ 可配置 |
| 3.6 | reranker.py — metadata_score | feature | tag 语义相似度计算（chunk tags vs query embedding cosine），文档级别权重 |
| 3.7 | reranker.py — Ebbinghaus 记忆衰减 | feature | retention 计算：基于 chunk 最近访问时间和访问频次的遗忘曲线，支持"优先近期"和"唤醒遗忘"两种模式 |
| 3.8 | 访问记录追踪 | feature | SQLite 中记录 chunk 被检索/命中的时间戳，供 Ebbinghaus 计算使用 |
| 3.9 | 检索 pipeline 编排 | feature | 串联 query_transform → searcher → reranker，返回排序后的 chunk 列表 |
| 3.10 | CLI 搜索命令 | feature | `python -m app.cli search "query"`，输出 top-k 结果及评分明细 |
| 3.11 | 检索质量评估脚本 | test | 手工构造 query-relevance 测试集（10–20 条），计算 MRR/nDCG，作为后续调参基线 |

**Sprint 3 交付标准：** CLI 搜索返回语义相关的结果，评分明细中能看到三个信号的各自贡献，评估脚本有基线数据。

---

## Sprint 4：精炼管道 + API 层（Week 7–8）

**目标：** 实现 refiner pipeline 提升输出质量，同时暴露 HTTP API 供外部调用。

| # | Issue | 类型 | 描述 |
|---|-------|------|------|
| 4.1 | deduplicator.py | feature | chunk 去重：基于 content_hash 精确去重 + embedding cosine 相似度模糊去重（阈值可配） |
| 4.2 | context_compressor.py | feature | 上下文压缩：移除与 query 无关的句子，保留关键信息。初版用 extractive 方式（句子级相关性过滤） |
| 4.3 | summarizer.py | feature | 对压缩后的 context 做摘要（LLM 调用），控制输出 token 数，适配下游消费 |
| 4.4 | refiner pipeline.py 编排 | feature | dedup → compress → summarize，每步可选跳过，pipeline 配置化 |
| 4.5 | FastAPI 应用初始化 | feature | main.py：app 实例、CORS、lifespan（启动时初始化 DB + Qdrant 连接）、dependencies.py |
| 4.6 | documents API | feature | documents.py：POST 上传文档（触发 ingestion）、GET 列表、GET 详情、DELETE |
| 4.7 | search API | feature | search.py：POST /search（全链路：transform → recall → rerank → refine）、POST /search/raw（跳过 refine） |
| 4.8 | generate API（minimal） | feature | generate.py：POST /generate，接收 context + query，调用 LLM 生成回答。最小实现，仅作 fallback |
| 4.9 | API 集成测试 | test | httpx AsyncClient 测试各端点，覆盖正常流程和错误情况 |

**Sprint 4 交付标准：** `uvicorn app.main:app` 启动后，通过 curl/httpx 调用 /search 返回经过精炼的上下文，/search/raw 返回原始排序结果。

---

## Sprint 5：MCP 服务（Week 9–10）

**目标：** 通过 MCP 暴露检索能力，Claude Desktop 能直接调用。同时补充测试覆盖率和代码质量。

| # | Issue | 类型 | 描述 |
|---|-------|------|------|
| 5.1 | MCP server.py — stdio 模式 | feature | 基于 mcp SDK 的 stdio server，独立进程运行，`python -m app.mcp.server` |
| 5.2 | MCP server.py — SSE 模式 | feature | 挂载到 FastAPI 的 SSE endpoint，支持远程 MCP 客户端连接 |
| 5.3 | MCP tools.py — search | feature | 完整检索 pipeline 暴露为 MCP tool，参数：query、top_k、mode（refined/raw） |
| 5.4 | MCP tools.py — ingest | feature | 文档导入工具，参数：file_path 或文本内容 |
| 5.5 | MCP tools.py — list_documents | feature | 列出已索引文档及状态 |
| 5.6 | MCP tools.py — reindex | feature | 触发重新嵌入 |
| 5.7 | Claude Desktop 集成测试 | test | 手动验证：配置 MCP server → Claude Desktop 中调用 search → 确认返回结果 |
| 5.8 | 单元测试补全 | test | 覆盖率目标 ≥ 70%，重点覆盖 reranker 评分逻辑、refiner pipeline、chunk_manager 状态转换 |
| 5.9 | 代码质量清理 | chore | ruff lint + format、type hints 检查、docstring 补全、移除 dead code |

**Sprint 5 交付标准：** Claude Desktop 配置 Recall MCP 后，能通过对话触发 search 并获得高质量上下文。测试覆盖率 ≥ 70%。

---

## Sprint 6：前端 + Portfolio 打磨（Week 11–12）

**目标：** 最小可用前端，README 和文档打磨到 portfolio 展示水平。

| # | Issue | 类型 | 描述 |
|---|-------|------|------|
| 6.1 | 前端项目初始化 | setup | Vite + React + TypeScript + Ant Design，proxy 配置连接后端 |
| 6.2 | 文档管理页面 | feature | 文档列表（状态标签）、上传入口、删除操作 |
| 6.3 | 搜索页面 | feature | 搜索框 + 结果列表（显示 chunk 内容、来源文档、综合评分） |
| 6.4 | 搜索结果评分可视化 | feature | 展示 α/β/γ 各信号贡献比例，辅助调参 |
| 6.5 | README 最终版 | chore | 架构图、GIF 演示、设计决策说明、Getting Started 验证通过 |
| 6.6 | CLAUDE.md 完善 | chore | 编码规范、项目约定、模块职责说明 |
| 6.7 | Dockerfile + docker-compose 完整化 | chore | 后端容器化，一键 `docker compose up` 启动全栈 |
| 6.8 | 端到端演示验证 | test | 完整流程录屏：导入文档 → 搜索 → 查看结果 → MCP 调用，确保无报错 |

**Sprint 6 交付标准：** `docker compose up` 一键启动，前端可操作文档管理和搜索，README 含演示 GIF，代码可作为 portfolio 展示。

---

## 风险与注意事项

**技术风险：** Ebbinghaus 记忆衰减的参数调优缺乏标准答案，Sprint 3 中应预留时间做参数实验而非追求完美实现。α/β/γ 的默认值建议先硬编码一组合理值（如 0.6/0.2/0.2），后续通过评估脚本迭代。

**范围控制：** Graph signals 和 Cross-Encoder 已从 MVP 砍掉，如果中途想加回来，建议作为 Sprint 6 之后的独立迭代，不要挤入现有 Sprint。

**依赖管理：** Sprint 2 的 LocalEmbedder（ONNX）可能遇到环境兼容性问题。如果卡住，优先保证 APIEmbedder 可用，LocalEmbedder 降级为 P1。

**旧代码复用：** 每个 Sprint 开始前花半天审查旧代码中可复用的部分，改造后纳入新架构，避免 Sprint 中途发现需要大改。
