import type { FileTaskStatus } from '../../../types/ingest';
import styles from './stage-progress.module.css';

const STAGE_LABELS: Record<string, string> = {
  parse: 'Parse',
  filter: 'Content filter',
  chunk: 'Chunk',
  contextualize: 'Contextualize',
  embed: 'Embed',
  tag: 'Auto-tag',
  write: 'Write',
};

interface StageProgressProps {
  fileStatus: FileTaskStatus;
}

export function StageProgress({ fileStatus }: StageProgressProps) {
  const fileIconType = fileStatus.fileName.endsWith('.md') ? 'md'
    : fileStatus.fileName.endsWith('.txt') ? 'txt' : 'pdf';

  const statusLabel = fileStatus.status === 'done' ? 'SYNCED'
    : fileStatus.status === 'error' ? 'FAILED'
    : fileStatus.status === 'running' ? '处理中' : '排队中';

  const isExpanded = fileStatus.status === 'running' || fileStatus.status === 'done' || fileStatus.status === 'error';

  return (
    <div className={styles.fileProgress}>
      <div className={styles.header}>
        <div className={`${styles.fpIcon} ${styles[fileIconType]}`}>
          {fileStatus.status === 'error' ? '!' : fileIconType.toUpperCase()}
        </div>
        <div className={`${styles.fpName} ${fileStatus.status === 'error' ? styles.fpNameError : ''}`}>
          {fileStatus.fileName}
        </div>
        <div className={`${styles.fpStatus} ${styles[`fpStatus_${fileStatus.status}`]}`}>
          {statusLabel}
        </div>
      </div>

      {isExpanded && fileStatus.stages.length > 0 && (
        <ul className={styles.stageList}>
          {fileStatus.stages.map(stage => {
            const label = STAGE_LABELS[stage.stage] ?? stage.stage;
            const hasProgress = stage.status === 'running' && stage.total != null && stage.current != null;

            return (
              <li key={stage.stage} className={styles.stageItem}>
                <div className={`${styles.stageDot} ${styles[`dot_${stage.status}`]}`}>
                  {stage.status === 'done' ? '✓'
                    : stage.status === 'running' ? '⟳'
                    : stage.status === 'error' ? '✕'
                    : ''}
                </div>
                <div className={styles.stageName}>{label}</div>
                {hasProgress ? (
                  <div className={styles.progressInline}>
                    <div className={styles.progressTrack}>
                      <div
                        className={styles.progressFill}
                        style={{ width: `${Math.round((stage.current! / stage.total!) * 100)}%` }}
                      />
                    </div>
                    <span className={styles.progressText}>{stage.current} / {stage.total}</span>
                  </div>
                ) : (
                  <div className={`${styles.stageDetail} ${stage.status === 'error' ? styles.stageDetailError : ''}`}>
                    {stage.detail ?? ''}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
