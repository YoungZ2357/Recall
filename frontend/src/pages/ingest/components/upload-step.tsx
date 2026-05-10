import { useRef, useState } from 'react';
import type { UploadFile } from '../../../types/ingest';
import { FileItem } from './file-item';
import styles from './upload-step.module.css';

const ACCEPTED_TYPES = ['.pdf', '.txt', '.md'];
const ACCEPTED_MIME = ['application/pdf', 'text/plain', 'text/markdown'];

function isAccepted(file: File): boolean {
  const ext = '.' + (file.name.split('.').pop()?.toLowerCase() ?? '');
  return ACCEPTED_TYPES.includes(ext) || ACCEPTED_MIME.some(m => file.type.startsWith(m));
}

function formatTotalSize(files: UploadFile[]): string {
  const bytes = files.reduce((sum, f) => sum + f.size, 0);
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

interface UploadStepProps {
  files: UploadFile[];
  onAddFiles: (files: File[]) => void;
  onRemoveFile: (id: string) => void;
  onNext: () => void;
}

export function UploadStep({ files, onAddFiles, onRemoveFile, onNext }: UploadStepProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  function handleFiles(fileList: FileList | null) {
    if (!fileList) return;
    const accepted = Array.from(fileList).filter(isAccepted);
    if (accepted.length > 0) onAddFiles(accepted);
  }

  function onDragOver(e: React.DragEvent) {
    e.preventDefault();
    setDragging(true);
  }

  function onDragLeave() {
    setDragging(false);
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragging(false);
    handleFiles(e.dataTransfer.files);
  }

  return (
    <>
      <div className={styles.card}>
        <div className={styles.cardBody}>
          <div
            className={`${styles.uploadZone} ${dragging ? styles.uploadZoneDragging : ''}`}
            onClick={() => inputRef.current?.click()}
            onDragOver={onDragOver}
            onDragLeave={onDragLeave}
            onDrop={onDrop}
          >
            <div className={styles.uploadIcon}>📄</div>
            <div className={styles.uploadTitle}>拖拽文件到此处，或点击选择</div>
            <div className={styles.uploadHint}>支持单文件或批量上传，单文件最大 50 MB</div>
            <div className={styles.formats}>
              {ACCEPTED_TYPES.map(t => (
                <span key={t} className={styles.formatBadge}>{t}</span>
              ))}
            </div>
          </div>

          <input
            ref={inputRef}
            type="file"
            multiple
            accept={ACCEPTED_TYPES.join(',')}
            style={{ display: 'none' }}
            onChange={e => handleFiles(e.target.files)}
          />

          {files.length > 0 && (
            <div className={styles.fileList}>
              {files.map(f => (
                <FileItem key={f.id} file={f} onRemove={onRemoveFile} />
              ))}
            </div>
          )}
        </div>
      </div>

      <div className={styles.actions}>
        <span className={styles.hint}>
          {files.length > 0
            ? `${files.length} 个文件已选择 · ${formatTotalSize(files)}`
            : '尚未选择文件'}
        </span>
        <button
          className={`${styles.btn} ${styles.btnPrimary}`}
          disabled={files.length === 0}
          onClick={onNext}
        >
          下一步：配置管道 →
        </button>
      </div>
    </>
  );
}
