import { useState } from 'react';
import type { SearchResultItem } from '../api/types';
import styles from './chunk-card.module.css';

interface ChunkCardProps {
  item: SearchResultItem;
  rank: number;
}

const SCORE_SIGNALS = [
  { key: 'retrieval_score' as const, label: 'retrieval', cssVar: 'var(--signal-retrieval)' },
  { key: 'metadata_score'  as const, label: 'metadata',  cssVar: 'var(--signal-metadata)'  },
  { key: 'retention_score' as const, label: 'retention', cssVar: 'var(--signal-retention)'  },
];

function docTitle(filename: string): string {
  return filename.replace(/\.[^.]+$/, '');
}

export function ChunkCard({ item, rank }: ChunkCardProps) {
  const [expanded, setExpanded] = useState(false);

  const scores = item.score_detail;
  const total = item.final_score;
  const sum = Math.max(scores.retrieval_score + scores.metadata_score + scores.retention_score, 0.001);

  return (
    <div className={styles.card}>
      {/* header */}
      <div className={styles.header}>
        <span className={styles.title}>{docTitle(item.filename)}</span>
        <span className={styles.num}>#{rank}</span>
      </div>

      {/* tags */}
      {item.tags.length > 0 && (
        <div className={styles.tagRow}>
          {item.tags.map(t => (
            <span key={t} className={styles.tag}>{t}</span>
          ))}
        </div>
      )}

      {/* content — click to toggle */}
      <div
        className={expanded ? styles.contentFull : styles.contentPreview}
        onClick={() => setExpanded(e => !e)}
      >
        {item.content}
      </div>

      {/* score bar row */}
      <div className={styles.scoreRow}>
        <span className={styles.scoreTotal}>{total.toFixed(2)}</span>
        <div className={styles.scoreBar}>
          {SCORE_SIGNALS.map(s => {
            const v = scores[s.key];
            return (
              <div
                key={s.key}
                className={styles.scoreSegment}
                style={{ flex: v / sum, background: s.cssVar }}
              />
            );
          })}
        </div>
      </div>

      {/* expanded detail */}
      {expanded && (
        <div className={styles.detail}>
          {SCORE_SIGNALS.map(s => {
            const v = scores[s.key];
            return (
              <div key={s.key} className={styles.detailRow}>
                <span className={styles.detailLabel} style={{ color: s.cssVar }}>{s.label}</span>
                <div className={styles.detailTrack}>
                  <div
                    className={styles.detailFill}
                    style={{ width: `${(v / total) * 100}%`, background: s.cssVar }}
                  />
                </div>
                <span className={styles.detailValue}>{v.toFixed(2)}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
