# Issue 2.2: chunker.py — 分块策略实现

## 任务概述

在 `backend/app/ingestion/chunker.py` 中实现分块模块，包含基类 `BaseChunker` 和两个策略：`RecursiveSplitStrategy`（递归分割）、`FixedCountStrategy`（定长分割）。不使用 LangChain 或任何外部文本分割库，全部自行实现。

---

## 前置依赖

开始前先阅读以下文件，理解已有的模式和约定：

- `@backend/app/core/exceptions.py` — 异常层级，chunker 使用 `IngestionError` 子类
- `@backend/app/ingestion/parser.py` — 了解 `ParseResult` 数据结构（chunker 的上游输入）
- `@backend/app/config.py` — 了解配置模式，chunker 参数后续由 config 驱动

---

## 文件结构

```
backend/app/ingestion/
    ├── chunker.py      ← 本次实现（基类 + 两个策略，全部放在同一个文件）
    ├── parser.py        （已有）
    └── ...
```

只创建 `chunker.py` 一个文件。两个策略体量不大，不需要拆成子目录。

---

## 数据类型

### ChunkData

定义分块结果的数据类，作为 chunker 的统一输出类型：

```python
@dataclass
class ChunkData:
    """单个分块的数据。"""
    content: str          # 分块文本内容
    chunk_index: int      # 在当前文档中的序号（从 0 开始）
    metadata: dict[str, Any]  # 继承自上游 + 分块产生的元信息
```

`metadata` 应包含：
- 上游 `ParseResult.metadata` 的全部字段（透传）
- `chunk_strategy: str` — 使用的策略名称（如 `"recursive"`, `"fixed_count"`）
- `chunk_size_configured: int` — 配置的目标 chunk size
- `char_count: int` — 该 chunk 的实际字符数

**注意：** `ChunkData` 暂时放在 `chunker.py` 内。如果后续 pipeline 编排（Issue 2.6）发现多个模块都需要 import 这个类型，再提取到 `ingestion/types.py`。

---

## 基类

```python
class BaseChunker(ABC):
    """分块策略基类。"""

    # 子类必须声明策略名称，用于 metadata 标记和 config 路由
    strategy_name: ClassVar[str]

    @abstractmethod
    def split(self, text: str, metadata: dict[str, Any] | None = None) -> list[ChunkData]:
        """将文本切分为 ChunkData 列表。

        Args:
            text: 待切分的纯文本（来自 ParseResult.content）。
            metadata: 上游传入的元信息（来自 ParseResult.metadata），会被透传到每个 ChunkData。

        Returns:
            ChunkData 列表，按 chunk_index 升序排列。
            如果文本为空或过短不需要分块，返回包含整篇文本的单元素列表。

        Raises:
            IngestionError: 分块过程中遇到不可恢复的错误。
        """
        ...
```

注意事项：
- `split` 是**同步方法**，与 parser 保持一致
- 不抛出 chunker 专属的异常子类（当前异常层级中没有定义 `ChunkingError`，直接使用 `IngestionError`）
- 空文本处理：如果 `text` 为空字符串或 None，不要抛异常，返回空列表。上游 parser 已经过滤了空文件，但防御性编程仍然需要

---

## 策略 1：RecursiveSplitStrategy

### 核心逻辑

按多级分隔符递归切分文本，在语义边界处断开，尽量不在句中切断。

### 参数

```python
@dataclass
class RecursiveSplitStrategy(BaseChunker):
    strategy_name: ClassVar[str] = "recursive"

    chunk_size: int = 512           # 目标 chunk 大小（字符数）
    chunk_overlap: int = 64         # 重叠区域大小（字符数）
    separators: list[str] | None = None  # 自定义分隔符层级，None 时使用默认值
    min_chunk_size: int = 50        # 低于此长度的尾部碎片合并到前一个 chunk
```

### 默认分隔符层级

