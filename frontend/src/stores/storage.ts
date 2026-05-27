// Safe wrappers around Web Storage that swallow exceptions
// (private mode / disabled storage / quota errors must not crash the app).

type StorageKind = 'local' | 'session';

function pick(kind: StorageKind): Storage | null {
  try {
    return kind === 'local' ? window.localStorage : window.sessionStorage;
  } catch {
    return null;
  }
}

export function readJSON<T>(kind: StorageKind, key: string): T | null {
  const store = pick(kind);
  if (!store) return null;
  try {
    const raw = store.getItem(key);
    if (raw == null) return null;
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

export function writeJSON<T>(kind: StorageKind, key: string, value: T): void {
  const store = pick(kind);
  if (!store) return;
  try {
    store.setItem(key, JSON.stringify(value));
  } catch {
    /* ignore quota / serialization errors */
  }
}

export function remove(kind: StorageKind, key: string): void {
  const store = pick(kind);
  if (!store) return;
  try {
    store.removeItem(key);
  } catch {
    /* ignore */
  }
}
