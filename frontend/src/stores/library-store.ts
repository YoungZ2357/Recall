import { create } from 'zustand';
import {
  fetchDocuments,
  uploadDocument,
  deleteDocument,
  updateDocumentWeight,
  type DocumentSummary,
  type UploadResponse,
} from '../api/documents';

interface LibraryState {
  docs: DocumentSummary[];
  loaded: boolean;
  loading: boolean;
  selectedDocId: string | null;
  filterText: string;
  showChunkTags: boolean;
  uploading: boolean;
}

interface LibraryActions {
  loadIfNeeded: () => Promise<void>;
  refresh: () => Promise<void>;
  setSelected: (docId: string | null) => void;
  setFilter: (text: string) => void;
  setShowChunkTags: (v: boolean) => void;
  removeDoc: (docId: string) => Promise<void>;
  patchWeight: (docId: string, weight: number) => Promise<void>;
  uploadFile: (file: File) => Promise<UploadResponse>;
}

let inflightLoad: Promise<void> | null = null;

export const useLibraryStore = create<LibraryState & LibraryActions>((set, get) => ({
  docs: [],
  loaded: false,
  loading: false,
  selectedDocId: null,
  filterText: '',
  showChunkTags: true,
  uploading: false,

  loadIfNeeded: async () => {
    if (get().loaded || get().loading) return inflightLoad ?? Promise.resolve();
    return get().refresh();
  },

  refresh: async () => {
    if (inflightLoad) return inflightLoad;
    set({ loading: true });
    inflightLoad = (async () => {
      try {
        const data = await fetchDocuments();
        set((s) => ({
          docs: data,
          loaded: true,
          selectedDocId:
            s.selectedDocId && data.some((d) => d.doc_id === s.selectedDocId)
              ? s.selectedDocId
              : data[0]?.doc_id ?? null,
        }));
      } finally {
        set({ loading: false });
        inflightLoad = null;
      }
    })();
    return inflightLoad;
  },

  setSelected: (docId) => set({ selectedDocId: docId }),
  setFilter: (text) => set({ filterText: text }),
  setShowChunkTags: (v) => set({ showChunkTags: v }),

  removeDoc: async (docId) => {
    await deleteDocument(docId);
    set((s) => {
      const docs = s.docs.filter((d) => d.doc_id !== docId);
      const selectedDocId =
        s.selectedDocId === docId ? (docs[0]?.doc_id ?? null) : s.selectedDocId;
      return { docs, selectedDocId };
    });
  },

  patchWeight: async (docId, weight) => {
    await updateDocumentWeight(docId, weight);
    set((s) => ({
      docs: s.docs.map((d) => (d.doc_id === docId ? { ...d, weight } : d)),
    }));
  },

  uploadFile: async (file) => {
    set({ uploading: true });
    try {
      const resp = await uploadDocument(file);
      await get().refresh();
      set({ selectedDocId: resp.doc_id });
      return resp;
    } finally {
      set({ uploading: false });
    }
  },
}));
