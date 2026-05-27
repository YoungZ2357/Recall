import type { SearchConfig } from '../components/config-panel-config';
import type { NodeSpecJSON, TopologySpecJSON } from './types';

// Compiles UI SearchConfig into the wire-level TopologySpecJSON consumed by
// the backend `/api/search` and `/generate` endpoints. Field names mirror
// backend/app/retrieval/topology.py and backend/app/retrieval/configs.py.
//
// Throws on a `custom` topo whose JSON cannot be parsed; structural errors
// (missing nodes/edges, wrong field names) are surfaced by the backend's
// Pydantic validator as 400 responses.

function rerankerConfig(config: SearchConfig): Record<string, unknown> {
  return {
    alpha: config.alpha,
    beta: config.beta,
    gamma: config.gamma,
    retention_mode: config.retention,
  };
}

function vectorOnly(config: SearchConfig): TopologySpecJSON {
  const nodes: NodeSpecJSON[] = [
    { node_id: 'vec',    node_type: 'VectorSearcher', config: {} },
    { node_id: 'rerank', node_type: 'Reranker',       config: rerankerConfig(config) },
  ];
  return {
    nodes,
    edges: [{ from_node: 'vec', to_node: 'rerank' }],
  };
}

function bm25Only(config: SearchConfig): TopologySpecJSON {
  const nodes: NodeSpecJSON[] = [
    { node_id: 'bm25',   node_type: 'BM25Searcher', config: {} },
    { node_id: 'rerank', node_type: 'Reranker',     config: rerankerConfig(config) },
  ];
  return {
    nodes,
    edges: [{ from_node: 'bm25', to_node: 'rerank' }],
  };
}

function rrfHybrid(config: SearchConfig): TopologySpecJSON {
  const nodes: NodeSpecJSON[] = [
    { node_id: 'vec',    node_type: 'VectorSearcher', config: {} },
    { node_id: 'bm25',   node_type: 'BM25Searcher',   config: {} },
    { node_id: 'merge',  node_type: 'RRFMerger',      config: {} },
    { node_id: 'rerank', node_type: 'Reranker',       config: rerankerConfig(config) },
  ];
  return {
    nodes,
    edges: [
      { from_node: 'vec',   to_node: 'merge' },
      { from_node: 'bm25',  to_node: 'merge' },
      { from_node: 'merge', to_node: 'rerank' },
    ],
  };
}

function fromCustomJson(json: string): TopologySpecJSON {
  let parsed: unknown;
  try {
    parsed = JSON.parse(json);
  } catch {
    throw new Error('Invalid custom topology JSON');
  }
  if (!parsed || typeof parsed !== 'object') {
    throw new Error('Invalid custom topology JSON');
  }
  return parsed as TopologySpecJSON;
}

export function buildTopology(config: SearchConfig): TopologySpecJSON {
  switch (config.topo) {
    case 'vector_only': return vectorOnly(config);
    case 'bm25_only':   return bm25Only(config);
    case 'rrf':         return rrfHybrid(config);
    case 'custom':      return fromCustomJson(config.customJson);
  }
}
