import { useState, useEffect, useMemo, useRef } from 'react';
import { message } from 'antd';
import { AppNav } from '../../components/app-nav';
import {
  fetchDocuments,
  fetchDocumentChunks,
  uploadDocument,
  deleteDocument,
  updateDocumentWeight,
} from '../../api/documents';
import type { DocumentSummary, ChunkDetail } from '../../api/documents';
import styles from './library-page.module.css';

/* ── SyncBadge ── */

function SyncBadge({ status }: { status: string }) {
  return (
    <span className={status === 'synced' ? styles.syncBadge : styles.syncBadgeDirty}>
      {status}
    </span>
  );
}

/* ── Toggle ── */

function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
}) {
  return (
    <label className={styles.toggle} onClick={() => onChange(!checked)}>
      <span className={`${styles.toggleTrack} ${checked ? styles.toggleTrackOn : ''}`}>
        <span className={`${styles.toggleThumb} ${checked ? styles.toggleThumbOn : ''}`} />
      </span>
      {label}
    </label>
  );
}

/* ── DocListItem ── */

function DocListItem({
  doc,
  active,
  onClick,
}: {
  doc: DocumentSummary;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <div
      className={`${styles.docItem} ${active ? styles.docItemActive : ''}`}
      onClick={onClick}
    >
      <div className={styles.docTitle}>{doc.filename}</div>
      <div className={styles.docMeta}>
        <span>◫ {doc.chunk_count}</span>
        <span>{doc.created_at.slice(0, 10)}</span>
        <SyncBadge status={doc.sync_status} />
      </div>
    </div>
  );
}

/* ── ChunkItem ── */

function ChunkItem({ chunk, showTags }: { chunk: ChunkDetail; showTags: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const num = chunk.chunk_index + 1;

  return (
    <div className={styles.chunkCard}>
      <div className={styles.chunkHeader}>
        <span className={styles.chunkNum}>#{num}</span>
        <span className={styles.chunkId}>{chunk.chunk_id.slice(0, 13)}</span>
        <span className={styles.flex1} />
        {showTags && chunk.tags.length > 0 && (
          <div className={styles.chunkTagsRow}>
            {chunk.tags.map(t => (
              <span key={t} className={styles.tag}>{t}</span>
            ))}
          </div>
        )}
        <button
          className={styles.deleteBtn}
          disabled
          title="Delete chunk (not yet supported)"
        >
          ×
        </button>
      </div>

      {chunk.context && (
        <div className={styles.chunkContext}>{chunk.context}</div>
      )}

      <div
        className={expanded ? styles.chunkContent : styles.chunkContentClamped}
        onClick={() => setExpanded(e => !e)}
      >
        {chunk.content}
      </div>
      {!expanded && (
        <span className={styles.showMore} onClick={() => setExpanded(true)}>
          show more
        </span>
      )}
    </div>
  );
}

/* ── DetailPane ── */

interface DetailPaneProps {
  doc: DocumentSummary;
  showChunkTags: boolean;
  onToggleChunkTags: (v: boolean) => void;
  onDelete: (docId: string) => Promise<void>;
  onWeightSaved: (docId: string, weight: number) => void;
}

function DetailPane({
  doc,
  showChunkTags,
  onToggleChunkTags,
  onDelete,
  onWeightSaved,
}: DetailPaneProps) {
  const [chunks, setChunks] = useState<ChunkDetail[]>([]);
  const [chunksLoading, setChunksLoading] = useState(true);
  const [weight, setWeight] = useState(doc.weight);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    setChunksLoading(true);
    fetchDocumentChunks(doc.doc_id)
      .then(setChunks)
      .catch(() => void message.error('Failed to load chunks'))
      .finally(() => setChunksLoading(false));
  }, [doc.doc_id]);

  async function handleWeightBlur() {
    if (weight === doc.weight) return;
    try {
      await updateDocumentWeight(doc.doc_id, weight);
      onWeightSaved(doc.doc_id, weight);
    } catch {
      void message.error('Failed to update weight');
      setWeight(doc.weight);
    }
  }

  async function handleDelete() {
    if (!confirm(`Delete "${doc.filename}"? This cannot be undone.`)) return;
    setDeleting(true);
    try {
      await onDelete(doc.doc_id);
    } catch {
      void message.error('Delete failed');
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className={styles.detailPane}>
      <div className={styles.docHeading}>{doc.filename}</div>

      <div className={styles.actionRow}>
        <button className={`${styles.actionBtn} ${styles.actionBtnDisabled}`} disabled>
          ↻ Re-index
        </button>
        <button className={`${styles.actionBtn} ${styles.actionBtnDisabled}`} disabled>
          ⟐ Re-tag
        </button>
        <button
          className={`${styles.actionBtn} ${styles.actionBtnDanger}`}
          onClick={() => void handleDelete()}
          disabled={deleting}
        >
          ✕ Delete
        </button>
      </div>

      <div className={styles.propsGrid}>
        <span className={styles.propLabel}>Chunks</span>
        <span className={styles.propValue}>
          {chunksLoading ? doc.chunk_count : chunks.length}
        </span>

        <span className={styles.propLabel}>Weight</span>
        <span>
          <input
            type="number"
            value={weight}
            onChange={e => setWeight(parseFloat(e.target.value) || 0)}
            onBlur={() => void handleWeightBlur()}
            step={0.1}
            min={0}
            max={2}
            className={styles.weightInput}
          />
        </span>

        <span className={styles.propLabel}>Status</span>
        <span className={styles.propValue}>
          <SyncBadge status={doc.sync_status} />
        </span>

        <span className={styles.propLabel}>Added</span>
        <span className={styles.propValue}>{doc.created_at.slice(0, 10)}</span>
      </div>

      <div className={styles.chunksHeader}>
        <span className={styles.chunksTitle}>
          Chunks ({chunksLoading ? '…' : chunks.length})
        </span>
        <Toggle
          checked={showChunkTags}
          onChange={onToggleChunkTags}
          label="Show tags"
        />
      </div>

      {chunksLoading ? (
        <div className={styles.loadingState}>Loading chunks…</div>
      ) : chunks.length === 0 ? (
        <div className={styles.loadingState}>No chunks</div>
      ) : (
        chunks.map(chunk => (
          <ChunkItem key={chunk.chunk_id} chunk={chunk} showTags={showChunkTags} />
        ))
      )}
    </div>
  );
}

