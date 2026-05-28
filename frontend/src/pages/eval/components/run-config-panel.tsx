import { useState } from 'react';
import { useEvalStore, type MetricKey } from '../../../stores/eval-store';
import { TOPOLOGY_PRESETS, type TopologyPresetId } from '../topology-presets';
import { TopologyJsonEditor } from './topology-json-editor';
import styles from '../eval-page.module.css';

const METRIC_LABELS: Record<MetricKey, string> = {
  mrr: 'MRR',
  ndcg10: 'nDCG@10',
  recall10: 'Recall@10',
};

export function RunConfigPanel() {
  const runConfig = useEvalStore((s) => s.runConfig);
  const selectedTestSetName = useEvalStore((s) => s.selectedTestSetName);
  const activeTask = useEvalStore((s) => s.activeTask);
  const updateRunConfig = useEvalStore((s) => s.updateRunConfig);
  const updateWeights = useEvalStore((s) => s.updateWeights);
  const setMetricEnabled = useEvalStore((s) => s.setMetricEnabled);
  const setCustomTopology = useEvalStore((s) => s.setCustomTopology);
  const runEvaluation = useEvalStore((s) => s.runEvaluation);

  const [jsonEditorOpen, setJsonEditorOpen] = useState(false);

  const isRunning = activeTask?.kind === 'run';
  const runDisabled = isRunning || !selectedTestSetName ||
    (runConfig.topologyPreset === 'custom' && runConfig.customTopology === null);

  const handlePresetClick = (id: TopologyPresetId) => {
    updateRunConfig({ topologyPreset: id });
    if (id === 'custom') {
      setJsonEditorOpen(true);
    }
  };

  return (
    <>
      {/* Topology */}
      <div className={styles.section}>
        <div className={styles.label}>Topology</div>
        <div className={styles.chipGroup}>
          {TOPOLOGY_PRESETS.map((p) => {
            const active = runConfig.topologyPreset === p.id;
            return (
              <button
                key={p.id}
                className={active ? `${styles.chip} ${styles.chipActive}` : styles.chip}
                onClick={() => handlePresetClick(p.id)}
              >
                {p.label}
                {active && <span className={styles.chipCheck}>✓</span>}
              </button>
            );
          })}
        </div>
        {runConfig.topologyPreset === 'custom' && (
          <button
            className={styles.btn}
            style={{ marginTop: 8, width: '100%', justifyContent: 'center' }}
            onClick={() => setJsonEditorOpen(true)}
          >
            {runConfig.customTopology ? 'Edit JSON…' : 'Define JSON…'}
          </button>
        )}
      </div>

      {/* Top-K */}
      <div className={styles.inlineRow}>
        <span className={styles.label} style={{ margin: 0 }}>Top-k</span>
        <input
          className={styles.numInput}
          type="number"
          min={1}
          value={runConfig.topK}
          onChange={(e) => {
            const v = Number(e.target.value);
            if (Number.isFinite(v) && v >= 1) updateRunConfig({ topK: v });
          }}
        />
      </div>

      {/* Thresholds — only for hardcoded presets; custom JSON controls its own */}
      {runConfig.topologyPreset !== 'custom' && (
        <>
          <div className={styles.inlineRow}>
            <span className={styles.label} style={{ margin: 0 }}>recall threshold</span>
            <input
              className={styles.numInput}
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={runConfig.thresholds.vectorThreshold}
              onChange={(e) => {
                const v = Number(e.target.value);
                if (Number.isFinite(v))
                  updateRunConfig({
                    thresholds: { ...runConfig.thresholds, vectorThreshold: Math.min(1, Math.max(0, v)) },
                  });
              }}
            />
          </div>
          <div className={styles.inlineRow}>
            <span className={styles.label} style={{ margin: 0 }}>precision threshold</span>
            <input
              className={styles.numInput}
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={runConfig.thresholds.rerankerThreshold}
              onChange={(e) => {
                const v = Number(e.target.value);
                if (Number.isFinite(v))
                  updateRunConfig({
                    thresholds: { ...runConfig.thresholds, rerankerThreshold: Math.min(1, Math.max(0, v)) },
                  });
              }}
            />
          </div>
        </>
      )}

      {/* Weights */}
      <div className={styles.section}>
        <div className={styles.label}>Weights</div>
        <div className={styles.weightRow}>
          <div className={styles.weightHeader}>
            <span className={`${styles.weightLabel} ${styles.weightAlpha}`}>α retrieval</span>
            <span className={styles.weightValue}>{runConfig.weights.alpha.toFixed(2)}</span>
          </div>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={runConfig.weights.alpha}
            onChange={(e) => updateWeights({ alpha: Number(e.target.value) })}
            className={styles.weightSlider}
          />
        </div>
        <div className={styles.weightRow}>
          <div className={styles.weightHeader}>
            <span className={`${styles.weightLabel} ${styles.weightBeta}`}>β metadata</span>
            <span className={styles.weightValue}>{runConfig.weights.beta.toFixed(2)}</span>
          </div>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={runConfig.weights.beta}
            onChange={(e) => updateWeights({ beta: Number(e.target.value) })}
            className={styles.weightSlider}
          />
        </div>
        <div className={styles.weightRow}>
          <div className={styles.weightHeader}>
            <span className={`${styles.weightLabel} ${styles.weightGamma}`}>γ retention</span>
            <span className={styles.weightValue}>{runConfig.weights.gamma.toFixed(2)}</span>
          </div>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={runConfig.weights.gamma}
            onChange={(e) => updateWeights({ gamma: Number(e.target.value) })}
            className={styles.weightSlider}
          />
        </div>
      </div>

      {/* Metrics */}
      <div className={styles.section}>
        <div className={styles.label}>Metrics shown</div>
        <div className={styles.chipGroupRow}>
          {(['mrr', 'ndcg10', 'recall10'] as MetricKey[]).map((m) => {
            const active = runConfig.metrics[m];
            return (
              <button
                key={m}
                className={active ? `${styles.chip} ${styles.chipActive}` : styles.chip}
                onClick={() => setMetricEnabled(m, !active)}
              >
                {METRIC_LABELS[m]}
              </button>
            );
          })}
        </div>
      </div>

      <button
        className={styles.runBtn}
        disabled={runDisabled}
        onClick={() => void runEvaluation()}
      >
        {isRunning ? 'Running…' : '▶ Run evaluation'}
      </button>

      {isRunning && activeTask?.status?.progress && 'current_query' in activeTask.status.progress && (
        <div className={styles.progressWrap}>
          <span>
            Query {activeTask.status.progress.current_query}/{activeTask.status.progress.total_queries}
          </span>
          <div className={styles.progressBar}>
            <div
              className={styles.progressFill}
              style={{
                width: activeTask.status.progress.total_queries > 0
                  ? `${Math.min(
                      100,
                      (activeTask.status.progress.current_query /
                        activeTask.status.progress.total_queries) *
                        100,
                    )}%`
                  : '5%',
              }}
            />
          </div>
        </div>
      )}

      <TopologyJsonEditor
        open={jsonEditorOpen}
        initialSpec={runConfig.customTopology}
        onClose={() => setJsonEditorOpen(false)}
        onSave={(spec) => setCustomTopology(spec)}
      />
    </>
  );
}
