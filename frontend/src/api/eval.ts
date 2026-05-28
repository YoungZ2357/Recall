import type {
  EvalReport,
  EvalTaskIdResponse,
  EvalTaskStatusResponse,
  GenerateTestSetRequest,
  ReportSummary,
  RunEvalRequest,
  TestSetPreview,
  TestSetSummary,
} from './types';

export class HttpError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = 'HttpError';
  }
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new HttpError(res.status, `Request failed ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

async function handleNoContent(res: Response): Promise<void> {
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new HttpError(res.status, `Request failed ${res.status}: ${text}`);
  }
}

// ---------- Test sets ----------

export async function listTestSets(): Promise<TestSetSummary[]> {
  const res = await fetch('/api/eval/test-sets');
  return handleResponse<TestSetSummary[]>(res);
}

export async function getTestSet(name: string, preview = 5): Promise<TestSetPreview> {
  const res = await fetch(`/api/eval/test-sets/${encodeURIComponent(name)}?preview=${preview}`);
  return handleResponse<TestSetPreview>(res);
}

export async function deleteTestSet(name: string): Promise<void> {
  const res = await fetch(`/api/eval/test-sets/${encodeURIComponent(name)}`, { method: 'DELETE' });
  return handleNoContent(res);
}

export async function uploadTestSet(
  file: File,
  options: { name?: string; overwrite?: boolean } = {},
): Promise<TestSetSummary> {
  const form = new FormData();
  form.append('file', file);
  if (options.name) form.append('name', options.name);
  if (options.overwrite) form.append('overwrite', 'true');
  const res = await fetch('/api/eval/test-sets/upload', { method: 'POST', body: form });
  return handleResponse<TestSetSummary>(res);
}

export async function generateTestSet(req: GenerateTestSetRequest): Promise<string> {
  const res = await fetch('/api/eval/test-sets/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  const { task_id } = await handleResponse<EvalTaskIdResponse>(res);
  return task_id;
}

// ---------- Runs ----------

export async function runEval(req: RunEvalRequest): Promise<string> {
  const res = await fetch('/api/eval/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  const { task_id } = await handleResponse<EvalTaskIdResponse>(res);
  return task_id;
}

export async function getTaskStatus(taskId: string): Promise<EvalTaskStatusResponse> {
  const res = await fetch(`/api/eval/tasks/${encodeURIComponent(taskId)}`);
  return handleResponse<EvalTaskStatusResponse>(res);
}

// ---------- Reports ----------

export async function listReports(): Promise<ReportSummary[]> {
  const res = await fetch('/api/eval/reports');
  return handleResponse<ReportSummary[]>(res);
}

export async function getReport(name: string): Promise<EvalReport> {
  const res = await fetch(`/api/eval/reports/${encodeURIComponent(name)}`);
  return handleResponse<EvalReport>(res);
}

export async function deleteReport(name: string): Promise<void> {
  const res = await fetch(`/api/eval/reports/${encodeURIComponent(name)}`, { method: 'DELETE' });
  return handleNoContent(res);
}

// ---------- Task polling helper ----------

const POLL_INTERVAL_MS = 1000;

export interface PollOptions {
  intervalMs?: number;
  onProgress?: (status: EvalTaskStatusResponse) => void;
  signal?: AbortSignal;
}

/**
 * Poll an eval task until it reaches a terminal state (done or error).
 * Calls onProgress on every poll. Returns the final EvalTaskStatusResponse.
 * Throws if the task ends in error or the signal aborts.
 */
export async function pollEvalTask(
  taskId: string,
  options: PollOptions = {},
): Promise<EvalTaskStatusResponse> {
  const intervalMs = options.intervalMs ?? POLL_INTERVAL_MS;

  while (true) {
    if (options.signal?.aborted) {
      throw new Error('Task polling aborted');
    }
    const status = await getTaskStatus(taskId);
    options.onProgress?.(status);
    if (status.status === 'done') return status;
    if (status.status === 'error') {
      throw new Error(status.error ?? 'Task failed');
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
}
