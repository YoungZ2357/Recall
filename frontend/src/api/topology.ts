import type { TopologySpecJSON } from './types';

// ---------------------------------------------------------------------------
// Local types (not in api/types.ts to avoid affecting existing code)
// ---------------------------------------------------------------------------

export interface NodeTypeEntry {
  node_type: string;
  display_name: string;
  node_role: 'SOURCE' | 'TRANSFORM' | 'MERGE';
  available: boolean;
  config_schema: Record<string, unknown> | null;
}

export interface PresetRow {
  id: number;
  name: string;
  description: string | null;
  is_builtin: boolean;
  created_at: string;
  spec: TopologySpecJSON;
}

export interface ValidationResult {
  valid: boolean;
  errors: string[];
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? '';

export async function fetchNodeTypes(): Promise<NodeTypeEntry[]> {
  const res = await fetch(`${BASE}/api/topology/node-types`);
  if (!res.ok) throw new Error(`fetchNodeTypes: ${res.status}`);
  return res.json() as Promise<NodeTypeEntry[]>;
}

export async function validateTopology(
  spec: TopologySpecJSON,
): Promise<ValidationResult> {
  const res = await fetch(`${BASE}/api/topology/validate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(spec),
  });
  if (!res.ok) throw new Error(`validateTopology: ${res.status}`);
  return res.json() as Promise<ValidationResult>;
}

export async function listPresets(): Promise<PresetRow[]> {
  const res = await fetch(`${BASE}/api/topology/presets`);
  if (!res.ok) throw new Error(`listPresets: ${res.status}`);
  return res.json() as Promise<PresetRow[]>;
}

export async function createPreset(
  name: string,
  description: string | null,
  spec: TopologySpecJSON,
): Promise<PresetRow> {
  const res = await fetch(`${BASE}/api/topology/presets`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, description, spec }),
  });
  if (!res.ok) throw new Error(`createPreset: ${res.status}`);
  return res.json() as Promise<PresetRow>;
}

export async function deletePresetById(id: number): Promise<void> {
  const res = await fetch(`${BASE}/api/topology/presets/${id}`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error(`deletePreset: ${res.status}`);
}
