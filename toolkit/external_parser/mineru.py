"""
MinerU Precision API parser for PDF files.

Uploads a local PDF to MinerU cloud, waits for parsing to complete,
then writes both the Markdown and JSON outputs to a specified directory.

Usage:
    python toolkit/external_parser/mineru.py <input.pdf> <output_dir> [options]

Examples:
    python toolkit/external_parser/mineru.py paper.pdf ./output
    python toolkit/external_parser/mineru.py paper.pdf ./output --model vlm --language en -v

Environment variables (loaded from .env if present):
    MINERU_API_KEY          Required. Bearer token for MinerU Precision API.
    MINERU_MODEL_VERSION    pipeline | vlm  (default: pipeline)
    MINERU_POLL_INTERVAL    Seconds between status polls (default: 3)
    MINERU_POLL_MAX_RETRIES Max poll attempts before timeout (default: 60)

Flow: get_upload_url → upload_file → poll_batch (parsing starts automatically on upload).
No separate task submission step is needed per the Precision API spec.
"""
from __future__ import annotations

import io
import logging
import os
import time
import zipfile
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ============================================================
# Constants
# ============================================================

_BASE_URL = "https://mineru.net/api/v4"
_DEFAULT_POLL_INTERVAL = 3
_DEFAULT_POLL_MAX_RETRIES = 60
_DEFAULT_MODEL_VERSION = "pipeline"


# ============================================================
# Exceptions
# ============================================================

class MinerUError(RuntimeError):
    """Raised on any MinerU API or processing failure."""


# ============================================================
# API Client
# ============================================================

