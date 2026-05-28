import { create } from 'zustand';
import {
  deleteReport,
  deleteTestSet,
  generateTestSet,
  listReports,
  listTestSets,
  pollEvalTask,
  runEval,
  uploadTestSet,
  HttpError,
} from '../api/eval';
import type {
  EvalTaskStatusResponse,
  GenerateTestSetRequest,
  ReportSummary,
  TestSetSummary,
  TopologySpecJSON,
} from '../api/types';
import {
  buildTopologyFromPreset,
  type RerankerWeights,
  type RetrieverThresholds,
  type TopologyPresetId,
} from '../pages/eval/topology-presets';
import { readJSON, writeJSON } from './storage';

const CONFIG_KEY = 'recall:eval-config';

export type MetricKey = 'mrr' | 'ndcg10' | 'recall10';

export interface EvalRunConfig {
  topologyPreset: TopologyPresetId;
  customTopology: TopologySpecJSON | null;
  topK: number;
  weights: RerankerWeights;
  thresholds: RetrieverThresholds;
  mode: 'prefer_recent' | 'awaken_forgotten';
  metrics: Record<MetricKey, boolean>;
}

const DEFAULT_CONFIG: EvalRunConfig = {
  topologyPreset: 'v_b_rrf',
  customTopology: null,
  topK: 10,
  weights: { alpha: 0.85, beta: 0.15, gamma: 0.0 },
  thresholds: { vectorThreshold: 0.2, rerankerThreshold: 0.6 },
  mode: 'prefer_recent',
  metrics: { mrr: true, ndcg10: true, recall10: true },
};

export interface ActiveTask {
  taskId: string;
  kind: 'generate' | 'run';
  status: EvalTaskStatusResponse | null;
}

interface EvalState {
  testSets: TestSetSummary[];
  reports: ReportSummary[];
  selectedTestSetName: string | null;
  runConfig: EvalRunConfig;
  activeTask: ActiveTask | null;
  loading: boolean;
  errorMessage: string | null;
  generatePanelOpen: boolean;
}

interface EvalActions {
  loadTestSets: () => Promise<void>;
  loadReports: () => Promise<void>;
  selectTestSet: (name: string | null) => void;
  updateRunConfig: (patch: Partial<EvalRunConfig>) => void;
  updateWeights: (patch: Partial<RerankerWeights>) => void;
  setMetricEnabled: (metric: MetricKey, enabled: boolean) => void;
  setCustomTopology: (spec: TopologySpecJSON | null) => void;
  uploadTestSet: (file: File, overwrite?: boolean) => Promise<void>;
  deleteTestSet: (name: string) => Promise<void>;
  generateTestSet: (req: GenerateTestSetRequest) => Promise<void>;
  runEvaluation: () => Promise<void>;
  deleteReport: (name: string) => Promise<void>;
  setGeneratePanelOpen: (open: boolean) => void;
  clearError: () => void;
}

function loadInitialConfig(): EvalRunConfig {
  const stored = readJSON<Partial<EvalRunConfig>>('local', CONFIG_KEY);
  return {
    ...DEFAULT_CONFIG,
    ...(stored ?? {}),
    weights: { ...DEFAULT_CONFIG.weights, ...(stored?.weights ?? {}) },
    thresholds: { ...DEFAULT_CONFIG.thresholds, ...(stored?.thresholds ?? {}) },
    metrics: { ...DEFAULT_CONFIG.metrics, ...(stored?.metrics ?? {}) },
  };
}

function persistConfig(cfg: EvalRunConfig): void {
  writeJSON('local', CONFIG_KEY, cfg);
}

function buildReportName(testSetName: string): string {
  // ISO-style timestamp without colons/dots so it matches NAME_PATTERN.
  const now = new Date();
  const ts =
    now.getFullYear().toString() +
    String(now.getMonth() + 1).padStart(2, '0') +
    String(now.getDate()).padStart(2, '0') +
    '-' +
    String(now.getHours()).padStart(2, '0') +
    String(now.getMinutes()).padStart(2, '0') +
    String(now.getSeconds()).padStart(2, '0');
  // Cap test_set_name to keep the combined length under 64 chars.
  const truncated = testSetName.length > 38 ? testSetName.slice(0, 38) : testSetName;
  return `${truncated}__${ts}`;
}

function describeError(e: unknown, fallback: string): string {
  if (e instanceof HttpError) return `${fallback} (HTTP ${e.status})`;
  if (e instanceof Error) return e.message || fallback;
  return fallback;
}

