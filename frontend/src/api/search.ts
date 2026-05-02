import type { SearchRequest, SearchResultItem } from './types';

export async function fetchSearch(req: SearchRequest): Promise<SearchResultItem[]> {
  const res = await fetch('/api/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  if (!res.ok) throw new Error(`Search failed: ${res.status}`);
  return res.json() as Promise<SearchResultItem[]>;
}
