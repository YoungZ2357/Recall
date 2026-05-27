import { create } from 'zustand';
import {
  applyApiKeys,
  clearApiKeys,
  getApiKeyStatus,
  type ApiKeyStatus,
  type ApplyKeysPayload,
} from '../api/settings';
import { readJSON, writeJSON, remove } from './storage';

const DRAFT_KEY = 'recall:settings-draft';

export interface DraftKeys {
  embedding_api_key: string;
  llm_api_key: string;
  mineru_api_key: string;
}

const EMPTY_DRAFT: DraftKeys = {
  embedding_api_key: '',
  llm_api_key: '',
  mineru_api_key: '',
};

interface SettingsState {
  draft: DraftKeys;
  status: ApiKeyStatus | null;
  loading: boolean;
  applying: boolean;
  errorMessage: string | null;
}

interface SettingsActions {
  setDraftField: (field: keyof DraftKeys, value: string) => void;
  resetDraft: () => void;
  refreshStatus: () => Promise<void>;
  apply: () => Promise<boolean>;
  clear: () => Promise<boolean>;
}

function loadInitialDraft(): DraftKeys {
  const stored = readJSON<Partial<DraftKeys>>('session', DRAFT_KEY);
  return { ...EMPTY_DRAFT, ...(stored ?? {}) };
}

export const useSettingsStore = create<SettingsState & SettingsActions>((set, get) => ({
  draft: loadInitialDraft(),
  status: null,
  loading: false,
  applying: false,
  errorMessage: null,

  setDraftField: (field, value) => {
    const next = { ...get().draft, [field]: value };
    set({ draft: next });
    writeJSON('session', DRAFT_KEY, next);
  },

  resetDraft: () => {
    set({ draft: { ...EMPTY_DRAFT } });
    remove('session', DRAFT_KEY);
  },

  refreshStatus: async () => {
    set({ loading: true, errorMessage: null });
    try {
      const status = await getApiKeyStatus();
      set({ status });
    } catch (e) {
      set({ errorMessage: e instanceof Error ? e.message : 'Failed to fetch status' });
    } finally {
      set({ loading: false });
    }
  },

  apply: async () => {
    const { draft } = get();
    const payload: ApplyKeysPayload = {};
    if (draft.embedding_api_key.trim()) payload.embedding_api_key = draft.embedding_api_key.trim();
    if (draft.llm_api_key.trim()) payload.llm_api_key = draft.llm_api_key.trim();
    if (draft.mineru_api_key.trim()) payload.mineru_api_key = draft.mineru_api_key.trim();

    if (Object.keys(payload).length === 0) {
      set({ errorMessage: 'Enter at least one API key before applying' });
      return false;
    }

    set({ applying: true, errorMessage: null });
    try {
      const status = await applyApiKeys(payload);
      set({ status });
      return true;
    } catch (e) {
      set({ errorMessage: e instanceof Error ? e.message : 'Apply failed' });
      return false;
    } finally {
      set({ applying: false });
    }
  },

  clear: async () => {
    set({ applying: true, errorMessage: null });
    try {
      const status = await clearApiKeys();
      set({ status });
      return true;
    } catch (e) {
      set({ errorMessage: e instanceof Error ? e.message : 'Clear failed' });
      return false;
    } finally {
      set({ applying: false });
    }
  },
}));
