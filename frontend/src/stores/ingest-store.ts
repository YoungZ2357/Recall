import { create } from 'zustand';
import { startIngestion, pollTaskStatus, HttpError } from '../api/ingest';
import type { IngestConfig, IngestTask, UploadFile } from '../types/ingest';
import { readJSON, writeJSON, remove } from './storage';

const CONFIG_KEY = 'recall:ingest-config';
const ACTIVE_TASK_KEY = 'recall:ingest-active-task';
const POLL_INTERVAL_MS = 1000;
// While the backend hasn't yet registered the task (between /api/upload and
// /api/ingest returning), polling will 404. Tolerate that for this long; after
// the grace expires we surface the error instead of looping silently.
const LAUNCH_GRACE_MS = 30_000;

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
  // Flips true on the first successful poll (HTTP 200). Once confirmed, a 404
  // is treated as "task is gone" (backend restart / eviction) rather than a
  // not-yet-registered race.
  taskConfirmed: boolean;
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
// Deadline for tolerating 404s on a not-yet-confirmed task. Refreshed every
// time polling (re)starts.
let graceUntil = 0;

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
      if (!get().taskConfirmed) set({ taskConfirmed: true });
      set({ task });
      if (task.status === 'done' || task.status === 'error') {
        stopPolling();
        // Intentionally keep ACTIVE_TASK_KEY in sessionStorage so a hard
        // refresh after completion can re-fetch the terminal state from the
        // backend's in-memory TaskStore. Cleared only via resetWizard /
        // clearTask.
      }
    } catch (e) {
      if (get().activeTaskId !== taskId) return;
      if (e instanceof HttpError && e.status === 404) {
        const confirmed = get().taskConfirmed;
        if (!confirmed && Date.now() < graceUntil) {
          // Task not yet registered on backend — keep retrying within grace.
          return;
        }
        // Either the task was confirmed and then disappeared (backend restart)
        // or grace expired without ever seeing a 200 (launch never reached the
        // task_store). Surface and stop.
        const message = confirmed
          ? '任务记录已丢失（后端可能已重启）'
          : '后端未注册该摄入任务（启动失败或已超时）';
        get().clearTask();
        set({ startError: message });
        return;
      }
      // Other errors (network blip, 5xx, etc.) — keep polling silently.
    }
  }

  function beginPolling(taskId: string) {
    stopPolling();
    graceUntil = Date.now() + LAUNCH_GRACE_MS;
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
    taskConfirmed: false,

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
        taskConfirmed: false,
      });
    },

    clearTask: () => {
      stopPolling();
      remove('session', ACTIVE_TASK_KEY);
      set({ activeTaskId: null, task: null, taskConfirmed: false });
    },

    startTask: async () => {
      const { files, config, activeTaskId, starting } = get();
      if (activeTaskId || starting) return; // already running or in flight
      if (files.length === 0) return;

      // Persist task_id BEFORE any await so a refresh at any point is
      // recoverable. Backend will register the same id via /api/ingest's
      // task_id field.
      const taskId = crypto.randomUUID();
      writeJSON('session', ACTIVE_TASK_KEY, taskId);
      set({
        activeTaskId: taskId,
        currentStep: 3,
        task: null,
        starting: true,
        startError: null,
        taskConfirmed: false,
      });
      beginPolling(taskId);

      try {
        await startIngestion(files, config, taskId);
      } catch (e) {
        // If the user already reset / a 404 path already cleaned up, bail.
        if (get().activeTaskId !== taskId) return;
        stopPolling();
        remove('session', ACTIVE_TASK_KEY);
        set({
          activeTaskId: null,
          task: null,
          taskConfirmed: false,
          startError: e instanceof Error ? e.message : 'Failed to start ingestion',
        });
      } finally {
        set({ starting: false });
      }
    },

    resumeIfPending: async () => {
      // Avoid double-resume if another mount already restored.
      if (pollTimer) return;
      const taskId = readJSON<string>('session', ACTIVE_TASK_KEY);
      if (!taskId) return;
      set({
        activeTaskId: taskId,
        currentStep: 3,
        taskConfirmed: false,
        startError: null,
      });
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
