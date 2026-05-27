export type KeySource = 'env' | 'override' | 'missing';

export interface ApiKeyStatus {
  embedding_api_key: KeySource;
  llm_api_key: KeySource;
  mineru_api_key: KeySource;
}

export interface ApplyKeysPayload {
  embedding_api_key?: string;
  llm_api_key?: string;
  mineru_api_key?: string;
}

interface ApiErrorBody {
  message?: string;
  detail?: string;
}

async function readError(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as ApiErrorBody;
    return body.message ?? `HTTP ${res.status}`;
  } catch {
    return `HTTP ${res.status}`;
  }
}

export async function getApiKeyStatus(): Promise<ApiKeyStatus> {
  const res = await fetch('/api/settings/api-keys/status');
  if (!res.ok) throw new Error(await readError(res));
  return res.json() as Promise<ApiKeyStatus>;
}

export async function applyApiKeys(payload: ApplyKeysPayload): Promise<ApiKeyStatus> {
  const res = await fetch('/api/settings/api-keys', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json() as Promise<ApiKeyStatus>;
}

export async function clearApiKeys(): Promise<ApiKeyStatus> {
  const res = await fetch('/api/settings/api-keys', { method: 'DELETE' });
  if (!res.ok) throw new Error(await readError(res));
  return res.json() as Promise<ApiKeyStatus>;
}
