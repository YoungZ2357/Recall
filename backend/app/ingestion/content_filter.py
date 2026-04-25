"""
Post-parse content filter: detects and removes reference/appendix sections.

Pipeline position: parser → content_filter (optional) → chunker → ...

Usage:
    result = content_filter(text)
    if result.cut_point is not None:
        print(f"Removed {result.removed_chars} chars: {result.cut_reason}")
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ============================================================
# Pattern constants
# ============================================================

# Reference section heading patterns (case-insensitive).
# Matched against stripped paragraph text; max length enforced separately.
_REF_HEADING_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r, re.IGNORECASE)
    for r in [
        # Plain English variants
        r"^references$",
        r"^bibliography$",
        r"^works cited$",
        r"^literature cited$",
        # Chinese variants
        r"^参考文献$",
        r"^参考资料$",
        r"^引用文献$",
        # Numbered prefixes: "7. References", "7 References", "VII. References"
        r"^(?:\d+\.?\s+|[IVXLCDM]+\.?\s+)references$",
        r"^(?:\d+\.?\s+|[IVXLCDM]+\.?\s+)bibliography$",
        r"^(?:\d+\.?\s+|[IVXLCDM]+\.?\s+)works cited$",
        r"^(?:\d+\.?\s+|[IVXLCDM]+\.?\s+)literature cited$",
        r"^(?:\d+\.?\s+|[IVXLCDM]+\.?\s+)参考文献$",
        r"^(?:\d+\.?\s+|[IVXLCDM]+\.?\s+)参考资料$",
    ]
]
_REF_HEADING_MAX_LEN = 30

# Appendix section heading patterns.
_APPENDIX_HEADING_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r, re.IGNORECASE)
    for r in [
        r"^appendix$",
        r"^appendices$",
        r"^附录$",
        # Numbered: "Appendix A", "Appendix 1"
        r"^appendix\s+[A-Z0-9]",
        # Single letter + title: "A. Mathematical Derivations" or "A Hyperparameters"
        r"^[A-Z]\.?\s+\w+",
        r"^supplementary\s+material",
        r"^supplemental\s+information",
    ]
]
_APPENDIX_HEADING_MAX_LEN = 50

# Citation density features (6 categories).
# Each entry is a compiled pattern; a paragraph scores 1 point per category matched.
_CITATION_FEATURES: list[re.Pattern[str]] = [
    re.compile(r"\[\d+(?:[,\s]+\d+)*\]"),                                # [1], [1, 2]
    re.compile(r"\[[A-Za-z][A-Za-z0-9]*\+?\d{2,4}\]"),                  # [Bel+15], [BVNB13]
    re.compile(r"\(\s*\d{4}[a-z]?\s*\)|,\s*\d{4}[a-z]?\b"),            # (2023), (2019a), , 2024
    re.compile(r"\b[A-Z][a-z]+,\s+[A-Z]\."),                            # LastName, F. (author-initial)  # noqa: E501
    re.compile(r"doi[:.]", re.IGNORECASE),                               # doi: / doi.
    re.compile(r"https?://"),                                            # URLs
    re.compile(r"arXiv:", re.IGNORECASE),                                # arXiv:
    re.compile(                                                          # academic keywords + journal abbrevs  # noqa: E501
        r"\b(?:Proceedings|Conference|Journal|Trans\.|Vol\.|pp\.|et al\.|J\.|Rev\.|Proc\.|Conf\.)\b",  # noqa: E501
        re.IGNORECASE,
    ),
]
_TOTAL_FEATURES = len(_CITATION_FEATURES)  # 8

# Tuning constants
_MD_HEADING_RE = re.compile(r"^(#+)\s+(.*)")  # matches "## Section Title"

_POSITION_PRIOR_THRESHOLD = 0.40   # ignore anchors in the first 40% of the document
_DENSITY_MIN = 0.25                 # minimum density to count a paragraph as "dense"
_DENSITY_CONFIRM_WINDOW = 3         # look at this many paragraphs after the anchor
_DENSITY_CONFIRM_MIN = 2            # at least this many must be dense to confirm
_FALLBACK_WINDOW_MIN = 5            # fallback: min consecutive dense paragraphs required


# ============================================================
# Result type
# ============================================================

@dataclass
class ContentFilterResult:
    filtered_text: str
    removed_chars: int
    cut_point: int | None          # character offset into original text; None = no cut
    cut_reason: str | None         # human-readable description of why the cut was made


# ============================================================
# Public API
# ============================================================

def strip_markdown_sections(text: str) -> ContentFilterResult:
    """Remove reference and appendix sections identified by Markdown headings.

    Scans for headings (lines starting with #) whose text matches reference or
    appendix patterns. Each matched section is removed from its heading line up
    to (but not including) the next heading of equal or higher level, or EOF.

    Unlike content_filter(), this performs surgical multi-range removal rather
    than a single trailing cut, so content after the removed section is preserved.

    Args:
        text: Full document text produced by the parser.

    Returns:
        ContentFilterResult with filtered text and diagnostic fields.
        cut_point is set to the first removed section's start offset, or None if
        no sections were removed.
    """
    lines = text.splitlines(keepends=True)

    # Build heading index: list of (line_idx, level, heading_text, char_offset)
    headings: list[tuple[int, int, str, int]] = []
    char_offset = 0
    for idx, line in enumerate(lines):
        m = _MD_HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            heading_text = m.group(2).strip()
            headings.append((idx, level, heading_text, char_offset))
        char_offset += len(line)

    # Identify removal ranges for each matched heading
    removal_ranges: list[tuple[int, int]] = []
    for hi, (_, level, heading_text, start_char) in enumerate(headings):
        if not (_is_ref_heading(heading_text) or _is_appendix_heading(heading_text)):
            continue
        # Section ends at the next heading with level <= current level, or EOF
        section_end_char = len(text)
        for hj in range(hi + 1, len(headings)):
            _, next_level, _, next_start = headings[hj]
            if next_level <= level:
                section_end_char = next_start
                break
        removal_ranges.append((start_char, section_end_char))

    if not removal_ranges:
        logger.info("strip_markdown_sections: no reference/appendix headings found")
        return ContentFilterResult(
            filtered_text=text,
            removed_chars=0,
            cut_point=None,
            cut_reason=None,
        )

    # Merge overlapping or adjacent ranges
    removal_ranges.sort()
    merged: list[tuple[int, int]] = [removal_ranges[0]]
    for start, end in removal_ranges[1:]:
        if start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    # Build filtered text by splicing out each range
    parts: list[str] = []
    prev_end = 0
    total_removed = 0
    for start, end in merged:
        parts.append(text[prev_end:start])
        total_removed += end - start
        prev_end = end
    parts.append(text[prev_end:])
    filtered = "".join(parts).rstrip()

    range_descriptions = "; ".join(f"char {s}–{e}" for s, e in merged)
    cut_reason = (
        f"stripped {len(merged)} markdown section(s): {range_descriptions}"
    )
    logger.debug("strip_markdown_sections: %s", cut_reason)
    return ContentFilterResult(
        filtered_text=filtered,
        removed_chars=total_removed,
        cut_point=merged[0][0],
        cut_reason=cut_reason,
    )


def content_filter(text: str, *, use_markdown_stripper: bool = False) -> ContentFilterResult:
    """Detect and remove reference/appendix sections from parsed document text.

    Args:
        text: Full document text produced by the parser.
        use_markdown_stripper: If True, first attempt section removal via Markdown
            heading structure. Returns immediately on success; falls back to
            paragraph-density heuristics only when no Markdown sections are found.

    Returns:
        ContentFilterResult with filtered text and diagnostic fields.
    """
    if use_markdown_stripper:
        md_result = strip_markdown_sections(text)
        if md_result.cut_point is not None:
            return md_result

    paragraphs, offsets = _split_paragraphs(text)

    if not paragraphs:
        return ContentFilterResult(
            filtered_text=text,
            removed_chars=0,
            cut_point=None,
            cut_reason=None,
        )

    total_chars = len(text)
    cut_char: int | None = None
    cut_reason: str | None = None

    # --- Signal 1 + 2 + 3: heading-based detection ---
    candidates = _find_heading_candidates(paragraphs, offsets, total_chars)

    for idx, anchor_type in candidates:
        if _confirm_by_density(paragraphs, idx):
            cut_char = offsets[idx]
            cut_reason = (
                f"{anchor_type.capitalize()} heading at paragraph {idx}, "
                f"confirmed by citation density"
            )
            break

    # --- Fallback: pure density scan from rear 40% ---
    if cut_char is None:
        cut_char, cut_reason = _fallback_density_scan(paragraphs, offsets, total_chars)

    if cut_char is None:
        logger.info("content_filter: no references/appendix region detected in document")
        return ContentFilterResult(
            filtered_text=text,
            removed_chars=0,
            cut_point=None,
            cut_reason=None,
        )

    filtered = text[:cut_char].rstrip()
    removed = total_chars - cut_char
    logger.debug(
        "content_filter: cut at char %d (%s), removed %d chars",
        cut_char, cut_reason, removed,
    )
    return ContentFilterResult(
        filtered_text=filtered,
        removed_chars=removed,
        cut_point=cut_char,
        cut_reason=cut_reason,
    )


# ============================================================
# Internal helpers
# ============================================================

def _split_paragraphs(text: str) -> tuple[list[str], list[int]]:
    """Split text by double newlines; return paragraphs and their start offsets."""
    paragraphs: list[str] = []
    offsets: list[int] = []
    pos = 0
    for part in text.split("\n\n"):
        paragraphs.append(part)
        offsets.append(pos)
        pos += len(part) + 2  # +2 for the "\n\n" separator
    return paragraphs, offsets


def _paragraph_density(para: str) -> float:
    """Return fraction of citation feature categories matched in a paragraph."""
    hits = sum(1 for pat in _CITATION_FEATURES if pat.search(para))
    return hits / _TOTAL_FEATURES


def _is_ref_heading(stripped: str) -> bool:
    if len(stripped) > _REF_HEADING_MAX_LEN:
        return False
    return any(pat.match(stripped) for pat in _REF_HEADING_PATTERNS)


def _is_appendix_heading(stripped: str) -> bool:
    if len(stripped) > _APPENDIX_HEADING_MAX_LEN:
        return False
    return any(pat.match(stripped) for pat in _APPENDIX_HEADING_PATTERNS)


def _find_heading_candidates(
    paragraphs: list[str],
    offsets: list[int],
    total_chars: int,
) -> list[tuple[int, str]]:
    """Return (paragraph_index, type) pairs that pass the position prior filter."""
    candidates: list[tuple[int, str]] = []
    for i, para in enumerate(paragraphs):
        stripped = para.strip()
        if not stripped:
            continue
        relative_pos = offsets[i] / total_chars if total_chars > 0 else 0
        if relative_pos < _POSITION_PRIOR_THRESHOLD:
            continue  # too early in the document — skip
        # Strip markdown heading markers (e.g. "# References" → "References")
        heading_text = re.sub(r"^#+\s*", "", stripped)
        if _is_ref_heading(heading_text):
            candidates.append((i, "references"))
        elif _is_appendix_heading(heading_text):
            candidates.append((i, "appendix"))
    return candidates


def _confirm_by_density(paragraphs: list[str], anchor_idx: int) -> bool:
    """Check whether the paragraphs after anchor_idx confirm a citation-dense region."""
    window = paragraphs[anchor_idx + 1: anchor_idx + 1 + _DENSITY_CONFIRM_WINDOW]
    if not window:
        # No subsequent paragraphs — accept heading alone as confirmation
        return True
    dense_count = sum(1 for p in window if _paragraph_density(p) >= _DENSITY_MIN)
    return dense_count >= _DENSITY_CONFIRM_MIN


def _fallback_density_scan(
    paragraphs: list[str],
    offsets: list[int],
    total_chars: int,
) -> tuple[int | None, str | None]:
    """Scan rear 40% for a run of >= _FALLBACK_WINDOW_MIN consecutive dense paragraphs."""
    start_search = next(
        (i for i, off in enumerate(offsets) if off / total_chars >= _POSITION_PRIOR_THRESHOLD),
        len(paragraphs),
    ) if total_chars > 0 else len(paragraphs)

    run_start: int | None = None
    run_len = 0

    for i in range(start_search, len(paragraphs)):
        if _paragraph_density(paragraphs[i]) >= _DENSITY_MIN:
            if run_start is None:
                run_start = i
            run_len += 1
            if run_len >= _FALLBACK_WINDOW_MIN:
                cut_char = offsets[run_start]
                reason = (
                    f"fallback density scan: {run_len} consecutive dense paragraphs "
                    f"starting at paragraph {run_start}"
                )
                return cut_char, reason
        else:
            run_start = None
            run_len = 0

    return None, None
