import { useState } from 'react';
import { Switch } from 'antd';
import type { SearchResultItem } from '../api/types';
import styles from './chunk-card.module.css';

interface ChunkCardProps {
  item: SearchResultItem;
  rank: number;
  weights?: { alpha: number; beta: number; gamma: number };
}

const DEFAULT_CARD_WEIGHTS = { alpha: 0.85, beta: 0.15, gamma: 0.0 };

const SCORE_SIGNALS = [
  { key: 'retrieval_score' as const, cssVar: 'var(--signal-retrieval)' },
  { key: 'metadata_score'  as const, cssVar: 'var(--signal-metadata)'  },
  { key: 'retention_score' as const, cssVar: 'var(--signal-retention)'  },
];

const WEIGHT_MAP_KEYS = {
  retrieval_score: 'alpha',
  metadata_score:  'beta',
  retention_score: 'gamma',
} as const;

const LABEL_MAP = {
  retrieval_score: { abs: 'retrieval', eff: 'retrieval×α' },
  metadata_score:  { abs: 'metadata',  eff: 'metadata×β'  },
  retention_score: { abs: 'retention', eff: 'retention×γ'  },
};

function docTitle(filename: string): string {
  return filename.replace(/\.[^.]+$/, '');
}

export function ChunkCard({ item, rank, weights }: ChunkCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [showAbsolute, setShowAbsolute] = useState(false);

  const scores = item.score_detail;
  const total = item.final_score;
  const w = weights ?? DEFAULT_CARD_WEIGHTS;

  // Compute per-signal display values and labels based on current mode
  const displaySignals = SCORE_SIGNALS.map(s => {
    const raw = scores[s.key];
    const weight = w[WEIGHT_MAP_KEYS[s.key]];
    return {
      ...s,
      label: showAbsolute ? LABEL_MAP[s.key].abs : LABEL_MAP[s.key].eff,
      value: showAbsolute ? raw : weight * raw,
    };
  });

  // Sum used for proportional flex in the stacked bar
  const sum = Math.max(displaySignals.reduce((acc, s) => acc + s.value, 0), 0.001);

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

      {/* score bar row — reflects current mode */}
      <div className={styles.scoreRow}>
        <span className={styles.scoreTotal}>{total.toFixed(2)}</span>
        <div className={styles.scoreBar}>
          {displaySignals.map(s => (
            <div
              key={s.key}
              className={styles.scoreSegment}
              style={{ flex: s.value / sum, background: s.cssVar }}
            />
          ))}
        </div>
      </div>

      {/* expanded detail */}
      {expanded && (
        <div className={styles.detail}>
          {/* toggle: absolute vs effective scores */}
          <div className={styles.toggleRow}>
            <Switch size="small" checked={showAbsolute} onChange={setShowAbsolute} />
            <span className={styles.toggleLabel}>绝对分数</span>
          </div>

          {displaySignals.map(s => (
            <div key={s.key} className={styles.detailRow}>
              <span className={styles.detailLabel} style={{ color: s.cssVar }}>{s.label}</span>
              <div className={styles.detailTrack}>
                <div
                  className={styles.detailFill}
                  style={{ width: `${s.value * 100}%`, background: s.cssVar }}
                />
              </div>
              <span className={styles.detailValue}>{s.value.toFixed(2)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
