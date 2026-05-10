export interface DocumentSummary {
  doc_id: string;
  filename: string;
  file_type: string;
  chunk_count: number;
  created_at: string;
  weight: number;
  sync_status: string;
}

export interface DocumentDetail extends DocumentSummary {
  total_chunks: number;
  synced_chunks: number;
  tags: string[];
}

export interface ChunkDetail {
  chunk_id: string;
  chunk_index: number;
  content: string;
  context: string | null;
  tags: string[];
  sync_status: string;
}

export interface UploadResponse {
  doc_id: string;
  filename: string;
  chunk_count: number;
  status: string;
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Request failed ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export async function fetchDocuments(): Promise<DocumentSummary[]> {
  const res = await fetch('/api/documents');
  return handleResponse<DocumentSummary[]>(res);
}

export async function fetchDocumentDetail(docId: string): Promise<DocumentDetail> {
  const res = await fetch(`/api/documents/${docId}`);
  return handleResponse<DocumentDetail>(res);
}

export async function fetchDocumentChunks(docId: string): Promise<ChunkDetail[]> {
  const res = await fetch(`/api/documents/${docId}/chunks`);
  return handleResponse<ChunkDetail[]>(res);
}

export async function uploadDocument(file: File): Promise<UploadResponse> {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch('/api/documents/upload', { method: 'POST', body: form });
  return handleResponse<UploadResponse>(res);
}

export async function deleteDocument(docId: string): Promise<void> {
  const res = await fetch(`/api/documents/${docId}`, { method: 'DELETE' });
  await handleResponse<unknown>(res);
}

export async function updateDocumentWeight(docId: string, weight: number): Promise<DocumentSummary> {
  const res = await fetch(`/api/documents/${docId}/weight`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ weight }),
  });
  return handleResponse<DocumentSummary>(res);
}
