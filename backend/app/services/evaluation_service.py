"""Evaluation service: orchestrates test set generation, evaluation runs, and
filesystem persistence for the /api/eval endpoints.

Does not re-implement sampling / synthesis / grading / metric computation —
delegates to `app.evaluation.*`. Owns only the coordination layer + disk I/O.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.eval_schemas import (
    NAME_PATTERN,
    GenerateTestSetRequest,
    ReportSummaryResponse,
    TestSetSummaryResponse,
)
from app.core.exceptions import (
    ConfigError,
    InvalidTestSetNameError,
    ReportNotFoundError,
    TestSetAlreadyExistsError,
    TestSetNotFoundError,
)
from app.core.repository import DocumentRepository
from app.core.vectordb import QdrantService
from app.evaluation.runner import run_evaluation
from app.evaluation.sampler import sample_chunks_stratified
from app.evaluation.schemas import EvalReport, RunConfig, TestSetEntry
from app.evaluation.synthesizer import expand_with_graded_pool, generate_test_set
from app.generation.generator import LLMGenerator
from app.ingestion.embedder import BaseEmbedder
from app.retrieval.topology import TopologySpecJSON
from app.services.eval_task_store import GenerateStage

if TYPE_CHECKING:
    from app.services.search_service import SearchService

logger = logging.getLogger(__name__)


_NAME_RE = re.compile(NAME_PATTERN.pattern)


def _build_run_config(
    test_set_name: str,
    mode: Literal["prefer_recent", "awaken_forgotten"],
    topology_spec: TopologySpecJSON | None,
) -> RunConfig:
    """Derive a RunConfig snapshot from a run's inputs.

    Extracts α/β/γ from the topology spec's Reranker node config when present.
    Falls back to a name-only RunConfig (topology=None, weights=None) when no
    spec is provided — that signals "server defaults were used".
    """
    if topology_spec is None:
        return RunConfig(test_set_name=test_set_name, mode=mode)

    topology_name = topology_spec.name
    weights: dict[str, float] | None = None
    for node in topology_spec.nodes:
        # node_type is the registry key; Reranker is the only operator that
        # carries α/β/γ. Match on the canonical registry name.
        if node.node_type == "Reranker":
            cfg = node.config or {}
            extracted = {
                k: float(cfg[k])
                for k in ("alpha", "beta", "gamma")
                if k in cfg
            }
            if extracted:
                weights = extracted
            break
    return RunConfig(
        test_set_name=test_set_name,
        mode=mode,
        topology_name=topology_name,
        weights=weights,
    )


class EvaluationService:
    """Coordinates evaluation workflows and persists test sets / reports."""

    def __init__(
        self,
        embedder: BaseEmbedder,
        qdrant_client: QdrantService,
        session_factory: async_sessionmaker[AsyncSession],
        generator: LLMGenerator | None,
        search_service: SearchService,
        test_set_dir: Path,
        report_dir: Path,
    ) -> None:
        self._embedder = embedder
        self._qdrant_client = qdrant_client
        self._session_factory = session_factory
        self._generator = generator
        self._search_service = search_service
        self._test_set_dir = test_set_dir
        self._report_dir = report_dir

    # ------------------------------------------------------------------
    # Generate test set
    # ------------------------------------------------------------------

    async def generate_test_set(
        self,
        params: GenerateTestSetRequest,
        llm_model_name: str = "",
        *,
        stage_cb: Callable[[GenerateStage, int, int], None] | None = None,
    ) -> tuple[Path, int]:
        """Run the full sampling → synthesis → grading → save pipeline.

        Args:
            params: Validated request body.
            llm_model_name: Identifier to record in entry metadata.
            stage_cb: Optional callback ``(stage, current, total)`` invoked at
                stage transitions and per-item progress within long stages.

        Returns:
            Tuple of (saved test set path, entry count).
        """
        if self._generator is None:
            raise ConfigError(message="LLM_API_KEY is not configured")

        # Reject collisions early so the caller can surface a 409 before the
        # background task spawns.
        path = self._resolve_test_set_path(params.name, must_exist=False)
        if path.exists():
            raise TestSetAlreadyExistsError(name=params.name)

        # ---- Stage 1: sampling ----
        if stage_cb is not None:
            stage_cb("sampling", 0, 0)

        include_ids: list[str] | None = params.include_doc_ids
        exclude_ids: list[str] | None = params.exclude_doc_ids
        if params.auto_split > 0.0:
            include_ids = await self._resolve_auto_split(params.name, params.auto_split)

        async with self._session_factory() as session:
            sampled = await sample_chunks_stratified(
                session,
                total_n=params.num_chunks,
                min_content_length=params.min_length,
                include_doc_ids=include_ids if include_ids else None,
                exclude_doc_ids=exclude_ids if exclude_ids else None,
            )

        if not sampled:
            raise ConfigError(
                message="No eligible chunks found for sampling",
                detail=(
                    f"num_chunks={params.num_chunks}, "
                    f"min_length={params.min_length}"
                ),
            )

        if stage_cb is not None:
            stage_cb("sampling", len(sampled), len(sampled))

        # ---- Stage 2: synthesizing ----
        synth_cb: Callable[[int, int], None] | None = None
        if stage_cb is not None:
            stage_cb("synthesizing", 0, len(sampled))

            def synth_cb(done: int, total: int) -> None:
                stage_cb("synthesizing", done, total)

        entries = await generate_test_set(
            self._generator,
            sampled,
            num_queries_per_chunk=params.queries_per_chunk,
            concurrency=params.concurrency,
            model_name=llm_model_name,
            with_context=params.with_context,
            progress_callback=synth_cb,
        )

        # ---- Stage 3: grading ----
        if entries and not params.skip_grading:
            grade_cb: Callable[[int, int], None] | None = None
            if stage_cb is not None:
                stage_cb("grading", 0, len(entries))

                def grade_cb(done: int, total: int) -> None:
                    stage_cb("grading", done, total)

            await expand_with_graded_pool(
                entries,
                embedder=self._embedder,
                qdrant_client=self._qdrant_client,
                session_factory=self._session_factory,
                generator=self._generator,
                pool_size=params.pool_size,
                concurrency=params.concurrency,
                grader_model=llm_model_name,
                progress_callback=grade_cb,
            )

        # ---- Stage 4: writing ----
        if stage_cb is not None:
            stage_cb("writing", 0, 1)

        await self._write_test_set(path, entries)

        if stage_cb is not None:
            stage_cb("writing", 1, 1)

        logger.info(
            "Generated test set %r with %d entries at %s",
            params.name, len(entries), path,
        )
        return path, len(entries)

    async def _resolve_auto_split(self, base_name: str, ratio: float) -> list[str]:
        """Pick a random subset of document ids for sampling; persist a sibling manifest."""
        import random

        async with self._session_factory() as session:
            all_docs = await DocumentRepository.list_all(session)

        all_doc_ids = [str(d.document_id) for d in all_docs]
        random.shuffle(all_doc_ids)
        split_at = max(1, round(len(all_doc_ids) * ratio))
        included = all_doc_ids[:split_at]
        excluded = all_doc_ids[split_at:]

        manifest_path = self._test_set_dir / f"{base_name}_split.json"
        manifest = {
            "split_ratio": ratio,
            "included_doc_ids": included,
            "excluded_doc_ids": excluded,
        }
        content = json.dumps(manifest, ensure_ascii=False, indent=2)
        await asyncio.to_thread(manifest_path.write_text, content, encoding="utf-8")
        return included

    async def _write_test_set(self, path: Path, entries: list[TestSetEntry]) -> None:
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        payload = json.dumps(
            [e.model_dump() for e in entries], ensure_ascii=False, indent=2,
        )
        await asyncio.to_thread(path.write_text, payload, encoding="utf-8")

    # ------------------------------------------------------------------
    # Upload test set
    # ------------------------------------------------------------------

    async def upload_test_set(
        self,
        file_bytes: bytes,
        name: str,
        *,
        overwrite: bool = False,
    ) -> TestSetSummaryResponse:
        """Persist an uploaded test set file under ``test_set_dir/{name}.json``.

        Validates the payload by parsing every entry through ``TestSetEntry``
        so a subsequent run won't crash on malformed data.

        Raises:
            InvalidTestSetNameError: name fails NAME_PATTERN.
            TestSetAlreadyExistsError: file exists and ``overwrite`` is False.
            ConfigError: payload is not a JSON list of TestSetEntry-compatible
                objects.
        """
        # Name validation + traversal guard (must_exist=False since we create).
        path = self._resolve_test_set_path(name, must_exist=False)
        if path.exists() and not overwrite:
            raise TestSetAlreadyExistsError(name=name)

        # Strict validation: decode + parse every entry so bad payloads
        # fail at upload time instead of mid-run.
        try:
            text = file_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ConfigError(
                message="Uploaded test set is not valid UTF-8",
                detail=str(exc),
            ) from exc
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigError(
                message="Uploaded test set is not valid JSON",
                detail=str(exc),
            ) from exc
        if not isinstance(raw, list):
            raise ConfigError(
                message="Uploaded test set must be a JSON list of entries",
            )
        try:
            entries = [TestSetEntry.model_validate(item) for item in raw]
        except (ValueError, TypeError) as exc:
            raise ConfigError(
                message="Uploaded test set has invalid entries",
                detail=str(exc),
            ) from exc

        await self._write_test_set(path, entries)
        logger.info("Uploaded test set %r with %d entries to %s", name, len(entries), path)
        return self.load_test_set_summary(name)

    # ------------------------------------------------------------------
    # Run evaluation
    # ------------------------------------------------------------------

    async def run_evaluation(
        self,
        test_set_name: str,
        top_k: int,
        mode: Literal["prefer_recent", "awaken_forgotten"],
        *,
        report_name: str | None = None,
        persist_report: bool = True,
        progress_cb: Callable[[int, int], None] | None = None,
        topology_spec: TopologySpecJSON | None = None,
    ) -> tuple[EvalReport, Path | None]:
        """Load a test set, run retrieval evaluation, optionally persist report.

        When ``topology_spec`` is given, opens a DB session so the search
        service can resolve/build a per-run pipeline; otherwise the search
        service's default pipeline is used.

        Returns ``(report, persisted_path_or_None)``.
        """
        entries = self.load_test_set(test_set_name)
        run_config = _build_run_config(test_set_name, mode, topology_spec)

        if topology_spec is not None:
            async with self._session_factory() as session:
                report = await run_evaluation(
                    self._search_service,
                    entries,
                    top_k=top_k,
                    retention_mode=mode,
                    query_callback=progress_cb,
                    topology_spec=topology_spec,
                    topology_session=session,
                )
        else:
            report = await run_evaluation(
                self._search_service,
                entries,
                top_k=top_k,
                retention_mode=mode,
                query_callback=progress_cb,
            )
        report.run_config = run_config

        saved_path: Path | None = None
        if persist_report:
            name = report_name or test_set_name
            saved_path = self._resolve_report_path(name, must_exist=False)
            await asyncio.to_thread(saved_path.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(
                saved_path.write_text,
                report.model_dump_json(indent=2),
                encoding="utf-8",
            )
            logger.info("Persisted eval report to %s", saved_path)

        return report, saved_path

    # ------------------------------------------------------------------
    # Test set CRUD
    # ------------------------------------------------------------------

    def list_test_sets(self) -> list[TestSetSummaryResponse]:
        if not self._test_set_dir.exists():
            return []
        out: list[TestSetSummaryResponse] = []
        for p in sorted(self._test_set_dir.glob("*.json")):
            # Skip split manifests
            if p.stem.endswith("_split"):
                continue
            try:
                entries = json.loads(p.read_text(encoding="utf-8"))
                count = len(entries) if isinstance(entries, list) else 0
            except (OSError, json.JSONDecodeError):
                logger.warning("Skipping unreadable test set: %s", p)
                continue
            stat = p.stat()
            out.append(TestSetSummaryResponse(
                name=p.stem,
                entry_count=count,
                created_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
                size_bytes=stat.st_size,
            ))
        return out

    def load_test_set(
        self, name: str, preview: int | None = None,
    ) -> list[TestSetEntry]:
        path = self._resolve_test_set_path(name, must_exist=True)
        raw = json.loads(path.read_text(encoding="utf-8"))
        entries = [TestSetEntry.model_validate(item) for item in raw]
        if preview is not None and preview >= 0:
            entries = entries[:preview]
        return entries

    def load_test_set_summary(self, name: str) -> TestSetSummaryResponse:
        path = self._resolve_test_set_path(name, must_exist=True)
        raw = json.loads(path.read_text(encoding="utf-8"))
        count = len(raw) if isinstance(raw, list) else 0
        stat = path.stat()
        return TestSetSummaryResponse(
            name=name,
            entry_count=count,
            created_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
            size_bytes=stat.st_size,
        )

    def delete_test_set(self, name: str) -> None:
        path = self._resolve_test_set_path(name, must_exist=True)
        path.unlink()
        # Best-effort delete the sibling split manifest if it exists
        manifest = self._test_set_dir / f"{name}_split.json"
        if manifest.exists():
            manifest.unlink()

    # ------------------------------------------------------------------
    # Report CRUD
    # ------------------------------------------------------------------

    def list_reports(self) -> list[ReportSummaryResponse]:
        if not self._report_dir.exists():
            return []
        out: list[ReportSummaryResponse] = []
        for p in sorted(self._report_dir.glob("*.json")):
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                report = EvalReport.model_validate(raw)
            except (OSError, json.JSONDecodeError, ValueError):
                logger.warning("Skipping unreadable eval report: %s", p)
                continue
            stat = p.stat()
            rc = report.run_config
            out.append(ReportSummaryResponse(
                name=p.stem,
                created_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
                num_queries=report.num_queries,
                top_k=report.top_k,
                aggregate_metrics=report.aggregate_metrics,
                test_set_name=rc.test_set_name if rc else None,
                topology_name=rc.topology_name if rc else None,
                weights=rc.weights if rc else None,
                mode=rc.mode if rc else None,
            ))
        return out

    def load_report(self, name: str) -> EvalReport:
        path = self._resolve_report_path(name, must_exist=True)
        raw = json.loads(path.read_text(encoding="utf-8"))
        return EvalReport.model_validate(raw)

    def delete_report(self, name: str) -> None:
        path = self._resolve_report_path(name, must_exist=True)
        path.unlink()

    # ------------------------------------------------------------------
    # Path helpers (defense-in-depth name validation + traversal guard)
    # ------------------------------------------------------------------

    def _resolve_test_set_path(self, name: str, *, must_exist: bool) -> Path:
        return self._resolve_path(
            self._test_set_dir, name, must_exist=must_exist,
            not_found_exc=TestSetNotFoundError,
        )

    def _resolve_report_path(self, name: str, *, must_exist: bool) -> Path:
        return self._resolve_path(
            self._report_dir, name, must_exist=must_exist,
            not_found_exc=ReportNotFoundError,
        )

    def _resolve_path(
        self,
        base: Path,
        name: str,
        *,
        must_exist: bool,
        not_found_exc: type[Exception],
    ) -> Path:
        if not _NAME_RE.match(name):
            raise InvalidTestSetNameError(name=name)
        candidate = (base / f"{name}.json").resolve()
        # Traversal guard: ensure resolved path stays within base
        try:
            candidate.relative_to(base.resolve())
        except ValueError as exc:
            raise InvalidTestSetNameError(name=name) from exc
        if must_exist and not candidate.exists():
            raise not_found_exc(name=name)
        return candidate