class MinerUClient:
    """Synchronous client for MinerU Precision API (v4)."""

    def __init__(self, api_key: str) -> None:
        self._client = httpx.Client(
            base_url=_BASE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60.0,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> MinerUClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ----------------------------------------------------------
    # Step 1: Presigned upload URL
    # ----------------------------------------------------------

    def get_upload_url(self, filename: str, model_version: str) -> tuple[str, str]:
        """Request a presigned upload slot for a single file.

        Calls POST /file-urls/batch with one file entry.
        Parsing starts automatically once the file is uploaded to the presigned URL.

        Args:
            filename: The original filename (used by the server for naming).
            model_version: MinerU parsing backend — "pipeline" or "vlm".

        Returns:
            (batch_id, upload_url) where:
              - batch_id   — used to poll for results
              - upload_url — presigned PUT URL for uploading raw bytes

        Raises:
            MinerUError: API error or unexpected response structure.
        """
        resp = self._client.post(
            "/file-urls/batch",
            json={"files": [{"name": filename}], "model_version": model_version},
        )
        self._raise_for_api_error(resp, "get_upload_url")

        data = resp.json().get("data", {})
        if not data:
            raise MinerUError(
                "get_upload_url: empty 'data' in response. "
                f"Full response: {resp.text[:400]}"
            )

        batch_id = data.get("batch_id")
        if not batch_id:
            raise MinerUError(
                f"get_upload_url: 'batch_id' not found in response data.\n"
                f"Actual keys: {list(data.keys())}\n"
                f"Full response: {resp.text[:400]}"
            )

        file_urls = data.get("file_urls", [])
        if not file_urls:
            raise MinerUError(
                f"get_upload_url: 'file_urls' not found or empty in response data.\n"
                f"Actual keys: {list(data.keys())}\n"
                f"Full response: {resp.text[:400]}"
            )

        return batch_id, file_urls[0]

    # ----------------------------------------------------------
    # Step 2: Upload file to presigned URL
    # ----------------------------------------------------------

    def upload_file(self, upload_url: str, file_path: Path) -> None:
        """PUT raw file bytes to the presigned upload URL.

        Uses a plain client without the Precision API auth headers,
        as presigned URLs typically do not accept additional auth headers.

        Args:
            upload_url: Presigned PUT URL from get_upload_url.
            file_path: Local path of the file to upload.

        Raises:
            MinerUError: Upload returned non-2xx status.
        """
        file_bytes = file_path.read_bytes()
        with httpx.Client(timeout=120.0) as plain:
            resp = plain.put(
                upload_url,
                content=file_bytes,
            )
        if resp.status_code not in (200, 204):
            raise MinerUError(
                f"File upload failed (HTTP {resp.status_code}): {resp.text[:300]}"
            )

    # ----------------------------------------------------------
    # Step 3: Poll for completion
    # ----------------------------------------------------------

    def poll_batch(
        self,
        batch_id: str,
        poll_interval: int,
        max_retries: int,
    ) -> str:
        """Poll GET /extract-results/batch/{batch_id} until state == 'done'.

        Parsing starts automatically after the file is uploaded to the presigned URL,
        so no separate task submission step is needed.

        Args:
            batch_id: ID returned by get_upload_url.
            poll_interval: Seconds to wait between each poll.
            max_retries: Maximum number of poll attempts.

        Returns:
            full_zip_url — CDN link to the result zip.

        Raises:
            MinerUError: Task failed or timed out.
        """
        for attempt in range(1, max_retries + 1):
            time.sleep(poll_interval)
            resp = self._client.get(f"/extract-results/batch/{batch_id}")
            self._raise_for_api_error(resp, "poll_batch")

            data = resp.json().get("data", {})
            results = data.get("extract_result", [])
            if not results:
                logger.debug("Poll %d/%d — extract_result empty, waiting...", attempt, max_retries)
                continue

            result = results[0]
            state = result.get("state", "")
            logger.debug("Poll %d/%d — state: %s", attempt, max_retries, state)

            if state == "done":
                zip_url = result.get("full_zip_url")
                if not zip_url:
                    raise MinerUError(
                        "poll_batch: state is 'done' but 'full_zip_url' is missing. "
                        f"Result entry: {result}"
                    )
                return zip_url

            if state in ("failed", "error"):
                err = result.get("err_msg", "")
                raise MinerUError(
                    f"MinerU task failed: batch_id={batch_id}, state={state}"
                    + (f", err_msg={err}" if err else "")
                )

        raise MinerUError(
            f"MinerU task timed out after {max_retries * poll_interval}s "
            f"(batch_id={batch_id}). Increase --poll-retries or --poll-interval."
        )

    # ----------------------------------------------------------
    # Internal helpers
    # ----------------------------------------------------------

    @staticmethod
    def _raise_for_api_error(resp: httpx.Response, context: str) -> None:
        """Raise MinerUError on HTTP error or non-zero API code."""
        if resp.status_code != 200:
            raise MinerUError(
                f"[{context}] HTTP {resp.status_code}: {resp.text[:300]}"
            )
        body = resp.json()
        code = body.get("code", 0)
        if code != 0:
            raise MinerUError(
                f"[{context}] API error code={code}: {body.get('msg', '(no message)')}"
            )


# ============================================================
# Result extraction
# ============================================================

def _download_zip(zip_url: str) -> bytes:
    """Download the result zip from CDN (public URL, no auth required)."""
    resp = httpx.get(zip_url, timeout=120.0, follow_redirects=True)
    if resp.status_code != 200:
        raise MinerUError(
            f"Failed to download result zip (HTTP {resp.status_code}): "
            f"{resp.text[:200]}"
        )
    return resp.content


def _extract_outputs(zip_bytes: bytes) -> tuple[str, str | None]:
    """Extract Markdown and JSON content strings from the result zip.

    Returns:
        (markdown_text, json_text) where json_text is None if no .json is present.

    Raises:
        MinerUError: No .md file found in the zip.
    """
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        logger.debug("Zip contents: %s", names)

        md_files = [n for n in names if n.endswith(".md")]
        json_files = [n for n in names if n.endswith(".json")]

        if not md_files:
            raise MinerUError(
                f"No .md file found in result zip. Contents: {names}"
            )

        markdown = zf.read(md_files[0]).decode("utf-8")

        json_text: str | None = None
        if json_files:
            json_text = zf.read(json_files[0]).decode("utf-8")
        else:
            logger.warning(
                "No .json file found in result zip. "
                "Only Markdown output will be written."
            )

    return markdown, json_text


# ============================================================
# Public entry point
# ============================================================

def parse_pdf(
    file_path: Path,
    output_dir: Path,
    *,
    model_version: str = _DEFAULT_MODEL_VERSION,
    language: str = "ch",
    enable_formula: bool = True,
    enable_table: bool = True,
    poll_interval: int = _DEFAULT_POLL_INTERVAL,
    poll_max_retries: int = _DEFAULT_POLL_MAX_RETRIES,
    api_key: str | None = None,
) -> tuple[Path, Path | None]:
    """Parse a PDF via MinerU Precision API and write results to output_dir.

    Orchestrates the full flow: upload → poll → download → extract → write.

    Args:
        file_path: Path to the input PDF file.
        output_dir: Directory to write output files into. Created if absent.
        model_version: MinerU parsing backend — "pipeline" (fast) or "vlm" (accurate).
        language: Primary language of the document (e.g. "ch", "en").
        enable_formula: Extract formulas as LaTeX. Requires model support.
        enable_table: Extract tables as HTML. Requires model support.
        poll_interval: Seconds between task status polls.
        poll_max_retries: Max poll attempts before raising a timeout error.
        api_key: MinerU API key. Falls back to MINERU_API_KEY env var.

    Returns:
        (md_path, json_path) — absolute paths of written files.
        json_path is None if the API did not produce a JSON output.

    Raises:
        FileNotFoundError: input file does not exist.
        EnvironmentError: MINERU_API_KEY is not set.
        MinerUError: any API or processing failure.
    """
    if not file_path.is_file():
        raise FileNotFoundError(f"Input file not found: {file_path}")

    resolved_key = api_key or os.environ.get("MINERU_API_KEY", "")
    if not resolved_key:
        raise EnvironmentError(
            "MINERU_API_KEY is not set. "
            "Add it to your .env file or export it as an environment variable."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = file_path.stem

    with MinerUClient(resolved_key) as client:
        logger.info("Step 1/3 — Requesting presigned upload URL (model=%s)...", model_version)
        batch_id, upload_url = client.get_upload_url(file_path.name, model_version)
        logger.info("Batch ID: %s", batch_id)

        size_mb = file_path.stat().st_size / 1_048_576
        logger.info("Step 2/3 — Uploading %s (%.2f MB)...", file_path.name, size_mb)
        client.upload_file(upload_url, file_path)

        logger.info(
            "Step 3/3 — Polling for result (interval=%ds, max=%d attempts)...",
            poll_interval, poll_max_retries,
        )
        zip_url = client.poll_batch(batch_id, poll_interval, poll_max_retries)

    logger.info("Downloading result zip...")
    zip_bytes = _download_zip(zip_url)

    markdown, json_text = _extract_outputs(zip_bytes)

    md_path = output_dir / f"{stem}.md"
    md_path.write_text(markdown, encoding="utf-8")
    logger.info("Wrote Markdown → %s", md_path)

    json_path: Path | None = None
    if json_text is not None:
        json_path = output_dir / f"{stem}.json"
        json_path.write_text(json_text, encoding="utf-8")
        logger.info("Wrote JSON     → %s", json_path)

    return md_path, json_path