export const useEvalStore = create<EvalState & EvalActions>((set, get) => ({
  testSets: [],
  reports: [],
  selectedTestSetName: null,
  runConfig: loadInitialConfig(),
  activeTask: null,
  loading: false,
  errorMessage: null,
  generatePanelOpen: false,

  loadTestSets: async () => {
    try {
      const testSets = await listTestSets();
      set((s) => {
        // Preserve current selection if it still exists; otherwise pick the
        // first dataset (matches mock-up: a dataset is always selected when
        // any exist).
        const stillSelected =
          s.selectedTestSetName && testSets.some((t) => t.name === s.selectedTestSetName);
        return {
          testSets,
          selectedTestSetName: stillSelected
            ? s.selectedTestSetName
            : (testSets[0]?.name ?? null),
        };
      });
    } catch (e) {
      set({ errorMessage: describeError(e, 'Failed to load test sets') });
    }
  },

  loadReports: async () => {
    try {
      const reports = await listReports();
      set({ reports });
    } catch (e) {
      set({ errorMessage: describeError(e, 'Failed to load reports') });
    }
  },

  selectTestSet: (name) => set({ selectedTestSetName: name }),

  updateRunConfig: (patch) => {
    const next = { ...get().runConfig, ...patch };
    set({ runConfig: next });
    persistConfig(next);
  },

  updateWeights: (patch) => {
    const next = { ...get().runConfig, weights: { ...get().runConfig.weights, ...patch } };
    set({ runConfig: next });
    persistConfig(next);
  },

  setMetricEnabled: (metric, enabled) => {
    const next = {
      ...get().runConfig,
      metrics: { ...get().runConfig.metrics, [metric]: enabled },
    };
    set({ runConfig: next });
    persistConfig(next);
  },

  setCustomTopology: (spec) => {
    const next = { ...get().runConfig, customTopology: spec };
    set({ runConfig: next });
    persistConfig(next);
  },

  uploadTestSet: async (file, overwrite = false) => {
    set({ loading: true, errorMessage: null });
    try {
      const summary = await uploadTestSet(file, { overwrite });
      await get().loadTestSets();
      set({ selectedTestSetName: summary.name });
    } catch (e) {
      if (e instanceof HttpError && e.status === 409 && !overwrite) {
        throw e; // let caller decide whether to retry with overwrite
      }
      set({ errorMessage: describeError(e, 'Upload failed') });
      throw e;
    } finally {
      set({ loading: false });
    }
  },

  deleteTestSet: async (name) => {
    try {
      await deleteTestSet(name);
      await get().loadTestSets();
    } catch (e) {
      set({ errorMessage: describeError(e, 'Delete failed') });
    }
  },

  generateTestSet: async (req) => {
    set({ errorMessage: null });
    try {
      const taskId = await generateTestSet(req);
      set({ activeTask: { taskId, kind: 'generate', status: null } });
      await pollEvalTask(taskId, {
        onProgress: (status) =>
          set({ activeTask: { taskId, kind: 'generate', status } }),
      });
      await get().loadTestSets();
      set({ selectedTestSetName: req.name, activeTask: null, generatePanelOpen: false });
    } catch (e) {
      set({
        errorMessage: describeError(e, 'Generate failed'),
        activeTask: null,
      });
    }
  },

  runEvaluation: async () => {
    const { selectedTestSetName, runConfig } = get();
    if (!selectedTestSetName) {
      set({ errorMessage: 'Select a test set first' });
      return;
    }
    const topology = buildTopologyFromPreset(
      runConfig.topologyPreset,
      runConfig.weights,
      runConfig.thresholds,
      runConfig.customTopology,
    );
    if (runConfig.topologyPreset === 'custom' && topology === null) {
      set({ errorMessage: 'Custom topology JSON is empty' });
      return;
    }

    set({ errorMessage: null });
    try {
      const taskId = await runEval({
        test_set_name: selectedTestSetName,
        top_k: runConfig.topK,
        mode: runConfig.mode,
        report_name: buildReportName(selectedTestSetName),
        persist_report: true,
        ...(topology ? { topology } : {}),
      });
      set({ activeTask: { taskId, kind: 'run', status: null } });
      await pollEvalTask(taskId, {
        onProgress: (status) =>
          set({ activeTask: { taskId, kind: 'run', status } }),
      });
      await get().loadReports();
      set({ activeTask: null });
    } catch (e) {
      set({
        errorMessage: describeError(e, 'Evaluation failed'),
        activeTask: null,
      });
    }
  },

  deleteReport: async (name) => {
    try {
      await deleteReport(name);
      await get().loadReports();
    } catch (e) {
      set({ errorMessage: describeError(e, 'Delete report failed') });
    }
  },

  setGeneratePanelOpen: (open) => set({ generatePanelOpen: open }),
  clearError: () => set({ errorMessage: null }),
}));
