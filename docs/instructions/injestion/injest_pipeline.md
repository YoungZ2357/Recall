# Task: 实现 Ingestion Pipeline 编排 — `backend/app/ingestion/pipeline.py`

对应 Sprint Plan Issue 2.6。

---

## 上下文

Recall 的文档摄入链路为 `parser → chunker → embedder → chunk_manager`。本次实现 `IngestionPipeline` 类，负责将这四个组件串联为一个原子操作：接收文件路径，完成从解析到双端存储（SQLite + Qdrant）的全流程。

**核心设计决策：** 采用方案 A（类组织），pipeline 持有各组件实例，通过 FastAPI DI 注入。pipeline 对外始终是原子的——要么全部完成，要么失败回滚，不暴露中间阶段。

### 架构定位

```
CLI / API endpoint
       │
       ▼
  IngestionPipeline          ← 本次实现
       │
       ├── BaseParser         → ParseResult（纯文本 + 元数据）
       ├── BaseChunker        → list[ChunkData]（分块结果）
       ├── BaseEmbedder       → list[list[float]]（向量）
       └── ChunkManager       → 双写 SQLite + Qdrant，管理 sync_status
```

### 消费者

- `app/cli.py`（Issue 2.7）：CLI 导入命令 `python -m app.cli ingest <file_path>`
- `app/api/documents.py`（Sprint 4 Issue 4.6）：POST 上传文档触发 ingestion
- `app/mcp/tools.py`（Sprint 5 Issue 5.4）：MCP ingest tool

---

## 前置依赖

实现前**必须先阅读**以下文件，理解各组件的实际接口签名：

- `@CLAUDE.md` — 编码规范
- `@backend/app/ingestion/parser.py` — `BaseParser` 基类和 `ParseResult` 定义，`get_parser()` 工厂函数
- `@backend/app/ingestion/chunker.py` — `BaseChunker` 基类，`split()` 方法签名和返回类型
- `@backend/app/ingestion/embedder.py` — `BaseEmbedder` 基类，`embed_batch()` 方法签名
- `@backend/app/core/chunk_manager.py` — `ChunkManager` 类，双写入口方法签名
- `@backend/app/core/models.py` — `Document` 和 `Chunk` ORM 模型，字段定义
- `@backend/app/core/exceptions.py` — 异常层级定义
- `@backend/app/config.py` — 配置结构

**关键：以实际代码中的方法签名为准。** 如果下文描述的接口与实际代码有出入，以实际代码为准，并在 pipeline 代码中加注释说明差异。

---

## 文件结构

```
app/ingestion/
├── __init__.py       # 已存在，不改动
├── parser.py         # 已实现
├── parsers/          # 已实现
├── chunker.py        # 已实现
├── embedder.py       # 已实现
└── pipeline.py       # ← 本次创建
```

---

## 实现要求

### 1. `IngestionPipeline` 类

```python
from __future__ import annotations

class IngestionPipeline:
    """文档摄入管道。

    串联 parser → chunker → embedder → chunk_manager，
    将原始文件转化为已索引的文档记录。
    组件实例通过构造函数注入，生命周期由外部管理。
    """

    def __init__(
        self,
        parser_factory: Callable[[Path], BaseParser],  # get_parser 函数
        chunker: BaseChunker,
        embedder: BaseEmbedder,
        chunk_manager: ChunkManager,
    ) -> None:
        self._get_parser = parser_factory
        self._chunker = chunker
        self._embedder = embedder
        self._chunk_manager = chunk_manager
```

**设计说明：**

- `parser_factory` 接收 `get_parser` 函数而非具体 parser 实例，因为不同文件格式需要不同的 parser，pipeline 需要按文件后缀动态选择。
- 其他三个组件是实例注入，因为它们不依赖具体文件。
- 不在 `__init__` 中做任何 I/O 操作。

### 2. `ingest` 方法 — 单文件导入（核心方法）

