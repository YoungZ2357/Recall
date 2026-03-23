"""
PDF 文件解析器，通过 Marker CLI 将 PDF 转换为 Markdown。

支持后缀：.pdf
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import ClassVar

from app.core.exceptions import ParsingError
from app.ingestion.parser import BaseParser, ParseResult, register_parser

_MARKER_TIMEOUT_S = 300


@register_parser
class MarkerCliParser(BaseParser):
    """通过 marker_single CLI 解析 PDF，返回 Markdown 文本内容。"""

    supported_extensions: ClassVar[set[str]] = {".pdf"}

    def parse(self, file_path: Path) -> ParseResult:
        """调用 marker_single 将 PDF 转为 Markdown，返回内容和元信息。

        Args:
            file_path: PDF 文件路径。

        Returns:
            ParseResult 实例，metadata 包含 source_path、file_type、title、file_size。

        Raises:
            ParsingError: marker_single 执行失败、输出文件缺失或内容为空时抛出。
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                result = subprocess.run(
                    [
                        "marker_single",
                        str(file_path),
                        "--output_format", "markdown",
                        "--output_dir", tmp_dir,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=_MARKER_TIMEOUT_S,
                )
            except subprocess.TimeoutExpired as exc:
                raise ParsingError(
                    message=f"marker_single 超时（>{_MARKER_TIMEOUT_S}s）：{file_path}",
                    detail=str(exc),
                ) from exc
            except FileNotFoundError as exc:
                raise ParsingError(
                    message="marker_single 未找到，请确认已安装 marker-pdf",
                    detail=str(exc),
                ) from exc

            if result.returncode != 0:
                raise ParsingError(
                    message=f"marker_single 执行失败（exit {result.returncode}）：{file_path}",
                    detail=result.stderr,
                )

            # marker_single 输出路径：<output_dir>/<stem>/<stem>.md
            output_md = Path(tmp_dir) / file_path.stem / f"{file_path.stem}.md"
            if not output_md.exists():
                raise ParsingError(
                    message=f"marker_single 未生成预期输出文件：{output_md}",
                    detail=result.stdout,
                )

            content = output_md.read_text(encoding="utf-8").strip()

        if not content:
            raise ParsingError(message=f"解析结果为空：{file_path}")

        metadata = {
            "source_path": str(file_path),
            "file_type": file_path.suffix.lower(),
            "title": file_path.stem,
            "file_size": file_path.stat().st_size,
        }

        return ParseResult(content=content, metadata=metadata)
