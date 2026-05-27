import type { SourceInfo, TopologySpecJSON } from './types';

interface GenerateApiRequest {
  query: string;
  top_k?: number;
  mode?: string;
  topology?: TopologySpecJSON;
}

// Discriminated union of SSE frames emitted by POST /generate (stream=true).
// New frame types should add a new variant here; callers switch on `kind`.
export type GenerateFrame =
  | { kind: 'token'; content: string }
  | { kind: 'sources'; sources: SourceInfo[] }
  | { kind: 'unknown'; raw: unknown };

function parseFrame(payload: string): GenerateFrame | null {
  let obj: unknown;
  try {
    obj = JSON.parse(payload);
  } catch {
    return null;
  }
  if (obj && typeof obj === 'object') {
    const o = obj as Record<string, unknown>;
    if (typeof o.content === 'string') {
      return { kind: 'token', content: o.content };
    }
    if (Array.isArray(o.sources)) {
      return { kind: 'sources', sources: o.sources as SourceInfo[] };
    }
  }
  return { kind: 'unknown', raw: obj };
}

export async function* streamGenerate(req: GenerateApiRequest): AsyncGenerator<GenerateFrame> {
  const res = await fetch('/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...req, stream: true }),
  });

  if (!res.ok) {
    throw new Error(`Generate request failed: ${res.status}`);
  }

  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buf = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split('\n');
    buf = lines.pop()!;
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      const payload = line.slice(6);
      if (payload === '[DONE]') return;
      const frame = parseFrame(payload);
      if (frame) yield frame;
    }
  }
}
