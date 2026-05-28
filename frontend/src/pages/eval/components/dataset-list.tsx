import { useRef } from 'react';
import { Modal, message } from 'antd';
import { HttpError } from '../../../api/eval';
import type { TestSetSummary } from '../../../api/types';
import { useEvalStore } from '../../../stores/eval-store';
import styles from '../eval-page.module.css';

interface Props {
  testSets: TestSetSummary[];
  selectedName: string | null;
  onSelect: (name: string) => void;
  onToggleGenerate: () => void;
}

function formatDate(iso: string): string {
  // Compact MM-DD; falls back to first 10 chars on parse failure
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
  return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

export function DatasetList({ testSets, selectedName, onSelect, onToggleGenerate }: Props) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const uploadTestSet = useEvalStore((s) => s.uploadTestSet);

  const handleUploadClick = () => fileInputRef.current?.click();

  const handleFileChosen = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ''; // allow re-picking the same file
    if (!file) return;

    if (file.size > 50 * 1024 * 1024) {
      void message.error('File too large (>50MB)');
      return;
    }

    try {
      await uploadTestSet(file, false);
      void message.success(`Uploaded ${file.name}`);
    } catch (err) {
      if (err instanceof HttpError && err.status === 409) {
        Modal.confirm({
          title: 'Test set already exists',
          content: `A test set with this name already exists. Overwrite?`,
          okText: 'Overwrite',
          cancelText: 'Cancel',
          onOk: async () => {
            try {
              await uploadTestSet(file, true);
              void message.success(`Overwrote ${file.name}`);
            } catch {
              // store already surfaces errorMessage; no extra toast needed
            }
          },
        });
      }
      // Other errors are already surfaced through store.errorMessage
    }
  };

  return (
    <div className={styles.section}>
      <div className={styles.sectionHeader}>
        <span className={styles.sectionLabel}>Datasets</span>
        <div className={styles.sectionActions}>
          <button
            className={styles.btn}
            onClick={handleUploadClick}
            title="Upload existing test set JSON"
          >
            Upload
          </button>
          <button
            className={styles.btn}
            onClick={onToggleGenerate}
            title="Generate new validation set"
          >
            + New
          </button>
        </div>
      </div>

      <input
        ref={fileInputRef}
        type="file"
        accept=".json,application/json"
        onChange={handleFileChosen}
        style={{ display: 'none' }}
      />

      {testSets.length === 0 ? (
        <div className={styles.datasetEmpty}>No datasets — upload or generate one</div>
      ) : (
        <div className={styles.datasetList}>
          {testSets.map((ts) => {
            const isActive = ts.name === selectedName;
            return (
              <div
                key={ts.name}
                className={
                  isActive ? `${styles.datasetItem} ${styles.datasetItemActive}` : styles.datasetItem
                }
                onClick={() => onSelect(ts.name)}
              >
                <div className={styles.datasetName}>{ts.name}</div>
                <div className={styles.datasetMeta}>
                  {ts.entry_count}q · {formatDate(ts.created_at)}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
