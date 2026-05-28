import { create } from 'zustand';
import {
  applyNodeChanges,
  applyEdgeChanges,
  addEdge,
  MarkerType,
  type Node,
  type Edge,
  type NodeChange,
  type EdgeChange,
  type Connection,
} from '@xyflow/react';
import {
  fetchNodeTypes,
  listPresets,
  createPreset,
  deletePresetById,
  validateTopology,
  type NodeTypeEntry,
  type PresetRow,
  type ValidationResult,
} from '../api/topology';
import type { TopologySpecJSON, NodeSpecJSON, EdgeJSON } from '../api/types';

// ---------------------------------------------------------------------------
// Node data shape (must extend Record<string, unknown> for React Flow)
// ---------------------------------------------------------------------------

export interface PipelineNodeData extends Record<string, unknown> {
  node_type: string;
  node_role: 'SOURCE' | 'TRANSFORM' | 'MERGE';
  config: Record<string, unknown>;
  label: string;
  available: boolean;
}

export type PipelineRFNode = Node<PipelineNodeData>;

// ---------------------------------------------------------------------------
// Default configs per node type
// ---------------------------------------------------------------------------

const DEFAULT_CONFIGS: Record<string, Record<string, unknown>> = {
  VectorSearcher: { score_threshold: 0.2, top_k: 10, collection_name: 'recall' },
  BM25Searcher: { score_threshold: 0.2, top_k: 10, recall_multiplier: 2 },
  ContextualBM25Searcher: { score_threshold: 0.2, top_k: 10, recall_multiplier: 2 },
  RRFMerger: { k: 60 },
  Reranker: {
    alpha: 0.85,
    beta: 0.15,
    gamma: 0.0,
    score_threshold: 0.60,
    retention_mode: 'prefer_recent',
  },
};

// ---------------------------------------------------------------------------
// Layout helpers
// ---------------------------------------------------------------------------

/** Simple left-to-right topological layout for a DAG. */
function autoLayout(
  nodes: NodeSpecJSON[],
  edges: EdgeJSON[],
): Map<string, { x: number; y: number }> {
  const COL_W = 200;
  const ROW_H = 120;

  const inDegree = new Map<string, number>();
  const downstream = new Map<string, string[]>();

  for (const n of nodes) {
    inDegree.set(n.node_id, 0);
    downstream.set(n.node_id, []);
  }
  for (const e of edges) {
    inDegree.set(e.to_node, (inDegree.get(e.to_node) ?? 0) + 1);
    downstream.get(e.from_node)?.push(e.to_node);
  }

  // Kahn's BFS: assign column = max(parent column + 1)
  const col = new Map<string, number>();
  const queue: string[] = [];
  for (const [id, deg] of inDegree) {
    if (deg === 0) { queue.push(id); col.set(id, 0); }
  }

  while (queue.length > 0) {
    const id = queue.shift()!;
    for (const next of (downstream.get(id) ?? [])) {
      const nextCol = Math.max(col.get(next) ?? 0, (col.get(id) ?? 0) + 1);
      col.set(next, nextCol);
      const deg = (inDegree.get(next) ?? 1) - 1;
      inDegree.set(next, deg);
      if (deg === 0) queue.push(next);
    }
  }

  // Group by column, assign rows centered at y=0
  const colGroups = new Map<number, string[]>();
  for (const n of nodes) {
    const c = col.get(n.node_id) ?? 0;
    if (!colGroups.has(c)) colGroups.set(c, []);
    colGroups.get(c)!.push(n.node_id);
  }

  const positions = new Map<string, { x: number; y: number }>();
  for (const [c, ids] of colGroups) {
    const total = ids.length;
    ids.forEach((id, rowIdx) => {
      positions.set(id, {
        x: c * COL_W + 60,
        y: (rowIdx - (total - 1) / 2) * ROW_H + 145,
      });
    });
  }
  return positions;
}

// ---------------------------------------------------------------------------
// Conversion helpers
// ---------------------------------------------------------------------------

function roleToRFType(role: 'SOURCE' | 'TRANSFORM' | 'MERGE'): string {
  if (role === 'SOURCE') return 'sourceNode';
  if (role === 'MERGE') return 'mergeNode';
  return 'transformNode';
}

