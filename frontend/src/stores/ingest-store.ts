import { create } from 'zustand';
import { startIngestion, pollTaskStatus } from '../api/ingest';
import type { IngestConfig, IngestTask, UploadFile } from '../types/ingest';
import { readJSON, writeJSON, remove } from './storage';

const CONFIG_KEY = 'recall:ingest-config';
const ACTIVE_TASK_KEY = 'recall:ingest-active-task';
const POLL_INTERVAL_MS = 1000;

export const DEFAULT_INGEST_CONFIG: IngestConfig = {
  pdfParser: 'pymupdf',
  stripTail: true,
  stripMarkdown: false,
  chunkStrategy: 'recursive',
  chunkSize: 512,
  chunkOverlap: 64,
  targetChunks: 20,
  overlapRatio: 0.1,
  contextualize: true,
  contextConcurrency: 8,
  autoTag: true,
};

function loadInitialConfig(): IngestConfig {
  const stored = readJSON<Partial<IngestConfig>>('local', CONFIG_KEY);
  return { ...DEFAULT_INGEST_CONFIG, ...(stored ?? {}) };
}

interface IngestState {
  currentStep: number;          // 0: upload, 1: configure, 2: review, 3: result
  files: UploadFile[];          // in-memory only (File objects are not serializable)
  config: IngestConfig;         // persisted to localStorage
  activeTaskId: string | null;  // persisted to sessionStorage
  task: IngestTask | null;      // latest poll snapshot
  starting: boolean;            // true between user clicking Start and getting a task_id
  startError: string | null;
}

interface IngestActions {
  addFiles: (files: File[]) => void;
  removeFile: (id: string) => void;
  setStep: (step: number) => void;
  setConfig: (patch: Partial<IngestConfig>) => void;
  resetWizard: () => void;
  startTask: () => Promise<void>;
  resumeIfPending: () => Promise<void>;
  clearTask: () => void;
}

// Singleton polling handle — kept outside zustand state to avoid stale-closure
// concerns and re-render churn.
let pollTimer: ReturnType<typeof setInterval> | null = null;

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

export const useIngestStore = create<IngestState & IngestActions>((set, get) => {
  async function pollOnce(taskId: string) {
    try {
      const task = await pollTaskStatus(taskId);
      // If the user reset/cleared while polling, drop this result.
      if (get().activeTaskId !== taskId) return;
      set({ task });
      if (task.status === 'done' || task.status === 'error') {
        stopPolling();
        remove('session', ACTIVE_TASK_KEY);
      }
    } catch {
      // Network blip — keep polling; surface only via task being stale.
    }
  }

  function beginPolling(taskId: string) {
    stopPolling();
    void pollOnce(taskId);
    pollTimer = setInterval(() => void pollOnce(taskId), POLL_INTERVAL_MS);
  }

  return {
    currentStep: 0,
    files: [],
    config: loadInitialConfig(),
    activeTaskId: null,
    task: null,
    starting: false,
    startError: null,

    addFiles: (newFiles) => {
      const mapped: UploadFile[] = newFiles.map((f) => {
        const ext = f.name.split('.').pop()?.toLowerCase() ?? '';
        const type = (ext === 'pdf' ? 'pdf' : ext === 'md' ? 'md' : 'txt') as UploadFile['type'];
        return {
          id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
          file: f,
          name: f.name,
          size: f.size,
          type,
        };
      });
      set((s) => ({ files: [...s.files, ...mapped] }));
    },

    removeFile: (id) => set((s) => ({ files: s.files.filter((f) => f.id !== id) })),

    setStep: (step) => set({ currentStep: step }),

    setConfig: (patch) => {
      const next = { ...get().config, ...patch };
      set({ config: next });
      writeJSON('local', CONFIG_KEY, next);
    },

    resetWizard: () => {
      stopPolling();
      remove('session', ACTIVE_TASK_KEY);
      set({
        currentStep: 0,
        files: [],
        activeTaskId: null,
        task: null,
        starting: false,
        startError: null,
      });
    },

    clearTask: () => {
      stopPolling();
      remove('session', ACTIVE_TASK_KEY);
      set({ activeTaskId: null, task: null });
    },

    startTask: async () => {
      const { files, config, activeTaskId, starting } = get();
      if (activeTaskId || starting) return; // already running or in flight
      if (files.length === 0) return;

      set({ starting: true, startError: null });
      try {
        const taskId = await startIngestion(files, config);
        writeJSON('session', ACTIVE_TASK_KEY, taskId);
        set({ activeTaskId: taskId, task: null });
        beginPolling(taskId);
      } catch (e) {
        set({ startError: e instanceof Error ? e.message : 'Failed to start ingestion' });
      } finally {
        set({ starting: false });
      }
    },

    resumeIfPending: async () => {
      // Avoid double-resume if another mount already restored.
      if (pollTimer) return;
      const taskId = readJSON<string>('session', ACTIVE_TASK_KEY);
      if (!taskId) return;
      set({ activeTaskId: taskId, currentStep: 3 });
      beginPolling(taskId);
    },
  };
});

// HMR cleanup: avoid duplicate intervals across hot updates in dev.
if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    stopPolling();
  });
}
