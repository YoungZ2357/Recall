export type RetentionMode = 'prefer_recent' | 'awaken_forgotten';
export type QueryMode = 'basic' | 'rag_fusion' | 'hyde';

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

export interface SearchRequest {
  query: string;
  top_k?: number;
  mode?: RetentionMode;
}
