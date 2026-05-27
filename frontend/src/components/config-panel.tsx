import styles from './config-panel.module.css';
import type { SearchConfig } from './config-panel-config';

const CUSTOM_JSON_PLACEHOLDER = `{
  "nodes": [
    {"node_id": "vec",    "node_type": "VectorSearcher", "config": {}},
    {"node_id": "bm25",   "node_type": "BM25Searcher",   "config": {}},
    {"node_id": "merge",  "node_type": "RRFMerger",      "config": {}},
    {"node_id": "rerank", "node_type": "Reranker",       "config": {}}
  ],
  "edges": [
    {"from_node": "vec",    "to_node": "merge"},
    {"from_node": "bm25",   "to_node": "merge"},
    {"from_node": "merge",  "to_node": "rerank"}
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
  let parsed: unknown;
  try {
    parsed = JSON.parse(json);
  } catch {
    return 'Invalid JSON';
  }
  if (!parsed || typeof parsed !== 'object') return 'Root must be an object';

  const root = parsed as Record<string, unknown>;
  if (!Array.isArray(root.nodes)) return 'Missing or invalid field: nodes (array)';
  if (!Array.isArray(root.edges)) return 'Missing or invalid field: edges (array)';

  for (let i = 0; i < root.nodes.length; i++) {
    const n = root.nodes[i] as Record<string, unknown> | null;
    if (!n || typeof n !== 'object') return `nodes[${i}] must be an object`;
    if (typeof n.node_id !== 'string')   return `nodes[${i}].node_id must be a string`;
    if (typeof n.node_type !== 'string') return `nodes[${i}].node_type must be a string`;
    if (!n.config || typeof n.config !== 'object') return `nodes[${i}].config must be an object`;
  }
  for (let i = 0; i < root.edges.length; i++) {
    const e = root.edges[i] as Record<string, unknown> | null;
    if (!e || typeof e !== 'object') return `edges[${i}] must be an object`;
    if (typeof e.from_node !== 'string') return `edges[${i}].from_node must be a string`;
    if (typeof e.to_node !== 'string')   return `edges[${i}].to_node must be a string`;
  }
  return '';
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
