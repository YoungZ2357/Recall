import styles from './config-panel.module.css';

export interface SearchConfig {
  topo: 'vector_only' | 'bm25_only' | 'rrf' | 'custom';
  customJson: string;
  rewrite: 'passthrough' | 'HyDE' | 'RAG-Fusion';
  topK: number;
  alpha: number;
  beta: number;
  gamma: number;
  retention: 'prefer_recent' | 'awaken_forgotten';
}

export const DEFAULT_CONFIG: SearchConfig = {
  topo: 'rrf',
  customJson: '',
  rewrite: 'passthrough',
  topK: 10,
  alpha: 0.6,
  beta: 0.2,
  gamma: 0.2,
  retention: 'prefer_recent',
};

const CUSTOM_JSON_PLACEHOLDER = `{
  "nodes": [
    {"id": "query_in", "type": "input"},
    {"id": "vector_search", "type": "searcher"},
    {"id": "rrf_merge", "type": "fusion"},
    {"id": "reranker", "type": "reranker"}
  ],
  "edges": [
    ["query_in", "vector_search"],
    ["vector_search", "rrf_merge"],
    ["rrf_merge", "reranker"]
  ]
}`;

interface ConfigPanelProps {
  open: boolean;
  onClose: () => void;
  config: SearchConfig;
  onChange: (patch: Partial<SearchConfig>) => void;
}

const TOPO_OPTIONS: { key: SearchConfig['topo']; label: string }[] = [
  { key: 'vector_only', label: 'Vector only' },
  { key: 'bm25_only',   label: 'BM25 only'   },
  { key: 'rrf',         label: 'Vector + BM25 (RRF)' },
  { key: 'custom',      label: 'Custom JSON'  },
];

const REWRITE_OPTIONS: SearchConfig['rewrite'][] = ['passthrough', 'HyDE', 'RAG-Fusion'];
const RETENTION_OPTIONS: { value: SearchConfig['retention']; label: string }[] = [
  { value: 'prefer_recent',    label: 'prefer_recent'    },
  { value: 'awaken_forgotten', label: 'awaken_forgotten' },
];

const WEIGHT_SIGNALS = [
  { key: 'alpha' as const, label: 'α retrieval', color: 'var(--signal-retrieval)' },
  { key: 'beta'  as const, label: 'β metadata',  color: 'var(--signal-metadata)'  },
  { key: 'gamma' as const, label: 'γ retention',  color: 'var(--signal-retention)' },
];

function validateJson(json: string): string {
  if (!json.trim()) return '';
  try {
    const parsed = JSON.parse(json) as Record<string, unknown>;
    if (!parsed.nodes || !parsed.edges) return 'Missing required fields: nodes, edges';
    return '';
  } catch {
    return 'Invalid JSON';
  }
}

export function ConfigPanel({ open, onClose, config, onChange }: ConfigPanelProps) {
  if (!open) return null;

  const jsonError = validateJson(config.customJson);
  const jsonValid = !jsonError && config.customJson.trim().length > 0;

  return (
    <div className={styles.panel}>
      <div className={styles.panelHeader}>
        <span className={styles.panelTitle}>Pipeline config</span>
        <span className={styles.closeBtn} onClick={onClose}>×</span>
      </div>

      {/* Topology */}
      <div className={styles.sectionLabel}>Topology</div>
      <div className={styles.pillGroup}>
        {TOPO_OPTIONS.map(opt => (
          <button
            key={opt.key}
            className={config.topo === opt.key ? styles.pillActive : styles.pill}
            onClick={() => onChange({ topo: opt.key })}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {config.topo === 'custom' && (
        <div className={styles.jsonSection}>
          <textarea
            value={config.customJson}
            onChange={e => onChange({ customJson: e.target.value })}
            placeholder={CUSTOM_JSON_PLACEHOLDER}
            spellCheck={false}
            className={jsonError ? styles.jsonTextareaError : styles.jsonTextarea}
          />
          {jsonError && <div className={styles.jsonErrorMsg}>{jsonError}</div>}
          {jsonValid && <div className={styles.jsonOkMsg}>Valid graph definition</div>}
        </div>
      )}
      {config.topo !== 'custom' && <div className={styles.sectionGap} />}

      {/* Query rewrite */}
      <div className={styles.sectionLabel}>Query rewrite</div>
      <div className={styles.pillGroup}>
        {REWRITE_OPTIONS.map(opt => (
          <button
            key={opt}
            className={config.rewrite === opt ? styles.pillActive : styles.pill}
            onClick={() => onChange({ rewrite: opt })}
          >
            {opt}
          </button>
        ))}
      </div>
      <div className={styles.sectionGap} />

      {/* Retrieval */}
      <div className={styles.sectionLabel}>Retrieval</div>
      <div className={styles.inlineRow}>
        <span className={styles.inlineLabel}>top-k</span>
        <input
          type="number"
          value={config.topK}
          min={1}
          max={50}
          onChange={e => onChange({ topK: Math.max(1, Number(e.target.value)) })}
          className={styles.numInput}
        />
      </div>
      <div className={styles.sectionGap} />

      {/* Rerank weights */}
      <div className={styles.sectionLabel}>Rerank weights</div>
      {WEIGHT_SIGNALS.map(s => (
        <div key={s.key} className={styles.sliderRow}>
          <span className={styles.sliderLabel} style={{ color: s.color }}>{s.label}</span>
          <input
            type="range"
            min="0"
            max="1"
            step="0.05"
            value={config[s.key]}
            onChange={e => onChange({ [s.key]: parseFloat(e.target.value) })}
            className={styles.slider}
            style={{ accentColor: s.color }}
          />
          <span className={styles.sliderValue}>{config[s.key].toFixed(2)}</span>
        </div>
      ))}
      <div className={styles.sectionGap} />

      {/* Retention */}
      <div className={styles.sectionLabel}>Retention</div>
      <div className={styles.pillGroup}>
        {RETENTION_OPTIONS.map(opt => (
          <button
            key={opt.value}
            className={config.retention === opt.value ? styles.pillActive : styles.pill}
            onClick={() => onChange({ retention: opt.value })}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  );
}
