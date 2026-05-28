import { useState } from 'react';
import { Button, Switch, message } from 'antd';
import { useEvalStore } from '../../../stores/eval-store';
import styles from '../eval-page.module.css';

interface Props {
  open: boolean;
}

interface GenForm {
  name: string;
  num_chunks: number;
  queries_per_chunk: number;
  pool_size: number;
  with_context: boolean;
  skip_grading: boolean;
}

const DEFAULTS: GenForm = {
  name: '',
  num_chunks: 50,
  queries_per_chunk: 2,
  pool_size: 50,
  with_context: false,
  skip_grading: false,
};

const NAME_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;

export function GenerateSection({ open }: Props) {
  const [form, setForm] = useState<GenForm>(DEFAULTS);
  const activeTask = useEvalStore((s) => s.activeTask);
  const generate = useEvalStore((s) => s.generateTestSet);
  const setOpen = useEvalStore((s) => s.setGeneratePanelOpen);

  if (!open) return null;

  const isGenerating = activeTask?.kind === 'generate';
  const progress = activeTask?.status?.progress as
    | { stage: string; current: number; total: number }
    | undefined;

  const handleSubmit = () => {
    if (!NAME_PATTERN.test(form.name)) {
      void message.error('Name must match [A-Za-z0-9_-]{1,64}');
      return;
    }
    void generate({
      name: form.name,
      num_chunks: form.num_chunks,
      queries_per_chunk: form.queries_per_chunk,
      pool_size: form.pool_size,
      with_context: form.with_context,
      skip_grading: form.skip_grading,
    });
  };

  return (
    <div className={styles.genPanel}>
      <div className={styles.genFormRow}>
        <span className={styles.genFormLabel}>Name *</span>
        <input
          type="text"
          className={styles.genInput}
          placeholder="e.g. rl_eval_v3"
          value={form.name}
          disabled={isGenerating}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
        />
      </div>
      <div className={styles.genFormRow}>
        <span className={styles.genFormLabel}>Chunks to sample</span>
        <input
          type="number"
          className={styles.genInput}
          min={1}
          value={form.num_chunks}
          disabled={isGenerating}
          onChange={(e) => {
            const v = parseInt(e.target.value, 10);
            if (v >= 1) setForm({ ...form, num_chunks: v });
          }}
        />
      </div>
      <div className={styles.genFormRow}>
        <span className={styles.genFormLabel}>Queries per chunk</span>
        <input
          type="number"
          className={styles.genInput}
          min={1}
          value={form.queries_per_chunk}
          disabled={isGenerating}
          onChange={(e) => {
            const v = parseInt(e.target.value, 10);
            if (v >= 1) setForm({ ...form, queries_per_chunk: v });
          }}
        />
      </div>
      <div className={styles.genFormRow}>
        <span className={styles.genFormLabel}>Pool size</span>
        <input
          type="number"
          className={styles.genInput}
          min={1}
          value={form.pool_size}
          disabled={isGenerating}
          onChange={(e) => {
            const v = parseInt(e.target.value, 10);
            if (v >= 1) setForm({ ...form, pool_size: v });
          }}
        />
      </div>
      <div className={styles.genFormRow}>
        <span className={styles.genFormLabel}>With context</span>
        <Switch
          size="small"
          checked={form.with_context}
          disabled={isGenerating}
          onChange={(v) => setForm({ ...form, with_context: v })}
        />
      </div>
      <div className={styles.genFormRow}>
        <span className={styles.genFormLabel}>Skip grading</span>
        <Switch
          size="small"
          checked={form.skip_grading}
          disabled={isGenerating}
          onChange={(v) => setForm({ ...form, skip_grading: v })}
        />
      </div>

      {isGenerating && progress && (
        <div className={styles.progressWrap}>
          <span>
            {progress.stage} — {progress.current}/{progress.total || '?'}
          </span>
          <div className={styles.progressBar}>
            <div
              className={styles.progressFill}
              style={{
                width: progress.total > 0
                  ? `${Math.min(100, (progress.current / progress.total) * 100)}%`
                  : '5%',
              }}
            />
          </div>
        </div>
      )}

      <div className={styles.genFormActions}>
        <Button size="small" disabled={isGenerating} onClick={() => setOpen(false)}>
          Cancel
        </Button>
        <Button size="small" type="primary" disabled={isGenerating} onClick={handleSubmit}>
          {isGenerating ? 'Generating…' : 'Start generation'}
        </Button>
      </div>
    </div>
  );
}