```python
async def ingest(self, file_path: Path) -> Document:
    """导入单个文件，返回创建的 Document ORM 对象。

    完整流程：解析 → 分块 → 嵌入 → 双端存储。
    任一环节失败则抛出异常，不做部分写入。

    Args:
        file_path: 待导入文件的绝对路径。

    Returns:
        创建的 Document 对象（已持久化，sync_status 为 SYNCED）。

    Raises:
        FileNotFoundError: 文件不存在。
        ParseError: 解析失败。
        ChunkError: 分块结果为空。
        EmbeddingError: 嵌入失败。
        SyncError: 双端写入失败。
    """
```

**方法内部流程（严格按此顺序）：**

#### Step 1: 校验文件

```python
file_path = Path(file_path).resolve()
if not file_path.is_file():
    raise FileNotFoundError(f"文件不存在: {file_path}")
```

#### Step 2: 解析

```python
parser = self._get_parser(file_path)
parse_result = parser.parse(file_path)  # 同步方法，返回 ParseResult
```

- `parser.parse()` 是同步方法。如果需要不阻塞事件循环，用 `await asyncio.to_thread(parser.parse, file_path)` 包装。
- 阅读 `parser.py` 确认 `parse()` 的实际签名。如果它已经是 async 的，直接 await。

#### Step 3: 分块

```python
chunks = self._chunker.split(parse_result.content)  # 同步方法，返回分块列表
```

- 阅读 `chunker.py` 确认 `split()` 的实际参数和返回类型。
- 如果分块结果为空列表，抛出异常（空文档不应写入索引）：

```python
if not chunks:
    raise IngestionError(f"分块结果为空: {file_path}")
```

#### Step 4: 嵌入

```python
texts = [chunk.content for chunk in chunks]  # 提取文本列表
embeddings = await self._embedder.embed_batch(texts)  # async 方法
```

- `embed_batch` 是 async 方法，直接 await。
- 阅读 `embedder.py` 确认入参类型（`list[str]`）和返回类型（`list[list[float]]`）。
- 校验返回数量一致性：

```python
if len(embeddings) != len(chunks):
    raise EmbeddingError(
        f"嵌入数量不匹配: {len(chunks)} chunks, {len(embeddings)} embeddings"
    )
```

#### Step 5: 双端存储

```python
document = await self._chunk_manager.create_document_with_chunks(
    parse_result=parse_result,
    chunks=chunks,
    embeddings=embeddings,
)
```

- 阅读 `chunk_manager.py` 确认双写入口方法的**实际名称和签名**。上面写的 `create_document_with_chunks` 是预期名称，实际可能不同。
- 如果 `chunk_manager` 没有一个统一的"创建 Document + Chunks + 向量"方法，需要拆成多步调用，但确保在同一个数据库事务内完成（Document 和 Chunks 的 SQLite 写入必须原子）。
- Qdrant 写入在 SQLite 事务提交后进行。如果 Qdrant 写入失败，SQLite 中的 chunks 的 sync_status 应保持 PENDING（由 chunk_manager 管理，pipeline 不直接操作状态）。

#### Step 6: 返回

```python
return document
```

### 3. `ingest_batch` 方法 — 批量导入

```python
async def ingest_batch(
    self,
    file_paths: list[Path],
) -> BatchIngestResult:
    """批量导入多个文件。

    逐文件调用 ingest()，单个文件失败不影响其他文件。

    Args:
        file_paths: 待导入文件路径列表。

    Returns:
        BatchIngestResult 包含成功列表和失败列表。
    """
```

**实现要点：**

- 逐文件串行调用 `self.ingest()`，**不做并发**（嵌入 API 有速率限制，Qdrant 写入需要顺序保证）。
- 单个文件失败时 catch 异常，记录到失败列表，继续处理下一个文件。
- 使用 `logger.error()` 记录失败详情。

**`BatchIngestResult` 定义：**

