export type RetentionMode = 'prefer_recent' | 'awaken_forgotten';
export type QueryMode = 'basic' | 'rag_fusion' | 'hyde';
export type ActionMode = 'search' | 'generate' | 'both';

export interface ScoreDetail {
  retrieval_score: number;
  metadata_score: number;
  retention_score: number;
}

export interface SearchResultItem {
  chunk_id: string;
  content: string;
  doc_id: string;
  filename: string;
  final_score: number;
  score_detail: ScoreDetail;
  tags: string[];
}

// Mirrors backend TopologySpecJSON / NodeSpecJSON / EdgeJSON
// (backend/app/retrieval/topology.py). Field names must match exactly —
// the backend Pydantic models reject extra/renamed keys.
export interface EdgeJSON {
  from_node: string;
  to_node: string;
}

export interface NodeSpecJSON {
  node_id: string;
  node_type: string;
  config: Record<string, unknown>;
}

export interface TopologySpecJSON {
  name?: string;
  nodes: NodeSpecJSON[];
  edges: EdgeJSON[];
}

export interface SearchRequest {
  query: string;
  top_k?: number;
  mode?: RetentionMode;
  topology?: TopologySpecJSON;
}

export interface SourceInfo {
  doc_id: string;
  filename: string;
  chunk_id: string;
}