当 `separators` 为 None 时，使用以下默认层级（从高到低优先级）：

```python
DEFAULT_SEPARATORS = [
    "\n\n",       # 段落
    "\n",         # 换行
    "。",         # 中文句号
    ".",          # 英文句号（后跟空格时视为句边界）
    "；",         # 中文分号
    ";",          # 英文分号
    "，",         # 中文逗号
    ",",          # 英文逗号
    " ",          # 空格
    "",           # 逐字符（最后兜底）
]
```

### 分割算法

实现 `_recursive_split(text: str, separators: list[str]) -> list[str]`：

1. 取当前最高优先级的分隔符 `sep = separators[0]`
2. 用 `sep` 拆分 `text` 为若干片段
3. 遍历片段，将连续的短片段合并，直到累计长度接近 `chunk_size`
4. 如果某个片段本身超过 `chunk_size`，对该片段递归调用 `_recursive_split(fragment, separators[1:])`
5. 当 `separators` 为空列表（即兜底的 `""` 已用完），按 `chunk_size` 硬切

合并片段时的 overlap 处理：
- 每个 chunk 的末尾 `chunk_overlap` 个字符会作为下一个 chunk 的开头
- overlap 不应超过 `chunk_size` 的 40%，如果 `chunk_overlap >= chunk_size * 0.4`，实际使用 `int(chunk_size * 0.4)`

### 边界情况

- 文本长度 <= `chunk_size`：不分块，返回整篇文本作为单个 ChunkData
- 分隔符恰好在文本末尾：不产生空的尾部 chunk
- 连续多个分隔符（如多个空行）：合并后视为单次分隔
- 尾部碎片长度 < `min_chunk_size`：合并到最后一个 chunk

---

## 策略 2：FixedCountStrategy

### 核心逻辑

将文档分割为大致固定数量的 chunk，带最大长度约束和自适应 overlap。适合需要控制 chunk 数量的场景。

### 参数

```python
@dataclass
class FixedCountStrategy(BaseChunker):
    strategy_name: ClassVar[str] = "fixed_count"

    target_chunks: int = 10         # 目标分块数量
    max_chunk_size: int = 1024      # 单 chunk 最大字符数（硬约束）
    min_doc_size: int = 256         # 文档短于此值则不分块
    overlap_ratio: float = 0.1      # overlap 占 chunk_size 的比例
    min_overlap: int = 50           # overlap 下限
    max_overlap: int = 200          # overlap 上限
    min_split_size: int = 50        # 尾部碎片合并阈值
```

### 分割算法

实现 `split` 方法：

1. **短文档保护**：`len(text) <= min_doc_size` → 不分块，返回整篇
2. **计算参数**：
   - `base_chunk_size = len(text) // target_chunks`
   - `actual_chunk_size = min(base_chunk_size, max_chunk_size)`
   - `raw_overlap = int(actual_chunk_size * overlap_ratio)`
   - `actual_overlap = clamp(raw_overlap, min_overlap, max_overlap)`
   - 如果 `actual_overlap >= actual_chunk_size`，将 `actual_overlap` 设为 0（避免死循环）
3. **滑动窗口切分**：
   - `step = actual_chunk_size - actual_overlap`
   - 从 `start = 0` 开始，每次取 `text[start : start + actual_chunk_size]`
   - `start += step` 直到覆盖全部文本
4. **尾部碎片处理**：最后一个 chunk 如果长度 < `min_split_size`，合并到前一个 chunk

### 边界情况

- `target_chunks` 大于实际可分块数（文档很短）：退化为不分块
- `base_chunk_size` 极小（如 < 20 字符）：直接不分块
- `actual_overlap >= actual_chunk_size`：设 overlap 为 0 而非抛异常

---

## 工厂函数

提供一个便捷函数，根据策略名称创建实例：

