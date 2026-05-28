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

// ---------------------------------------------------------------------------
// Evaluation API types — mirrors backend/app/core/eval_schemas.py and
// backend/app/evaluation/schemas.py
// ---------------------------------------------------------------------------

export type EvalRetentionMode = 'prefer_recent' | 'awaken_forgotten';
export type GenerateStage = 'sampling' | 'synthesizing' | 'grading' | 'writing';
export type EvalTaskKind = 'generate' | 'run';
export type EvalTaskStatus = 'pending' | 'running' | 'done' | 'error';

export interface RunConfig {
  test_set_name: string;
  mode: EvalRetentionMode;
  topology_name: string | null;
  weights: Record<string, number> | null;
}

export interface QueryMetadata {
  query_type: string;
  generator_model: string;
  grader_model: string | null;
}

export interface TestSetEntry {
  query_id: string;
  query: string;
  relevance: Record<string, number>;
  source_document_id: string;
  source_chunk_id: string;
  metadata: QueryMetadata;
}

export interface EvalResult {
  query_id: string;
  query: string;
  retrieved_chunk_ids: string[];
  metrics: Record<string, number>;
}

export interface EvalReport {
  num_queries: number;
  top_k: number;
  aggregate_metrics: Record<string, number>;
  per_query: EvalResult[];
  run_config: RunConfig | null;
}

export interface TestSetSummary {
  name: string;
  entry_count: number;
  created_at: string;
  size_bytes: number;
}

export interface TestSetPreview extends TestSetSummary {
  entries: TestSetEntry[];
}

export interface ReportSummary {
  name: string;
  created_at: string;
  num_queries: number;
  top_k: number;
  aggregate_metrics: Record<string, number>;
  test_set_name: string | null;
  topology_name: string | null;
  weights: Record<string, number> | null;
  mode: string | null;
}

export interface GenerateTestSetRequest {
  name: string;
  num_chunks?: number;
  queries_per_chunk?: number;
  min_length?: number;
  concurrency?: number;
  with_context?: boolean;
  pool_size?: number;
  skip_grading?: boolean;
  include_doc_ids?: string[];
  exclude_doc_ids?: string[];
  auto_split?: number;
}

export interface RunEvalRequest {
  test_set_name: string;
  top_k?: number;
  mode?: EvalRetentionMode;
  report_name?: string;
  persist_report?: boolean;
  topology?: TopologySpecJSON;
}

export interface EvalTaskIdResponse {
  task_id: string;
}

export interface GenerateProgress {
  stage: GenerateStage;
  current: number;
  total: number;
}

export interface RunProgress {
  current_query: number;
  total_queries: number;
}

export interface EvalTaskStatusResponse {
  task_id: string;
  kind: EvalTaskKind;
  name: string;
  status: EvalTaskStatus;
  progress: GenerateProgress | RunProgress;
  summary: Record<string, unknown> | null;
  result_path: string | null;
  error: string | null;
  started_at: string | null;
  completed_at: string | null;
}
