export interface IngestConfig {
  pdfParser: 'pymupdf' | 'marker' | 'mineru';
  stripTail: boolean;
  stripMarkdown: boolean;
  chunkStrategy: 'recursive' | 'fixed_count';
  chunkSize: number;
  chunkOverlap: number;
  targetChunks: number;
  overlapRatio: number;
  contextualize: boolean;
  contextConcurrency: number;
  autoTag: boolean;
}

export interface UploadFile {
  id: string;
  file: File;
  name: string;
  size: number;
  type: 'pdf' | 'txt' | 'md';
}

export type StageStatus = 'waiting' | 'running' | 'done' | 'error' | 'skipped';

export interface StageProgress {
  stage: string;
  status: StageStatus;
  detail?: string;
  current?: number;
  total?: number;
}

export interface FileTaskStatus {
  fileId: string;
  fileName: string;
  status: 'waiting' | 'running' | 'done' | 'error';
  stages: StageProgress[];
  error?: string;
  tags?: string[];
  chunkCount?: number;
}

export interface IngestTask {
  taskId: string;
  status: 'running' | 'done' | 'error';
  files: FileTaskStatus[];
  startedAt: string;
  completedAt?: string;
}
