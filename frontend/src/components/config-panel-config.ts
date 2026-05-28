export interface SearchConfig {
  topo: 'vector_only' | 'bm25_only' | 'rrf' | 'custom';
  customJson: string;
  rewrite: 'passthrough' | 'HyDE' | 'RAG-Fusion';
  topK: number;
  vectorThreshold: number;
  rerankerThreshold: number;
  alpha: number;
  beta: number;
  gamma: number;
  retention: 'prefer_recent' | 'awaken_forgotten';
}

export const DEFAULT_CONFIG: SearchConfig = {
  topo: 'rrf',
  customJson: '',
  rewrite: 'passthrough',
  topK: 10,
  vectorThreshold: 0.2,
  rerankerThreshold: 0.6,
  alpha: 0.85,
  beta: 0.15,
  gamma: 0.0,
  retention: 'prefer_recent',
};
