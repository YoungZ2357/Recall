import { Popconfirm, message } from 'antd';
import type { ReportSummary } from '../../../api/types';
import { useEvalStore, type MetricKey } from '../../../stores/eval-store';
import styles from '../eval-page.module.css';

// Backend metric keys → UI labels
const METRIC_BACKEND_KEY: Record<MetricKey, string> = {
  mrr: 'RR(rel=2)',
  ndcg10: 'nDCG@10',
  recall10: 'R(rel=2)@10',
};

const METRIC_LABEL: Record<MetricKey, string> = {
  mrr: 'MRR',
  ndcg10: 'nDCG@10',
  recall10: 'Recall@10',
};

interface Props {
  selectedTestSetName: string | null;
}

function formatDelta(curr: number, prev: number | null): { text: string; cls: string } {
  if (prev === null) return { text: '—', cls: styles.deltaNeutral };
  const diff = curr - prev;
  if (Math.abs(diff) < 0.0001) return { text: '±0.0000', cls: styles.deltaNeutral };
  const sign = diff > 0 ? '+' : '';
  return {
    text: `${sign}${diff.toFixed(4)}`,
    cls: diff > 0 ? styles.deltaPositive : styles.deltaNegative,
  };
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
  return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function formatWeights(w: Record<string, number> | null): string {
  if (!w) return '—';
  return `${(w.alpha ?? 0).toFixed(2)}/${(w.beta ?? 0).toFixed(2)}/${(w.gamma ?? 0).toFixed(2)}`;
}

function shortTopologyName(name: string | null): string {
  if (!name) return 'default';
  switch (name) {
    case 'vector': return 'Vector';
    case 'bm25': return 'BM25';
    case 'v_b_rrf': return 'V+B';
    case 'custom': return 'Custom';
    default: return name;
  }
}

export function ResultsPanel({ selectedTestSetName }: Props) {
  const reports = useEvalStore((s) => s.reports);
  const metrics = useEvalStore((s) => s.runConfig.metrics);
  const deleteReport = useEvalStore((s) => s.deleteReport);

  // Filter to the selected test set; older reports without run_config fall
  // back to filename-prefix matching so legacy data still surfaces.
  const datasetReports = selectedTestSetName
    ? reports.filter(
        (r) =>
          r.test_set_name === selectedTestSetName ||
          (!r.test_set_name && r.name.startsWith(`${selectedTestSetName}__`)) ||
          (!r.test_set_name && r.name === selectedTestSetName),
      )
    : [];

  // Sort by created_at descending — newest first
  const sorted = [...datasetReports].sort((a, b) =>
    b.created_at.localeCompare(a.created_at),
  );

  const enabledMetrics = (Object.keys(metrics) as MetricKey[]).filter((m) => metrics[m]);

  const latest = sorted[0];
  const previous = sorted[1] ?? null;

  const handleDelete = (name: string) => {
    void deleteReport(name).then(() => {
      void message.success('Report deleted');
    });
  };

  return (
    <>
      <div className={styles.resultsHeader}>
        <div className={styles.resultsTitle}>
          <span className={styles.sectionLabel}>Results</span>
          <span className={styles.resultsHint}>
            {selectedTestSetName
              ? `on ${selectedTestSetName} · ${sorted.length} run${sorted.length === 1 ? '' : 's'}`
              : 'no dataset selected'}
          </span>
        </div>
      </div>

      {/* Metric cards from latest run */}
      <div className={styles.metricCards}>
        {enabledMetrics.length === 0 && (
          <div
            className={styles.metricCard}
            style={{ gridColumn: '1 / -1', textAlign: 'center', color: 'var(--text-tertiary)' }}
          >
            No metrics selected
          </div>
        )}
        {enabledMetrics.map((m) => {
          const key = METRIC_BACKEND_KEY[m];
          const curr = latest?.aggregate_metrics[key];
          const prev = previous?.aggregate_metrics[key] ?? null;
          const delta = curr !== undefined ? formatDelta(curr, prev) : null;
          return (
            <div key={m} className={styles.metricCard}>
              <div className={styles.metricLabel}>{METRIC_LABEL[m]}</div>
              <div className={styles.metricValue}>
                {curr !== undefined ? curr.toFixed(4) : '—'}
              </div>
              {delta && <div className={`${styles.metricDelta} ${delta.cls}`}>{delta.text}</div>}
            </div>
          );
        })}
      </div>

      {/* Runs table */}
      {sorted.length === 0 ? (
        <div className={styles.runsEmpty}>
          {selectedTestSetName ? 'No runs yet. Configure and click Run evaluation.' : '—'}
        </div>
      ) : (
        <table className={styles.runsTable}>
          <thead>
            <tr>
              <th style={{ width: 22 }}>#</th>
              <th style={{ width: 46 }}>Date</th>
              <th>Topology</th>
              <th>α/β/γ</th>
              {enabledMetrics.map((m) => (
                <th key={m} style={{ textAlign: 'right' }}>{METRIC_LABEL[m]}</th>
              ))}
              <th style={{ width: 30 }}></th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((r: ReportSummary, idx) => (
              <tr key={r.name}>
                <td className={styles.num}>{sorted.length - idx}</td>
                <td className={styles.mono}>{formatDate(r.created_at)}</td>
                <td>{shortTopologyName(r.topology_name)}</td>
                <td className={styles.mono}>{formatWeights(r.weights)}</td>
                {enabledMetrics.map((m) => {
                  const val = r.aggregate_metrics[METRIC_BACKEND_KEY[m]];
                  return (
                    <td key={m} className={styles.num}>
                      {val !== undefined ? val.toFixed(4) : '—'}
                    </td>
                  );
                })}
                <td>
                  <Popconfirm
                    title="Delete this run?"
                    onConfirm={() => handleDelete(r.name)}
                    okText="Delete"
                    cancelText="Cancel"
                  >
                    <button
                      title="Delete"
                      style={{
                        border: 'none',
                        background: 'transparent',
                        cursor: 'pointer',
                        color: 'var(--text-tertiary)',
                        fontSize: 12,
                      }}
                    >
                      ×
                    </button>
                  </Popconfirm>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
