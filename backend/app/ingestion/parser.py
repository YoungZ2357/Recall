"""
文件解析器基类、工厂注册机制和对外入口函数。

使用示例：
    from app.ingestion.parser import get_parser

    parser = get_parser("notes.txt")
    result = parser.parse(Path("notes.txt"))
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from app.core.exceptions import UnsupportedFileTypeError


# ============================================================
# 解析结果数据类
# ============================================================

@dataclass
class ParseResult:
    """文件解析结果。"""

    content: str                 # 解析出的纯文本内容
    metadata: dict[str, Any]     # 元信息：source_path, file_type, title 等


# ============================================================
# 抽象基类
# ============================================================

class BaseParser(ABC):
    """文件解析器基类。子类须声明 supported_extensions 并实现 parse()。"""

    # 子类必须声明支持的文件后缀，如 {".txt", ".md"}
    supported_extensions: ClassVar[set[str]]

    @abstractmethod
    def parse(self, file_path: Path) -> ParseResult:
        """解析文件，返回纯文本内容和元信息。

        Args:
            file_path: 文件路径，调用前已由工厂确认文件存在且后缀匹配。

        Returns:
            ParseResult 实例。

        Raises:
            ParsingError: 解析失败时抛出（编码错误、空文件等）。
        """
        ...


# ============================================================
# 工厂注册机制
# ============================================================

# 模块级注册表：后缀 → 解析器类
_parser_registry: dict[str, type[BaseParser]] = {}


def register_parser(parser_cls: type[BaseParser]) -> type[BaseParser]:
    """注册解析器类，将其 supported_extensions 映射到注册表。

    Args:
        parser_cls: 继承自 BaseParser 的解析器类。

    Returns:
        原始类（支持作为装饰器使用）。

    Raises:
        ValueError: 后缀已被其他解析器注册时抛出。
    """
    for ext in parser_cls.supported_extensions:
        if ext in _parser_registry:
            raise ValueError(
                f"后缀 {ext} 已被 {_parser_registry[ext].__name__} 注册，"
                f"无法再注册 {parser_cls.__name__}"
            )
        _parser_registry[ext] = parser_cls
    return parser_cls


def get_parser(file_path: str | Path) -> BaseParser:
    """根据文件后缀获取对应的解析器实例。

    Args:
        file_path: 文件路径（字符串或 Path 对象）。

    Returns:
        匹配后缀的 BaseParser 实例。

    Raises:
        FileNotFoundError: 文件不存在。
        UnsupportedFileTypeError: 不支持的文件格式。
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"文件不存在：{path}")

    ext = path.suffix.lower()
    parser_cls = _parser_registry.get(ext)

    if parser_cls is None:
        supported = sorted(_parser_registry.keys())
        raise UnsupportedFileTypeError(
            file_type=ext,
            detail=f"当前支持的格式：{supported}",
        )

    return parser_cls()


# ============================================================
# 触发子模块注册（保持在文件末尾）
# ============================================================

from app.ingestion.parsers import text  # noqa: F401, E402