/* ── LibraryPage ── */

export function LibraryPage() {
  const [docs, setDocs] = useState<DocumentSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [filterText, setFilterText] = useState('');
  const [showChunkTags, setShowChunkTags] = useState(true);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetchDocuments()
      .then(data => {
        setDocs(data);
        if (data.length > 0) setSelectedDocId(data[0].doc_id);
      })
      .catch(() => void message.error('Failed to load documents'))
      .finally(() => setLoading(false));
  }, []);

  const filteredDocs = useMemo(() => {
    if (!filterText.trim()) return docs;
    const q = filterText.toLowerCase();
    return docs.filter(d => d.filename.toLowerCase().includes(q));
  }, [docs, filterText]);

  const selectedDoc =
    filteredDocs.find(d => d.doc_id === selectedDocId) ?? filteredDocs[0] ?? null;

  const totalChunks = docs.reduce((s, d) => s + d.chunk_count, 0);

  function handleWeightSaved(docId: string, weight: number) {
    setDocs(prev => prev.map(d => d.doc_id === docId ? { ...d, weight } : d));
  }

  async function handleDeleteDoc(docId: string) {
    await deleteDocument(docId);
    setDocs(prev => prev.filter(d => d.doc_id !== docId));
    void message.success('Document deleted');
  }

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const resp = await uploadDocument(file);
      const newDocs = await fetchDocuments();
      setDocs(newDocs);
      setSelectedDocId(resp.doc_id);
      void message.success(`Uploaded ${file.name}`);
    } catch {
      void message.error('Upload failed');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  }

  return (
    <div className={styles.shell}>
      <AppNav />

      <div className={styles.topBar}>
        <div className={styles.filterBox}>
          <span className={styles.filterIcon}>⌕</span>
          <input
            type="text"
            value={filterText}
            onChange={e => setFilterText(e.target.value)}
            placeholder="Filter by title…"
            className={styles.filterInput}
          />
        </div>
        <span className={styles.stats}>
          {docs.length} docs · {totalChunks} chunks
        </span>
        <button
          className={styles.uploadBtn}
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
        >
          {uploading ? '…' : '↑ Upload'}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".txt,.md,.pdf"
          style={{ display: 'none' }}
          onChange={e => void handleFileChange(e)}
        />
      </div>

      <div className={styles.body}>
        <div className={styles.docList}>
          {loading ? (
            <div className={styles.loadingState}>Loading…</div>
          ) : filteredDocs.length === 0 ? (
            <div className={styles.loadingState}>
              {docs.length === 0 ? 'No documents yet' : 'No matches'}
            </div>
          ) : (
            filteredDocs.map(doc => (
              <DocListItem
                key={doc.doc_id}
                doc={doc}
                active={selectedDoc?.doc_id === doc.doc_id}
                onClick={() => setSelectedDocId(doc.doc_id)}
              />
            ))
          )}
        </div>

        <div className={styles.detailArea}>
          {selectedDoc ? (
            <DetailPane
              key={selectedDoc.doc_id}
              doc={selectedDoc}
              showChunkTags={showChunkTags}
              onToggleChunkTags={setShowChunkTags}
              onDelete={handleDeleteDoc}
              onWeightSaved={handleWeightSaved}
            />
          ) : (
            <div className={styles.emptyState}>
              {loading ? 'Loading…' : 'Upload a document to get started'}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