```python
def get_chunker(strategy: str = "recursive", **kwargs) -> BaseChunker:
    """根据策略名称创建分块器实例。

    Args:
        strategy: 策略名称（"recursive" 或 "fixed_count"）。
        **kwargs: 传递给策略构造函数的参数。

    Returns:
        BaseChunker 实例。

    Raises:
        IngestionError: 不支持的策略名称。
    """
```

实现：用简单的 dict mapping，不需要装饰器 registry（因为只有两个策略且在同一个文件中）：

```python
_STRATEGY_MAP: dict[str, type[BaseChunker]] = {
    "recursive": RecursiveSplitStrategy,
    "fixed_count": FixedCountStrategy,
}
```

---

## 不需要做的事

- **不引入 LangChain 或 langchain-text-splitters**——全部自行实现
- **不做 token 级别的分割**——当前阶段按字符数切分，token 计数是 embedder 的职责
- **不做语义分割**——SemanticChunker 是后续增强项，不在本 issue 范围内
- **不做 Markdown 结构感知分割**——`RecursiveSplitStrategy` 的默认分隔符中 `\n\n` 和 `\n` 已经能在段落/行级别自然断开，Markdown 标题级分割留到后续 issue
- **不写单元测试**——测试在 Issue 2.9 中统一做
- **不在 chunker 中处理 embedding**——那是 embedder 的职责
- **不定义新的异常子类**——直接使用 `IngestionError`
- **不做异步**——与 parser 保持一致，pipeline 层负责线程包装

---

## 代码规范

- 所有注释和 docstring 使用中文
- 类型标注完整，文件顶部添加 `from __future__ import annotations`
- 导入顺序：标准库 → 第三方 → 项目内部，各组之间空一行
- 使用 `@dataclass` 定义策略类（继承 ABC + dataclass 双重装饰）
- 无全局实例，无 print 语句
- 常量（如 `DEFAULT_SEPARATORS`）用模块级大写变量定义
- 日志使用 `logging.getLogger(__name__)`，关键路径记录 debug 级别日志（如分块数量、参数计算结果）

---

## 验证清单

完成后确认以下事项：

- [ ] `from app.ingestion.chunker import BaseChunker, RecursiveSplitStrategy, FixedCountStrategy, ChunkData, get_chunker` 导入无报错
- [ ] `get_chunker("recursive")` 返回 `RecursiveSplitStrategy` 实例
- [ ] `get_chunker("fixed_count")` 返回 `FixedCountStrategy` 实例
- [ ] `get_chunker("nonexistent")` 抛出 `IngestionError`
- [ ] `RecursiveSplitStrategy().split("")` 返回空列表
- [ ] `RecursiveSplitStrategy().split("短文本")` 返回包含一个 ChunkData 的列表
- [ ] `RecursiveSplitStrategy(chunk_size=100).split(长文本)` 返回多个 ChunkData，每个 content 长度 <= 100 + overlap
- [ ] `RecursiveSplitStrategy(chunk_size=100).split(长文本)` 的相邻 chunk 之间存在 overlap（后一个 chunk 的开头与前一个 chunk 的结尾有重叠文本）
- [ ] `FixedCountStrategy().split("短于256字符的文本")` 返回单个 ChunkData（不分块）
- [ ] `FixedCountStrategy(target_chunks=5).split(长文本)` 返回约 5 个 ChunkData（允许因 max_chunk_size 约束而多于 5 个）
- [ ] 所有 ChunkData 的 `chunk_index` 从 0 开始连续递增
- [ ] 所有 ChunkData 的 `metadata` 包含 `chunk_strategy`、`chunk_size_configured`、`char_count` 字段
- [ ] 传入 `metadata={"source_path": "/test.md"}` 时，输出的每个 ChunkData.metadata 中包含 `source_path`
- [ ] 尾部碎片被正确合并（不存在长度 < min_chunk_size / min_split_size 的尾部 chunk）
- [ ] 所有类和函数都有中文 docstring
- [ ] `ruff check` 无错误