```python
@dataclass
class BatchIngestResult:
    """批量导入结果。"""
    succeeded: list[Document]       # 成功导入的文档列表
    failed: list[FailedIngest]      # 失败记录

@dataclass
class FailedIngest:
    """单个文件导入失败的记录。"""
    file_path: Path
    error: str                       # 异常消息，不存储异常对象
```

将 `BatchIngestResult` 和 `FailedIngest` 定义在 `pipeline.py` 文件顶部（`IngestionPipeline` 类之前）。

---

## 日志

使用标准库 logging：

```python
import logging

logger = logging.getLogger(__name__)
```

在以下位置输出日志：

- `ingest` 开始时：`logger.info("开始导入文件: %s", file_path)`
- 每个步骤完成后：`logger.debug("解析完成: %d 字符", len(parse_result.content))`
- `ingest` 成功时：`logger.info("文件导入成功: %s, %d chunks", file_path, len(chunks))`
- `ingest_batch` 中单文件失败时：`logger.error("文件导入失败: %s, 错误: %s", file_path, str(e))`
- `ingest_batch` 完成时：`logger.info("批量导入完成: %d 成功, %d 失败", ...)`

---

## 不需要做的事

- **不实现 CLI 命令** — 那是 Issue 2.7 的职责
- **不实现 FastAPI endpoint** — 那是 Sprint 4 的职责
- **不实现 dry-run / preview** — 后续迭代再加
- **不做文件去重检查**（同一文件重复导入） — 可以在 chunk_manager 层通过 content_hash 处理
- **不做并发导入** — 串行足够，并发引入速率限制和事务竞争问题
- **不在 `__init__.py` 中 re-export** — 保持 `__init__.py` 不变
- **不写单元测试** — 测试在 Issue 2.9 中统一做
- **不引入新依赖** — pipeline 本身只做编排，不需要额外的第三方库

---

## 异常处理策略

`ingest` 方法**不做 catch**。各组件抛出的异常（ParseError、EmbeddingError、SyncError 等）直接向上传播，由调用方（CLI / API）决定如何处理。

`ingest_batch` 方法在循环内 catch `Exception`，记录失败并继续：

```python
for path in file_paths:
    try:
        doc = await self.ingest(path)
        result.succeeded.append(doc)
    except Exception as e:
        logger.error("文件导入失败: %s, 错误: %s", path, e)
        result.failed.append(FailedIngest(file_path=path, error=str(e)))
```

---

## 代码规范

- 所有注释和 docstring 使用中文
- 类型标注完整，使用 `from __future__ import annotations`
- 文件顶部 `from __future__ import annotations`
- 导入顺序：标准库 → 第三方 → 项目内部，各组之间空一行
- 无全局实例，无 print 语句
- `logger = logging.getLogger(__name__)` 紧跟 import 块之后

---

## 验证清单

完成后确认以下事项：

- [ ] `from app.ingestion.pipeline import IngestionPipeline, BatchIngestResult` 导入无报错
- [ ] `IngestionPipeline.__init__` 接收 4 个组件参数，无 I/O 操作
- [ ] `ingest()` 方法内部按 校验 → 解析 → 分块 → 嵌入 → 存储 顺序执行
- [ ] `ingest()` 方法对分块结果为空、嵌入数量不匹配有防御性检查
- [ ] `ingest()` 中调用 chunk_manager 的方法名和参数与 `chunk_manager.py` 实际代码一致
- [ ] `ingest()` 中 parser.parse() 如果是同步方法，已用 `asyncio.to_thread` 包装
- [ ] `ingest_batch()` 单文件失败不影响后续文件
- [ ] `BatchIngestResult` 和 `FailedIngest` 是 dataclass，定义在类之前
- [ ] 关键步骤有 logger 输出
- [ ] 没有引入新的第三方依赖
- [ ] 没有直接操作数据库 session 或 Qdrant client（全部委托给 chunk_manager）
- [ ] 所有类和方法都有中文 docstring
- [ ] ruff check 无错误