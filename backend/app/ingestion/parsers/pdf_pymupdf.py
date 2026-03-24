"""
PDF parser using PyMuPDF (fitz) — lightweight, CPU-friendly text extraction.

Supported extensions: .pdf
"""
from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import fitz  # pymupdf

from app.core.exceptions import ParsingError
from app.ingestion.parser import BaseParser, ParseResult, register_parser


@register_parser
class PyMuPDFParser(BaseParser):
    """Extract text from PDF files using PyMuPDF."""

    supported_extensions: ClassVar[set[str]] = {".pdf"}

    def parse(self, file_path: Path) -> ParseResult:
        """Open the PDF with fitz and extract text page by page.

        Args:
            file_path: Path to the PDF file.

        Returns:
            ParseResult with page text joined by double newlines.
            metadata includes source_path, file_type, title, file_size, page_count.

        Raises:
            ParsingError: fitz cannot open the file or extracted text is empty.
        """
        try:
            doc = fitz.open(str(file_path))
        except Exception as exc:
            raise ParsingError(
                message=f"PyMuPDF failed to open: {file_path}",
                detail=str(exc),
            ) from exc

        pages: list[str] = []
        with doc:
            page_count = doc.page_count
            for page in doc:
                text = page.get_text()
                if text.strip():
                    pages.append(text.strip())

        content = "\n\n".join(pages)
        if not content:
            raise ParsingError(message=f"No text extracted from PDF: {file_path}")

        metadata = {
            "source_path": str(file_path),
            "file_type": file_path.suffix.lower(),
            "title": file_path.stem,
            "file_size": file_path.stat().st_size,
            "page_count": page_count,
        }

        return ParseResult(content=content, metadata=metadata)
