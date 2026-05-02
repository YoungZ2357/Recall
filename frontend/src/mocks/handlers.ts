import { http, HttpResponse, delay } from 'msw';
import type { SearchResultItem } from '../api/types';

const MOCK_RESULTS: SearchResultItem[] = [
  {
    chunk_id: 'chunk-001',
    doc_id: 'doc-001',
    filename: 'direct-preference-optimization.pdf',
    content:
      'DPO directly optimizes a language model for preference alignment without requiring a separate reward model. The key insight is that the optimal policy under RLHF can be expressed in closed form, allowing direct optimization via a binary cross-entropy objective over preference pairs.',
    final_score: 0.828,
    score_detail: { retrieval_score: 0.91, metadata_score: 0.73, retention_score: 0.68 },
    tags: ['alignment', 'RLHF'],
  },
  {
    chunk_id: 'chunk-002',
    doc_id: 'doc-002',
    filename: 'rlhf-from-human-feedback.pdf',
    content:
      'RLHF uses a reward model trained from human preference data to guide policy optimization via PPO. The preference pairs are collected by asking human raters to compare two model outputs and select the preferred one.',
    final_score: 0.694,
    score_detail: { retrieval_score: 0.76, metadata_score: 0.65, retention_score: 0.55 },
    tags: ['RLHF', 'PPO', 'reward-model'],
  },
  {
    chunk_id: 'chunk-003',
    doc_id: 'doc-003',
    filename: 'rq-rag-dataset-paper.pdf',
    content:
      'RQ-RAG constructs training data for query rewriting by decomposing complex queries into sub-queries, generating synthetic preference data for retrieval optimization.',
    final_score: 0.676,
    score_detail: { retrieval_score: 0.72, metadata_score: 0.62, retention_score: 0.61 },
    tags: ['RAG', 'query-rewriting'],
  },
];

export const handlers = [
  http.post('/api/search', async () => {
    await delay(400);
    return HttpResponse.json(MOCK_RESULTS);
  }),
];
