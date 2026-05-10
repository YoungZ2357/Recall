import type { UploadFile } from '../../../types/ingest';
import styles from './file-item.module.css';

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

interface FileItemProps {
  file: UploadFile;
  onRemove?: (id: string) => void;
}

export function FileItem({ file, onRemove }: FileItemProps) {
  return (
    <div className={styles.item}>
      <div className={`${styles.icon} ${styles[file.type]}`}>
        {file.type.toUpperCase()}
      </div>
      <div className={styles.info}>
        <div className={styles.name}>{file.name}</div>
        <div className={styles.meta}>{formatSize(file.size)}</div>
      </div>
      {onRemove && (
        <button className={styles.remove} onClick={() => onRemove(file.id)} title="移除">
          ×
        </button>
      )}
    </div>
  );
}
