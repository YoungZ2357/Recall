import type { ScoreDetail } from '../api/types';
import styles from './score-breakdown.module.css';

interface Props {
  detail: ScoreDetail;
  finalScore: number;
  weights?: { alpha: number; beta: number; gamma: number };
}

const DEFAULT_WEIGHTS = { alpha: 0.6, beta: 0.2, gamma: 0.2 };

const SIGNALS = [
  { key: 'retrieval_score' as const, label: 'retrieval', cssVar: 'var(--signal-retrieval)' },
  { key: 'metadata_score' as const, label: 'metadata', cssVar: 'var(--signal-metadata)' },
  { key: 'retention_score' as const, label: 'retention', cssVar: 'var(--signal-retention)' },
];

export function ScoreBreakdown({ detail, finalScore, weights = DEFAULT_WEIGHTS }: Props) {
  const { alpha, beta, gamma } = weights;

  return (
    <div className={styles.root}>
      {SIGNALS.map(({ key, label, cssVar }) => {
        const value = detail[key];
        return (
          <div key={key} className={styles.row}>
            <span className={styles.label}>{label}</span>
            <div className={styles.track}>
              <div
                className={styles.fill}
                style={{ width: `${value * 100}%`, background: cssVar }}
              />
            </div>
            <span className={styles.value}>{value.toFixed(2)}</span>
          </div>
        );
      })}
      <div className={styles.formula}>
        {alpha}×{detail.retrieval_score.toFixed(2)} + {beta}×{detail.metadata_score.toFixed(2)} +{' '}
        {gamma}×{detail.retention_score.toFixed(2)} = {finalScore.toFixed(3)}
      </div>
    </div>
  );
}
