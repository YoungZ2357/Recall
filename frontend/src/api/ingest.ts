import type { IngestConfig, IngestTask, FileTaskStatus, StageProgress, UploadFile } from '../types/ingest';

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Request failed ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

interface TempFileInfo {
  file_id: string;
  filename: string;
  size: number;
  file_hash: string;
}

interface TempUploadResponse {
  files: TempFileInfo[];
}

interface IngestResponse {
  task_id: string;
}

interface StageProgressResponse {
  stage: string;
  status: string;
  detail: string;
  current: number;
  total: number;
}

interface FileTaskProgressResponse {
  file_id: string;
  filename: string;
  status: string;
  stages: StageProgressResponse[];
  error: string | null;
  chunk_count: number;
  tags: string[];
}

interface TaskStatusResponse {
  task_id: string;
  status: string;
  files: FileTaskProgressResponse[];
  started_at: string | null;
  completed_at: string | null;
}

export async function startIngestion(
  files: UploadFile[],
  config: IngestConfig,
): Promise<string> {
  // Step 1: upload files to temp storage
  const form = new FormData();
  for (const f of files) {
    form.append('files', f.file);
  }
  const uploadRes = await fetch('/api/upload', { method: 'POST', body: form });
  const uploaded = await handleResponse<TempUploadResponse>(uploadRes);
  const fileIds = uploaded.files.map(f => f.file_id);

  // Step 2: start ingest task
  const body = {
    file_ids: fileIds,
    pdf_parser: config.pdfParser,
    strip_tail: config.stripTail,
    strip_markdown: config.stripMarkdown,
    chunk_strategy: config.chunkStrategy,
    chunk_size: config.chunkSize,
    chunk_overlap: config.chunkOverlap,
    target_chunks: config.targetChunks,
    overlap_ratio: config.overlapRatio,
    contextualize: config.contextualize,
    context_concurrency: config.contextConcurrency,
    auto_tag: config.autoTag,
  };
  const ingestRes = await fetch('/api/ingest', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const { task_id } = await handleResponse<IngestResponse>(ingestRes);
  return task_id;
}

export async function pollTaskStatus(
  taskId: string,
  _files: UploadFile[],
): Promise<IngestTask> {
  const res = await fetch(`/api/ingest/${taskId}`);
  const data = await handleResponse<TaskStatusResponse>(res);

  const files: FileTaskStatus[] = data.files.map(f => {
    const stages: StageProgress[] = f.stages.map(s => ({
      stage: s.stage,
      status: s.status as StageProgress['status'],
      detail: s.detail || undefined,
      current: s.current || undefined,
      total: s.total || undefined,
    }));

    const result: FileTaskStatus = {
      fileId: f.file_id,
      fileName: f.filename,
      status: f.status as FileTaskStatus['status'],
      stages,
    };

    if (f.error) result.error = f.error;
    if (f.chunk_count) result.chunkCount = f.chunk_count;
    if (f.tags?.length) result.tags = f.tags;

    return result;
  });

  const taskStatus = data.status === 'pending' ? 'running' : data.status as IngestTask['status'];

  return {
    taskId: data.task_id,
    status: taskStatus,
    files,
    startedAt: data.started_at ?? new Date().toISOString(),
    completedAt: data.completed_at ?? undefined,
  };
}