function specToFlow(
  spec: TopologySpecJSON,
  catalog: NodeTypeEntry[],
): { nodes: PipelineRFNode[]; edges: Edge[] } {
  const catalogMap = new Map(catalog.map(e => [e.node_type, e]));
  const positions = autoLayout(spec.nodes, spec.edges);

  const nodes: PipelineRFNode[] = spec.nodes.map(n => {
    const info = catalogMap.get(n.node_type);
    const role = info?.node_role ?? 'SOURCE';
    const pos = positions.get(n.node_id) ?? { x: 60, y: 145 };
    return {
      id: n.node_id,
      type: roleToRFType(role),
      position: pos,
      data: {
        node_type: n.node_type,
        node_role: role,
        config: (n.config as Record<string, unknown>) ?? {},
        label: info?.display_name ?? n.node_type,
        available: info?.available ?? true,
      },
    };
  });

  const edges: Edge[] = spec.edges.map(e => ({
    id: `${e.from_node}->${e.to_node}`,
    source: e.from_node,
    target: e.to_node,
    type: 'smoothstep',
    markerEnd: { type: MarkerType.ArrowClosed },
  }));

  return { nodes, edges };
}

function flowToSpec(nodes: PipelineRFNode[], edges: Edge[]): TopologySpecJSON {
  return {
    nodes: nodes.map(n => ({
      node_id: n.id,
      node_type: n.data.node_type,
      config: n.data.config,
    })),
    edges: edges.map(e => ({
      from_node: e.source,
      to_node: e.target,
    })),
  };
}

function makeNodeId(nodeType: string, existing: PipelineRFNode[]): string {
  const prefix = nodeType
    .replace('Searcher', '')
    .replace('Merger', 'merge')
    .replace('Contextual', 'ctx')
    .toLowerCase();
  let i = 1;
  while (existing.some(n => n.id === `${prefix}_${i}`)) i++;
  return `${prefix}_${i}`;
}

// ---------------------------------------------------------------------------
// Store types
// ---------------------------------------------------------------------------

interface PipelineState {
  // Preset catalog
  presets: PresetRow[];
  presetsLoaded: boolean;
  // Node type catalog
  catalog: NodeTypeEntry[];
  catalogLoaded: boolean;
  // Active editing session
  activeId: number | null;    // null = new (unsaved)
  activeName: string;
  rfNodes: PipelineRFNode[];
  rfEdges: Edge[];
  isDirty: boolean;
  // UI state
  selectedNodeId: string | null;
  validationResult: ValidationResult | null;
  isValidating: boolean;
  isSaving: boolean;
}

