"""
纯文本 / Markdown 文件解析器。

支持后缀：.txt  .md  .markdown
"""
from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from app.core.exceptions import ParsingError
from app.ingestion.parser import BaseParser, ParseResult, register_parser


@register_parser
class TextParser(BaseParser):
    """纯文本 / Markdown 文件解析器。"""

    supported_extensions: ClassVar[set[str]] = {".txt", ".md", ".markdown"}

    def parse(self, file_path: Path) -> ParseResult:
        """读取纯文本文件，返回去除首尾空白后的内容和元信息。

        Args:
            file_path: 文件路径。

        Returns:
            ParseResult 实例，metadata 包含 source_path、file_type、title、file_size。

        Raises:
            ParsingError: 文件编码无法解析或内容为空时抛出。
        """
        # 读取文件内容
        try:
            raw = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as exc:
            raise ParsingError(
                message=f"无法读取文件：{file_path}",
                detail=str(exc),
            ) from exc

        content = raw.strip()

        # 空文件不应进入后续 pipeline
        if not content:
            raise ParsingError(message=f"文件内容为空：{file_path}")

        metadata = {
            "source_path": str(file_path),
            "file_type": file_path.suffix.lower(),
            "title": file_path.stem,
            "file_size": file_path.stat().st_size,
        }

        return ParseResult(content=content, metadata=metadata)
