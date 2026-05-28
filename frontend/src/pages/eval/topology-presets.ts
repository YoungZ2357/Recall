import type { TopologySpecJSON } from '../../api/types';

export interface RerankerWeights {
  alpha: number;
  beta: number;
  gamma: number;
}

export interface RetrieverThresholds {
  vectorThreshold: number;
  rerankerThreshold: number;
}

export type TopologyPresetId = 'vector' | 'bm25' | 'v_b_rrf' | 'custom';

export interface TopologyPresetMeta {
  id: TopologyPresetId;
  label: string;
}

export const TOPOLOGY_PRESETS: readonly TopologyPresetMeta[] = [
  { id: 'vector', label: 'Vector only' },
  { id: 'bm25', label: 'BM25 only' },
  { id: 'v_b_rrf', label: 'V + B (RRF)' },
  { id: 'custom', label: 'Custom JSON' },
] as const;

function rerankerNode(weights: RerankerWeights, rerankerThreshold: number) {
  return {
    node_id: 'rerank',
    node_type: 'Reranker',
    config: {
      alpha: weights.alpha,
      beta: weights.beta,
      gamma: weights.gamma,
      score_threshold: rerankerThreshold,
    },
  };
}

export function vectorOnly(weights: RerankerWeights, thresholds: RetrieverThresholds): TopologySpecJSON {
  return {
    name: 'vector',
    nodes: [
      { node_id: 'vec', node_type: 'VectorSearcher', config: { score_threshold: thresholds.vectorThreshold } },
      rerankerNode(weights, thresholds.rerankerThreshold),
    ],
    edges: [{ from_node: 'vec', to_node: 'rerank' }],
  };
}

export function bm25Only(weights: RerankerWeights, thresholds: RetrieverThresholds): TopologySpecJSON {
  return {
    name: 'bm25',
    nodes: [
      { node_id: 'bm25', node_type: 'BM25Searcher', config: { score_threshold: thresholds.vectorThreshold } },
      rerankerNode(weights, thresholds.rerankerThreshold),
    ],
    edges: [{ from_node: 'bm25', to_node: 'rerank' }],
  };
}

export function vectorBm25Rrf(weights: RerankerWeights, thresholds: RetrieverThresholds): TopologySpecJSON {
  return {
    name: 'v_b_rrf',
    nodes: [
      { node_id: 'vec', node_type: 'VectorSearcher', config: { score_threshold: thresholds.vectorThreshold } },
      { node_id: 'bm25', node_type: 'BM25Searcher', config: { score_threshold: thresholds.vectorThreshold } },
      { node_id: 'merge', node_type: 'RRFMerger', config: {} },
      rerankerNode(weights, thresholds.rerankerThreshold),
    ],
    edges: [
      { from_node: 'vec', to_node: 'merge' },
      { from_node: 'bm25', to_node: 'merge' },
      { from_node: 'merge', to_node: 'rerank' },
    ],
  };
}

/**
 * Patch an existing TopologySpecJSON's node configs with weights and thresholds.
 * Used for custom topologies where the user controls the structure but weights/
 * thresholds are still managed by the UI panel. Returns a new spec — input is
 * not mutated.
 */
export function applyConfig(
  spec: TopologySpecJSON,
  weights: RerankerWeights,
  thresholds: RetrieverThresholds,
): TopologySpecJSON {
  return {
    ...spec,
    nodes: spec.nodes.map((n) => {
      if (n.node_type === 'Reranker') {
        return {
          ...n,
          config: {
            ...n.config,
            alpha: weights.alpha,
            beta: weights.beta,
            gamma: weights.gamma,
            score_threshold: thresholds.rerankerThreshold,
          },
        };
      }
      if (n.node_type === 'VectorSearcher' || n.node_type === 'BM25Searcher') {
        return { ...n, config: { ...n.config, score_threshold: thresholds.vectorThreshold } };
      }
      return n;
    }),
  };
}

export function buildTopologyFromPreset(
  preset: TopologyPresetId,
  weights: RerankerWeights,
  thresholds: RetrieverThresholds,
  customSpec: TopologySpecJSON | null,
): TopologySpecJSON | null {
  switch (preset) {
    case 'vector':
      return vectorOnly(weights, thresholds);
    case 'bm25':
      return bm25Only(weights, thresholds);
    case 'v_b_rrf':
      return vectorBm25Rrf(weights, thresholds);
    case 'custom':
      return customSpec ? applyConfig(customSpec, weights, thresholds) : null;
  }
}