interface PipelineActions {
  loadPresetsIfNeeded: () => Promise<void>;
  loadCatalogIfNeeded: () => Promise<void>;
  openPreset: (id: number) => void;
  newPreset: () => void;
  onNodesChange: (changes: NodeChange<PipelineRFNode>[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  onConnect: (connection: Connection) => void;
  selectNode: (id: string | null) => void;
  addNode: (nodeType: string) => void;
  updateNodeConfig: (nodeId: string, patch: Record<string, unknown>) => void;
  deleteSelectedNode: () => void;
  validate: () => Promise<ValidationResult>;
  save: (name: string) => Promise<void>;
  deletePreset: (id: number) => Promise<void>;
  toSpec: () => TopologySpecJSON;
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export const usePipelineStore = create<PipelineState & PipelineActions>((set, get) => ({
  presets: [],
  presetsLoaded: false,
  catalog: [],
  catalogLoaded: false,
  activeId: null,
  activeName: '',
  rfNodes: [],
  rfEdges: [],
  isDirty: false,
  selectedNodeId: null,
  validationResult: null,
  isValidating: false,
  isSaving: false,

  // ── loaders ──────────────────────────────────────────────────────────────

  loadPresetsIfNeeded: async () => {
    if (get().presetsLoaded) return;
    const rows = await listPresets();
    set({ presets: rows, presetsLoaded: true });
  },

  loadCatalogIfNeeded: async () => {
    if (get().catalogLoaded) return;
    const entries = await fetchNodeTypes();
    set({ catalog: entries, catalogLoaded: true });
  },

  // ── session management ────────────────────────────────────────────────────

  openPreset: (id) => {
    const preset = get().presets.find(p => p.id === id);
    if (!preset) return;
    const { nodes, edges } = specToFlow(preset.spec, get().catalog);
    set({
      activeId: id,
      activeName: preset.name,
      rfNodes: nodes,
      rfEdges: edges,
      isDirty: false,
      selectedNodeId: null,
      validationResult: null,
    });
  },

  newPreset: () => {
    set({
      activeId: null,
      activeName: '',
      rfNodes: [],
      rfEdges: [],
      isDirty: false,
      selectedNodeId: null,
      validationResult: null,
    });
  },

  // ── React Flow change handlers ────────────────────────────────────────────

  onNodesChange: (changes) => {
    const updated = applyNodeChanges(changes, get().rfNodes);

    // Sync selection state with inspector panel
    for (const c of changes) {
      if (c.type === 'select') {
        if (c.selected) {
          set({ selectedNodeId: c.id });
        } else if (get().selectedNodeId === c.id) {
          const anySelected = updated.some(n => n.selected);
          if (!anySelected) set({ selectedNodeId: null });
        }
      }
    }

    set({ rfNodes: updated });
  },

  onEdgesChange: (changes) => {
    const updated = applyEdgeChanges(changes, get().rfEdges);
    const hasRemove = changes.some(c => c.type === 'remove');
    if (hasRemove) set({ isDirty: true });
    set({ rfEdges: updated });
  },

  onConnect: (connection) => {
    const newEdge: Edge = {
      id: `${connection.source}->${connection.target}`,
      source: connection.source ?? '',
      target: connection.target ?? '',
      type: 'smoothstep',
      markerEnd: { type: MarkerType.ArrowClosed },
    };
    set({ rfEdges: addEdge(newEdge, get().rfEdges), isDirty: true });
  },

  // ── selection ─────────────────────────────────────────────────────────────

  selectNode: (id) => set({ selectedNodeId: id }),

  // ── canvas mutations ──────────────────────────────────────────────────────

  addNode: (nodeType) => {
    const info = get().catalog.find(e => e.node_type === nodeType);
    if (!info) return;
    const existing = get().rfNodes;
    const nodeId = makeNodeId(nodeType, existing);
    const col = existing.length;
    const newNode: PipelineRFNode = {
      id: nodeId,
      type: roleToRFType(info.node_role),
      position: { x: 60 + (col % 5) * 190, y: 80 + Math.floor(col / 5) * 120 },
      data: {
        node_type: nodeType,
        node_role: info.node_role,
        config: { ...(DEFAULT_CONFIGS[nodeType] ?? {}) },
        label: info.display_name,
        available: info.available,
      },
    };
    set({ rfNodes: [...existing, newNode], isDirty: true });
  },

  updateNodeConfig: (nodeId, patch) => {
    const updated = get().rfNodes.map(n => {
      if (n.id !== nodeId) return n;
      return { ...n, data: { ...n.data, config: { ...n.data.config, ...patch } } };
    });
    set({ rfNodes: updated, isDirty: true });
  },

  deleteSelectedNode: () => {
    const { selectedNodeId, rfNodes, rfEdges } = get();
    if (!selectedNodeId) return;
    set({
      rfNodes: rfNodes.filter(n => n.id !== selectedNodeId),
      rfEdges: rfEdges.filter(
        e => e.source !== selectedNodeId && e.target !== selectedNodeId,
      ),
      selectedNodeId: null,
      isDirty: true,
    });
  },

  // ── backend operations ────────────────────────────────────────────────────

  validate: async () => {
    set({ isValidating: true });
    try {
      const spec = get().toSpec();
      const result = await validateTopology(spec);
      set({ validationResult: result });
      return result;
    } finally {
      set({ isValidating: false });
    }
  },

  save: async (name: string) => {
    set({ isSaving: true });
    try {
      const spec = get().toSpec();
      const { activeId, presets } = get();
      const activePreset = activeId != null ? presets.find(p => p.id === activeId) : null;

      // Delete existing user preset before recreating (update semantics)
      if (activePreset && !activePreset.is_builtin) {
        await deletePresetById(activeId!);
      }

      const created = await createPreset(name, null, spec);
      const updated = await listPresets();
      set({
        presets: updated,
        activeId: created.id,
        activeName: name,
        isDirty: false,
      });
    } finally {
      set({ isSaving: false });
    }
  },

  deletePreset: async (id) => {
    await deletePresetById(id);
    const { activeId } = get();
    const updated = await listPresets();
    set({
      presets: updated,
      ...(activeId === id
        ? { activeId: null, activeName: '', rfNodes: [], rfEdges: [], selectedNodeId: null }
        : {}),
    });
  },

  toSpec: () => flowToSpec(get().rfNodes, get().rfEdges),
}));
