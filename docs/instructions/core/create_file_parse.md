# Task: 实现文件解析器基类与纯文本解析器

对应 Sprint Plan Issue 2.1（部分）。本次只实现基类 + 工厂注册 + TextParser，PDF 解析器后续单独做。

------

## 上下文

Recall 的 ingestion pipeline 链路为 `parser → chunker → embedder → chunk_manager`。parser 的职责是接收文件路径，输出**纯文本字符串**（一个文档一个字符串），后续 chunker 负责分块。parser 不做分块，不做嵌入，不操作数据库。

### 文件结构

当前 `ingestion/` 目录下只有 `__init__.py`（可能为空）。本次需要创建以下文件：

```
app/ingestion/
├── __init__.py          # 已存在，不改动
├── parser.py            # 基类 + 工厂注册 + 对外入口函数
└── parsers/
    ├── __init__.py      # 空文件
    └── text.py          # .txt / .md 解析
```

------

## 前置依赖

实现前先阅读以下文件，理解项目约定：

- `@CLAUDE.md` — 编码规范（中文注释、类型标注要求等）
- `@backend/app/core/exceptions.py` — 使用已定义的 `IngestionError`（如果不存在，在 `parser.py` 中临时定义一个占位异常 `class ParseError(Exception): pass`，并加 `# TODO: 迁移到 core/exceptions.py`）
- `@backend/app/config.py` — 了解配置结构（本次可能用不到，但需确认）

------

## 实现要求

### 1. `parser.py` — 基类与工厂

#### 1.1 数据类：解析结果

定义一个 dataclass 作为 parser 的统一返回类型：

```python
@dataclass
class ParseResult:
    """文件解析结果。"""
    content: str          # 解析出的纯文本内容
    metadata: dict[str, Any]  # 元信息（来源路径、文件类型、标题等）
```

`metadata` 至少包含：

- `source_path: str` — 原始文件路径
- `file_type: str` — 文件后缀（如 `".txt"`、`".md"`）
- `title: str | None` — 从文件名推断的标题（去后缀），调用方可覆盖

#### 1.2 抽象基类

```python
from abc import ABC, abstractmethod

class BaseParser(ABC):
    """文件解析器基类。"""

    # 子类必须声明自己支持的文件后缀，如 {".txt", ".md"}
    supported_extensions: ClassVar[set[str]]

    @abstractmethod
    def parse(self, file_path: Path) -> ParseResult:
        """解析文件，返回纯文本内容和元信息。

        Args:
            file_path: 文件路径，调用前已由工厂确认文件存在且后缀匹配。

        Returns:
            ParseResult 实例。

        Raises:
            ParseError / IngestionError: 解析失败时抛出。
        """
        ...
```

注意事项：

- `parse` 是**同步方法**。文件 I/O 是 CPU-bound，不需要 async。如果 pipeline 需要异步，由 pipeline 层用 `asyncio.to_thread` 包装
- 不要在基类中添加 `__init__` 参数，保持零配置实例化。如果子类需要配置（如 PDF 解析的模型路径），由子类自行在 `__init__` 中声明

#### 1.3 工厂注册机制

使用一个模块级的 registry dict，通过装饰器或显式注册：

```python
# 模块级注册表
_parser_registry: dict[str, type[BaseParser]] = {}

def register_parser(parser_cls: type[BaseParser]) -> type[BaseParser]:
    """注册解析器类，将其 supported_extensions 映射到 registry。"""
    for ext in parser_cls.supported_extensions:
        if ext in _parser_registry:
            raise ValueError(f"后缀 {ext} 已被 {_parser_registry[ext].__name__} 注册")
        _parser_registry[ext] = parser_cls
    return parser_cls
```

#### 1.4 对外入口函数

```python
def get_parser(file_path: str | Path) -> BaseParser:
    """根据文件后缀获取对应的解析器实例。

    Args:
        file_path: 文件路径。

    Returns:
        匹配的 BaseParser 实例。

    Raises:
        FileNotFoundError: 文件不存在。
        ParseError / IngestionError: 不支持的文件格式。
    """
```

实现逻辑：

1. 将 `file_path` 转为 `Path` 对象
2. 检查文件存在性（`Path.exists()`），不存在则抛 `FileNotFoundError`
3. 提取后缀（`.suffix.lower()`），从 `_parser_registry` 查找
4. 未找到则抛异常，消息中列出当前支持的所有后缀
5. 返回 parser 类的实例（`parser_cls()`）

#### 1.5 自动注册

在 `parser.py` 底部，通过导入触发 parsers 子模块的注册：

```python
# 触发各 parser 子模块的注册
from app.ingestion.parsers import text  # noqa: F401, E402
# 后续新增 parser 在这里加一行 import 即可
```

这样 `from app.ingestion.parser import get_parser` 时，所有已实现的 parser 自动可用。

------

### 2. `parsers/text.py` — 纯文本解析器

```python
@register_parser
class TextParser(BaseParser):
    """纯文本 / Markdown 文件解析器。"""

    supported_extensions: ClassVar[set[str]] = {".txt", ".md", ".markdown"}
```

`parse` 方法实现：

1. 读取文件内容：`file_path.read_text(encoding="utf-8")`
2. 如果读取失败（`UnicodeDecodeError` 等），catch 后抛 `ParseError`，消息包含文件路径和原始错误
3. 去除首尾空白（`.strip()`）
4. 如果内容为空，抛 `ParseError`（空文件不应进入后续 pipeline）
5. 从文件名推断 title：`file_path.stem`（即去掉后缀的文件名）
6. 组装并返回 `ParseResult`

完整的 `metadata` 字段：

```python
metadata = {
    "source_path": str(file_path),
    "file_type": file_path.suffix.lower(),
    "title": file_path.stem,
    "file_size": file_path.stat().st_size,  # 字节数
}
```

------

## 不需要做的事

- **不做 PDF 解析**——MarkerCliConverter 后续单独 issue
- **不做 chunking**——那是 chunker.py 的职责
- **不做 async I/O**——文件读取是同步的，pipeline 层负责线程包装
- **不在 `__init__.py` 中 re-export**——保持 `__init__.py` 为空，避免不必要的模块加载
- **不做 MIME type 检测**——按后缀分发足够，不引入额外依赖
- **不写单元测试**——测试在 Issue 2.9 中统一做

------

## 代码规范

- 所有注释和 docstring 使用中文
- 类型标注完整，使用 `from __future__ import annotations`
- 导入顺序：标准库 → 第三方 → 项目内部，各组之间空一行
- 无全局实例，无 print 语句
- 异常消息包含足够的上下文信息（文件路径、后缀名等）

------

## 验证清单

完成后确认以下事项：

- [ ] `from app.ingestion.parser import get_parser, BaseParser, ParseResult` 导入无报错
- [ ] `get_parser("test.txt")` 返回 `TextParser` 实例
- [ ] `get_parser("test.md")` 返回 `TextParser` 实例
- [ ] `get_parser("test.pdf")` 抛出异常，消息提示不支持的格式
- [ ] `get_parser("nonexistent.txt")` 抛出 `FileNotFoundError`
- [ ] `TextParser().parse(valid_txt_file)` 返回 `ParseResult`，`content` 非空，`metadata` 包含所有预期字段
- [ ] `TextParser().parse(empty_txt_file)` 抛出异常
- [ ] 所有类和函数都有中文 docstring
- [ ] ruff check 无错误