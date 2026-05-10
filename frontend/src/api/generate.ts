interface GenerateApiRequest {
  query: string;
  top_k?: number;
  mode?: string;
}

// Yields SSE payload strings (text tokens or final sources JSON).
// Caller should check if a yielded value starts with '{' to detect the sources frame.
export async function* streamGenerate(req: GenerateApiRequest): AsyncGenerator<string> {
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
      yield payload;
    }
  }
}
