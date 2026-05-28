import { usePipelineStore } from '../../stores/pipeline-store';
import type { PipelineNodeData } from '../../stores/pipeline-store';
import styles from './node-inspector.module.css';

// ---------------------------------------------------------------------------
// Shared field helpers
// ---------------------------------------------------------------------------

interface SliderFieldProps {
  label: string;
  value: number;
  min?: number;
  max?: number;
  step?: number;
  color?: string;
  disabled?: boolean;
  onChange: (v: number) => void;
}

function SliderField({
  label,
  value,
  min = 0,
  max = 1,
  step = 0.05,
  color,
  disabled,
  onChange,
}: SliderFieldProps) {
  return (
    <div className={styles.field}>
      <div className={styles.fieldLabel}>{label}</div>
      <div className={styles.sliderRow}>
        <input
          type="range"
          className={styles.slider}
          style={color ? ({ '--slider-color': color } as React.CSSProperties) : undefined}
          min={min}
          max={max}
          step={step}
          value={value}
          disabled={disabled}
          onChange={e => onChange(parseFloat(e.target.value))}
        />
        <span className={styles.sliderValue}>{value.toFixed(2)}</span>
      </div>
    </div>
  );
}

interface NumberFieldProps {
  label: string;
  value: number | string;
  disabled?: boolean;
  onChange: (v: string) => void;
}

