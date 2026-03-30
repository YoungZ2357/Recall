"""
PDF parser via MinerU Precision Cloud API.

Calls MinerU to convert a PDF to Markdown, then returns the result as a ParseResult.

Supported extensions: .pdf
"""
from __future__ import annotations

import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import ClassVar

logger = logging.getLogger(__name__)

from app.core.exceptions import ParsingError
from app.ingestion.parser import BaseParser, ParseResult

# Resolve toolkit path relative to this file:
# backend/app/ingestion/parsers/pdf_mineru.py → parents[4] = project root
_TOOLKIT_DIR = Path(__file__).parents[4] / "toolkit" / "external_parser"
if str(_TOOLKIT_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLKIT_DIR))

try:
    from mineru import MinerUError as _MinerUError
    from mineru import parse_pdf as _mineru_parse_pdf
except ImportError as _e:
    raise ImportError(
        f"Cannot import MinerU toolkit from {_TOOLKIT_DIR}. "
        "Ensure toolkit/external_parser/mineru.py exists."
    ) from _e


class MinerUParser(BaseParser):
    """Parse PDF via MinerU Precision Cloud API, returning Markdown text.

    Not auto-registered. Use --pdf-parser mineru in the ingest CLI to select it.
    Requires MINERU_API_KEY environment variable.
    """

    supported_extensions: ClassVar[set[str]] = {".pdf"}

    def __init__(
        self,
        model_version: str = "pipeline",
        language: str = "ch",
        api_key: str | None = None,
    ) -> None:
        self._model_version = model_version
        self._language = language
        self._api_key = api_key

    def parse(self, file_path: Path) -> ParseResult:
        """Upload PDF to MinerU API, wait for result, return Markdown content.

        Args:
            file_path: Path to the PDF file.

        Returns:
            ParseResult with Markdown content and metadata.

        Raises:
            ParsingError: MinerU API failure, timeout, missing API key, or empty output.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                md_path, json_path = _mineru_parse_pdf(
                    file_path=file_path,
                    output_dir=Path(tmp_dir),
                    model_version=self._model_version,
                    language=self._language,
                    api_key=self._api_key,
                )
            except EnvironmentError as exc:
                raise ParsingError(
                    message="MINERU_API_KEY 未设置，无法使用 MinerU 解析器",
                    detail=str(exc),
                ) from exc
            except _MinerUError as exc:
                raise ParsingError(
                    message=f"MinerU 解析失败：{file_path.name}",
                    detail=str(exc),
                ) from exc

            content = md_path.read_text(encoding="utf-8").strip()
            title = _extract_title_from_json(json_path) or file_path.stem

        if not content:
            raise ParsingError(message=f"MinerU 解析结果为空：{file_path}")

        metadata = {
            "source_path": str(file_path),
            "file_type": file_path.suffix.lower(),
            "title": title,
            "file_size": file_path.stat().st_size,
            "parser": "mineru",
        }

        return ParseResult(content=content, metadata=metadata)


def _extract_title_from_json(json_path: Path | None) -> str | None:
    """Extract the document title from MinerU JSON output.

    Looks for the first text block with text_level=1 on page 0.
    Returns None if json_path is absent, unreadable, or contains no H1 on page 0.
    """
    if json_path is None or not json_path.exists():
        return None
    try:
        blocks = json.loads(json_path.read_text(encoding="utf-8"))
        for block in blocks:
            if block.get("text_level") == 1 and block.get("page_idx") == 0:
                text = block.get("text", "").strip()
                if text:
                    return text
    except Exception:
        logger.warning("Failed to extract title from MinerU JSON: %s", json_path)
    return None
