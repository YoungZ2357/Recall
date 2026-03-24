# Task: 实现 Qdrant 客户端封装 — `backend/app/core/vectordb.py`

对应 Sprint Plan Issue 1.6。

## 上下文

Recall 是一个 personal RAG 检索服务，架构上 **SQLite 是 source of truth，Qdrant 是 rebuildable derived storage**，两者通过 UUID 共享主键关联。`vectordb.py` 是 Qdrant 的唯一访问入口，上层消费者包括：

- `chunk_manager.py`：双写（SQLite → Qdrant）、删除、一致性检查
- `searcher.py`（Sprint 3）：ANN 向量检索，支持 metadata filter
- `query_transform.py`（Sprint 3）：RAG-Fusion 需要 batch search

## 前置依赖

实现前先阅读以下已有文件，理解项目约定：

- `CLAUDE.md` — 编码规范和项目约定（如果已存在）
- `backend/app/config.py` — 获取 Qdrant 连接配置（host、port、collection_name、vector_dimension 等）
- `backend/app/core/models.py` — 了解 Chunk 模型的字段定义，特别是 UUID 主键和 sync_status
- `backend/app/core/exceptions.py` — 使用已定义的 VectorDBError 等异常类型（如果尚未创建，先跳过异常转换，用 TODO 标记）

如果上述文件尚未实现，根据 Sprint Plan 和 README 中的描述做合理假设，并在代码注释中标注假设内容。

## 实现要求

### 类设计

创建 `QdrantService` 类，持有 `AsyncQdrantClient` 实例。不要使用同步 client。

```python
class QdrantService:
    """Qdrant 向量数据库服务封装。
    
    作为 Qdrant 的唯一访问入口，对上层屏蔽 SDK 细节。
    生命周期由 FastAPI lifespan 管理。
    """
```

### 需要封装的方法

按功能分组，共 4 类：

**1. Collection 管理**

- `ensure_collection(dimension: int, distance: Distance = Distance.COSINE) -> None`
  - 幂等操作：collection 存在且配置匹配则跳过，不存在则创建
  - 如果已存在但 dimension 不匹配，抛异常而非静默覆盖（防止 embedding 模型切换后误操作）
  - FastAPI lifespan startup 时调用
- `delete_collection() -> None`
  - reindex 场景使用，整个 collection 删除重建比逐条删除更干净
- `get_collection_info() -> CollectionInfo | None`
  - 返回 collection 元信息（点数量、向量维度等），不存在时返回 None
  - 用于健康检查和一致性校验

**2. 数据写入**

- `upsert(points: list[PointStruct]) -> None`
  - 批量 upsert（Qdrant upsert 语义天然幂等，相同 ID 覆盖）
  - 内部按 batch_size 分片，避免单次请求过大
  - 空列表时直接返回，不发请求
- `delete(point_ids: list[str]) -> None`
  - 按 point IDs 批量删除
  - 空列表时直接返回

**3. 检索**

- `search(query_vector: list[float], top_k: int = 10, score_threshold: float | None = None, query_filter: Filter | None = None) -> list[ScoredPoint]`
  - 单次 ANN 搜索，返回结果包含 id、score、payload
  - 由 searcher.py 调用
- `search_batch(queries: list[SearchRequest]) -> list[list[ScoredPoint]]`
  - 批量搜索，一次 RPC 发送多个查询
  - 由 RAG-Fusion 场景使用（N 个变体查询并行检索）

**4. 一致性维护**

- `get_points(point_ids: list[str], with_payload: bool = True, with_vectors: bool = False) -> list[Record]`
  - 按 IDs 批量获取 points
  - chunk_manager 用于校验 SQLite 中 synced 状态的 chunks 是否真的存在于 Qdrant
- `count() -> int`
  - collection 中总点数，快速比对两侧数量

### 生命周期管理

- 构造函数接收配置参数（host、port、grpc_port 等），**内部创建** `AsyncQdrantClient` 实例
- 提供 `async close() -> None` 方法关闭连接
- 支持 async context manager（`__aenter__` / `__aexit__`）
- 不要在模块级别创建全局实例，实例化由 FastAPI dependencies 或 lifespan 负责

### 错误处理

- catch Qdrant SDK 的异常（`UnexpectedResponse`、`ResponseHandlingException` 等），转换为项目自定义的 `VectorDBError`
- 原始异常信息要保留在 `__cause__` 中（用 `raise VectorDBError(...) from e`）
- 如果 `exceptions.py` 尚未实现，先定义一个临时的 `VectorDBError(Exception)` 在文件顶部，加 TODO 标记后续迁移

### 类型标注

- 所有公开方法必须有完整的类型标注
- Qdrant SDK 的类型（`PointStruct`、`ScoredPoint`、`Filter`、`SearchRequest`、`Record`、`Distance` 等）直接从 `qdrant_client.models` 导入并在方法签名中使用，不要自己再包一层 wrapper type
- 返回类型直接用 SDK 类型，不做额外转换——类型转换是上层（chunk_manager / searcher）的职责

## 代码风格

- 全部 async/await
- SQLAlchemy 2.0 风格的 Mapped[] 是 ORM 层的事，vectordb.py 不涉及
- 日志使用 `logging.getLogger(__name__)`，关键操作（collection 创建、批量 upsert 数量、异常）记录日志
- 不要写任何 print 语句

## 不需要做的事

- ❌ 不封装 scroll / 遍历接口（MVP 不需要）
- ❌ 不封装 recommend / discover 接口
- ❌ 不封装 snapshot 管理
- ❌ 不做 payload index 管理（后续按需添加）
- ❌ 不写单元测试（Issue 1.9 冒烟测试单独处理）
- ❌ 不创建 FastAPI dependency（那是 dependencies.py 的职责）

## Payload 约定

upsert 时 payload 由上层（chunk_manager）构造，vectordb.py 不关心 payload 内容。但为了给 chunk_manager 开发者参考，在 docstring 中注明推荐的 payload 结构：

```python
# 推荐 payload 结构（由 chunk_manager 构造）:
{     
    "document_id": str,      # 所属文档 UUID
    "chunk_index": int,      # chunk 在文档中的序号
    "tags": list[str],       # 标签列表，用于 metadata filter 和 reranker
    "created_at": str,       # ISO format 时间戳
}
```

## 验收标准

1. 文件位于 `backend/app/core/vectordb.py`
2. `QdrantService` 类包含上述所有方法，类型标注完整
3. 异常处理到位，不泄漏 Qdrant SDK 异常到上层
4. batch_size 分片逻辑正确（upsert 和 delete）
5. 所有方法都是 async
6. 无全局实例，无 print 语句
7. 可通过 `python -c "from app.core.vectordb import QdrantService"` 验证导入无误