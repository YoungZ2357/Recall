import { create } from 'zustand';
import { fetchSearch } from '../api/search';
import { streamGenerate } from '../api/generate';
import { buildTopology } from '../api/topology-builder';
import type { SearchResultItem } from '../api/types';
import { DEFAULT_CONFIG, type SearchConfig } from '../components/config-panel-config';
import { readJSON, writeJSON } from './storage';

const CONFIG_KEY = 'recall:search-config';

export interface SearchMeta {
  ms: number;
  topo: string;
  rewrite: string;
  count: number;
}

const TOPO_LABELS: Record<SearchConfig['topo'], string> = {
  vector_only: 'Vector only',
  bm25_only:   'BM25 only',
  rrf:         'Vector + BM25',
  custom:      'Custom',
};

interface SearchState {
  // Persisted user prefs
  config: SearchConfig;

  // In-memory session state
  mode: number;          // 0 = search, 1 = search+gen, 2 = gen
  results: SearchResultItem[];
  generated: string;
  meta: SearchMeta | null;
  loading: boolean;
  streaming: boolean;
  configOpen: boolean;
  sourcesOpen: boolean;
  errorMessage: string | null;
}

interface SearchActions {
  setConfig: (patch: Partial<SearchConfig>) => void;
  setMode: (mode: number) => void;
  toggleConfig: () => void;
  setConfigOpen: (open: boolean) => void;
  toggleSources: () => void;
  clearError: () => void;
  submit: (query: string) => Promise<void>;
}

function loadInitialConfig(): SearchConfig {
  const stored = readJSON<Partial<SearchConfig>>('local', CONFIG_KEY);
  return { ...DEFAULT_CONFIG, ...(stored ?? {}) };
}

export const useSearchStore = create<SearchState & SearchActions>((set, get) => ({
  config: loadInitialConfig(),
  mode: 0,
  results: [],
  generated: '',
  meta: null,
  loading: false,
  streaming: false,
  configOpen: false,
  sourcesOpen: true,
  errorMessage: null,

  setConfig: (patch) => {
    const next = { ...get().config, ...patch };
    set({ config: next });
    writeJSON('local', CONFIG_KEY, next);
  },

  setMode: (mode) => set({ mode }),

  toggleConfig: () => set((s) => ({ configOpen: !s.configOpen })),
  setConfigOpen: (open) => set({ configOpen: open }),
  toggleSources: () => set((s) => ({ sourcesOpen: !s.sourcesOpen })),

  clearError: () => set({ errorMessage: null }),

  submit: async (query) => {
    const { config, mode } = get();
    const showGenerate = mode >= 1;
    const showChunks   = mode <= 1;

    let topology;
    try {
      topology = buildTopology(config);
    } catch (e) {
      set({ errorMessage: e instanceof Error ? e.message : 'Invalid topology config' });
      return;
    }

    set({ loading: true, generated: '', errorMessage: null });
    const t0 = Date.now();

    const searchPromise = showChunks
      ? fetchSearch({ query, top_k: config.topK, mode: config.retention, topology })
      : Promise.resolve([] as SearchResultItem[]);

    const generatePromise = showGenerate
      ? (async () => {
          set({ streaming: true });
          try {
            for await (const frame of streamGenerate({
              query,
              top_k: config.topK,
              mode: config.retention,
              topology,
            })) {
              if (frame.kind === 'token') {
                set((s) => ({ generated: s.generated + frame.content }));
              }
            }
          } finally {
            set({ streaming: false });
          }
        })()
      : Promise.resolve();

    try {
      const [data] = await Promise.all([searchPromise, generatePromise]);
      set({
        results: data,
        meta: {
          ms: Date.now() - t0,
          topo: TOPO_LABELS[config.topo],
          rewrite: config.rewrite,
          count: data.length,
        },
      });
    } catch {
      set({ errorMessage: 'Request failed. Please try again.' });
    } finally {
      set({ loading: false });
    }
  },
}));