function NumberField({ label, value, disabled, onChange }: NumberFieldProps) {
  return (
    <div className={styles.field}>
      <div className={styles.fieldLabel}>{label}</div>
      <input
        type="text"
        className={styles.numInput}
        value={value}
        disabled={disabled}
        onChange={e => onChange(e.target.value)}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Per-node-type form components
// ---------------------------------------------------------------------------

interface FormProps {
  config: Record<string, unknown>;
  nodeId: string;
  disabled?: boolean;
  update: (id: string, patch: Record<string, unknown>) => void;
}

function VectorSearcherForm({ config, nodeId, disabled, update }: FormProps) {
  return (
    <div className={styles.formGrid}>
      <NumberField
        label="Score threshold"
        value={(config.score_threshold as number | undefined) ?? 0.2}
        disabled={disabled}
        onChange={v => update(nodeId, { score_threshold: parseFloat(v) || 0 })}
      />
      <NumberField
        label="Top-k"
        value={(config.top_k as number | undefined) ?? 10}
        disabled={disabled}
        onChange={v => update(nodeId, { top_k: parseInt(v, 10) || 10 })}
      />
      <div className={styles.field}>
        <div className={styles.fieldLabel}>Collection</div>
        <input
          type="text"
          className={styles.numInput}
          style={{ width: '100%' }}
          value={(config.collection_name as string | undefined) ?? 'recall'}
          disabled={disabled}
          onChange={e => update(nodeId, { collection_name: e.target.value })}
        />
      </div>
    </div>
  );
}

function BM25Form({ config, nodeId, disabled, update }: FormProps) {
  return (
    <div className={styles.formGrid}>
      <NumberField
        label="Score threshold"
        value={(config.score_threshold as number | undefined) ?? 0.2}
        disabled={disabled}
        onChange={v => update(nodeId, { score_threshold: parseFloat(v) || 0 })}
      />
      <NumberField
        label="Top-k"
        value={(config.top_k as number | undefined) ?? 10}
        disabled={disabled}
        onChange={v => update(nodeId, { top_k: parseInt(v, 10) || 10 })}
      />
      <NumberField
        label="Recall multiplier"
        value={(config.recall_multiplier as number | undefined) ?? 2}
        disabled={disabled}
        onChange={v => update(nodeId, { recall_multiplier: parseInt(v, 10) || 2 })}
      />
    </div>
  );
}

function RRFMergerForm({ config, nodeId, disabled, update }: FormProps) {
  return (
    <div className={styles.formGrid}>
      <NumberField
        label="k (smoothing)"
        value={(config.k as number | undefined) ?? 60}
        disabled={disabled}
        onChange={v => update(nodeId, { k: parseInt(v, 10) || 60 })}
      />
    </div>
  );
}

function RerankerForm({ config, nodeId, disabled, update }: FormProps) {
  const alpha = (config.alpha as number | undefined) ?? 0.85;
  const beta = (config.beta as number | undefined) ?? 0.15;
  const gamma = (config.gamma as number | undefined) ?? 0.0;
  const threshold = (config.score_threshold as number | undefined) ?? 0.60;
  const mode = (config.retention_mode as string | undefined) ?? 'prefer_recent';

  return (
    <div className={styles.rerankerGrid}>
      <SliderField
        label="α retrieval"
        value={alpha}
        color="var(--signal-retrieval)"
        disabled={disabled}
        onChange={v => update(nodeId, { alpha: v })}
      />
      <SliderField
        label="β metadata"
        value={beta}
        color="var(--signal-metadata)"
        disabled={disabled}
        onChange={v => update(nodeId, { beta: v })}
      />
      <SliderField
        label="γ retention"
        value={gamma}
        color="var(--signal-retention)"
        disabled={disabled}
        onChange={v => update(nodeId, { gamma: v })}
      />
      <NumberField
        label="Score threshold"
        value={threshold}
        disabled={disabled}
        onChange={v => update(nodeId, { score_threshold: parseFloat(v) || 0 })}
      />
      <div className={styles.field}>
        <div className={styles.fieldLabel}>Retention mode</div>
        <div className={styles.togglePair}>
          <button
            className={mode === 'prefer_recent' ? styles.toggleBtnActive : styles.toggleBtn}
            disabled={disabled}
            onClick={() => update(nodeId, { retention_mode: 'prefer_recent' })}
          >
            recent
          </button>
          <button
            className={mode === 'awaken_forgotten' ? styles.toggleBtnActive : styles.toggleBtn}
            disabled={disabled}
            onClick={() => update(nodeId, { retention_mode: 'awaken_forgotten' })}
          >
            awaken
          </button>
        </div>
      </div>
    </div>
  );
}

function UnavailableForm() {
  return (
    <p className={styles.unavailableMsg}>This operator is not yet implemented.</p>
  );
}

// ---------------------------------------------------------------------------
// Role dot colour
// ---------------------------------------------------------------------------

function RoleDot({ role }: { role: PipelineNodeData['node_role'] }) {
  const colors: Record<PipelineNodeData['node_role'], string> = {
    SOURCE: 'var(--badge-vec-fg)',
    MERGE: 'var(--warning-fg)',
    TRANSFORM: 'var(--accent)',
  };
  return (
    <span
      className={styles.dot}
      style={{ background: colors[role] }}
    />
  );
}

// ---------------------------------------------------------------------------
// NodeInspector
// ---------------------------------------------------------------------------

export function NodeInspector({ readOnly = false }: { readOnly?: boolean }) {
  const selectedNodeId = usePipelineStore(s => s.selectedNodeId);
  const rfNodes = usePipelineStore(s => s.rfNodes);
  const updateNodeConfig = usePipelineStore(s => s.updateNodeConfig);
  const deleteSelectedNode = usePipelineStore(s => s.deleteSelectedNode);
  const selectNode = usePipelineStore(s => s.selectNode);

  const node = rfNodes.find(n => n.id === selectedNodeId);
  if (!node) return null;

  const { data } = node;

  let formContent: React.ReactNode;
  if (!data.available) {
    formContent = <UnavailableForm />;
  } else {
    switch (data.node_type) {
      case 'VectorSearcher':
        formContent = (
          <VectorSearcherForm
            config={data.config}
            nodeId={node.id}
            disabled={readOnly}
            update={updateNodeConfig}
          />
        );
        break;
      case 'BM25Searcher':
      case 'ContextualBM25Searcher':
        formContent = (
          <BM25Form
            config={data.config}
            nodeId={node.id}
            disabled={readOnly}
            update={updateNodeConfig}
          />
        );
        break;
      case 'RRFMerger':
        formContent = (
          <RRFMergerForm
            config={data.config}
            nodeId={node.id}
            disabled={readOnly}
            update={updateNodeConfig}
          />
        );
        break;
      case 'Reranker':
        formContent = (
          <RerankerForm
            config={data.config}
            nodeId={node.id}
            disabled={readOnly}
            update={updateNodeConfig}
          />
        );
        break;
      default:
        formContent = <UnavailableForm />;
    }
  }

  return (
    <div className={styles.inspector}>
      {/* ── header ── */}
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <RoleDot role={data.node_role} />
          <span className={styles.nodeName}>{data.label}</span>
          <span className={styles.nodeMeta}>
            {node.id} · {data.node_role.toLowerCase()}
          </span>
        </div>
        <div className={styles.headerActions}>
          {!readOnly && (
            <button className={styles.deleteBtn} onClick={deleteSelectedNode}>
              Delete
            </button>
          )}
          <button className={styles.closeBtn} onClick={() => selectNode(null)}>
            ×
          </button>
        </div>
      </div>

      {/* ── config form ── */}
      <div className={styles.body}>{formContent}</div>
    </div>
  );
}
