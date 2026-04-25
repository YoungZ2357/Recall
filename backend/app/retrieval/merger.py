"""RRFMerger: wraps reciprocal_rank_fusion() as a BaseMerger operator."""

from app.core.pipeline_deps import PipelineDeps
from app.retrieval.configs import RRFMergerConfig
from app.retrieval.operators import BaseMerger, PipelineContext, SearchHit
from app.retrieval.searcher import reciprocal_rank_fusion


class RRFMerger(BaseMerger):
    """RRF merge operator. Wraps the reciprocal_rank_fusion() free function.

    deps is accepted for interface uniformity but is unused by RRF itself.
    """

    def __init__(self, deps: PipelineDeps, config: RRFMergerConfig | None = None) -> None:
        self.config = config or RRFMergerConfig()

    async def merge(
        self, hits_list: list[list[SearchHit]], context: PipelineContext
    ) -> list[SearchHit]:
        weights = list(self.config.weights) if self.config.weights is not None else None
        return reciprocal_rank_fusion(hits_list, k=self.config.k, weights=weights)
