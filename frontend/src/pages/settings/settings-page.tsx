import { useEffect, useMemo, useState } from 'react';
import { message } from 'antd';
import { AppNav } from '../../components/app-nav';
import { useSettingsStore, type DraftKeys } from '../../stores/settings-store';
import type { KeySource } from '../../api/settings';
import styles from './settings-page.module.css';

interface FieldSpec {
  field: keyof DraftKeys;
  label: string;
  placeholder: string;
  hint: string;
}

const FIELDS: FieldSpec[] = [
  {
    field: 'embedding_api_key',
    label: 'Embedding API key',
    placeholder: 'sk-…  (GLM Embedding-3)',
    hint: 'Validated by a one-token embedding call before applying.',
  },
  {
    field: 'llm_api_key',
    label: 'LLM API key',
    placeholder: 'sk-…  (DeepSeek / OpenAI-compatible)',
    hint: 'Validated by a max_tokens=1 chat completion before applying.',
  },
  {
    field: 'mineru_api_key',
    label: 'MinerU API key',
    placeholder: 'optional — used only during PDF ingestion',
    hint: 'No liveness check; verified on first PDF ingestion.',
  },
];

const SOURCE_BADGE: Record<KeySource, { className: string; text: string }> = {
  env: { className: styles.badgeEnv, text: '.env' },
  override: { className: styles.badgeOverride, text: 'override' },
  missing: { className: styles.badgeMissing, text: 'missing' },
};

function StatusBadge({ source }: { source: KeySource | undefined }) {
  if (!source) {
    return <span className={`${styles.badge} ${styles.badgeEnv}`}>—</span>;
  }
  const cfg = SOURCE_BADGE[source];
  return <span className={`${styles.badge} ${cfg.className}`}>{cfg.text}</span>;
}

interface KeyFieldProps {
  spec: FieldSpec;
  value: string;
  source: KeySource | undefined;
  disabled: boolean;
  onChange: (next: string) => void;
}

function KeyField({ spec, value, source, disabled, onChange }: KeyFieldProps) {
  const [visible, setVisible] = useState(false);

  return (
    <div className={styles.field}>
      <div className={styles.fieldHeader}>
        <span className={styles.fieldLabel}>{spec.label}</span>
        <StatusBadge source={source} />
      </div>
      <div className={styles.inputWrapper}>
        <input
          className={styles.input}
          type={visible ? 'text' : 'password'}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={spec.placeholder}
          autoComplete="off"
          spellCheck={false}
          disabled={disabled}
        />
        <button
          type="button"
          className={styles.toggleVisibility}
          onClick={() => setVisible((v) => !v)}
          tabIndex={-1}
        >
          {visible ? 'Hide' : 'Show'}
        </button>
      </div>
      <div className={styles.fieldHint}>{spec.hint}</div>
    </div>
  );
}

export function SettingsPage() {
  const draft = useSettingsStore((s) => s.draft);
  const status = useSettingsStore((s) => s.status);
  const loading = useSettingsStore((s) => s.loading);
  const applying = useSettingsStore((s) => s.applying);
  const errorMessage = useSettingsStore((s) => s.errorMessage);

  const setDraftField = useSettingsStore((s) => s.setDraftField);
  const resetDraft = useSettingsStore((s) => s.resetDraft);
  const refreshStatus = useSettingsStore((s) => s.refreshStatus);
  const apply = useSettingsStore((s) => s.apply);
  const clear = useSettingsStore((s) => s.clear);

  useEffect(() => {
    void refreshStatus();
  }, [refreshStatus]);

  useEffect(() => {
    if (errorMessage) void message.error(errorMessage);
  }, [errorMessage]);

  const hasAnyDraft = useMemo(
    () => Object.values(draft).some((v) => v.trim().length > 0),
    [draft],
  );

  const hasAnyOverride = useMemo(() => {
    if (!status) return false;
    return Object.values(status).some((s) => s === 'override');
  }, [status]);

  async function handleApply() {
    const ok = await apply();
    if (ok) {
      void message.success('API keys applied for this process');
      resetDraft();
    }
  }

  async function handleClear() {
    const ok = await clear();
    if (ok) {
      void message.success('Runtime overrides cleared — reverted to .env');
    }
  }

  const showInitialLoading = loading && !status;

  return (
    <div className={styles.shell}>
      <AppNav />
      <div className={styles.contentArea}>
        <div className={styles.container}>
          <div className={styles.header}>
            <div className={styles.breadcrumb}>System / Settings</div>
            <h1 className={styles.title}>API Keys</h1>
          </div>

          <div className={styles.alert}>
            <span className={styles.alertIcon}>ⓘ</span>
            <div>
              <div className={styles.alertTitle}>
                Runtime override — scoped to this process only
              </div>
              <div className={styles.alertBody}>
                Keys you apply here replace the values loaded from{' '}
                <code>.env</code> for the lifetime of the backend process.
                Restarting the container reverts to <code>.env</code>. Drafts
                are kept in this browser tab&apos;s sessionStorage and clear
                when the tab closes.
              </div>
            </div>
          </div>

          {showInitialLoading ? (
            <div className={styles.loadingState}>Loading status…</div>
          ) : (
            FIELDS.map((spec) => (
              <KeyField
                key={spec.field}
                spec={spec}
                value={draft[spec.field]}
                source={status?.[spec.field]}
                disabled={applying}
                onChange={(next) => setDraftField(spec.field, next)}
              />
            ))
          )}

          <div className={styles.actions}>
            <button
              type="button"
              className={`${styles.btn} ${styles.btnPrimary}`}
              onClick={() => void handleApply()}
              disabled={!hasAnyDraft || applying}
            >
              {applying ? 'Validating…' : 'Validate & apply'}
            </button>
            <button
              type="button"
              className={styles.btn}
              onClick={() => void handleClear()}
              disabled={applying || !hasAnyOverride}
            >
              Clear all overrides
            </button>
            <button
              type="button"
              className={`${styles.btn} ${styles.btnGhost}`}
              onClick={resetDraft}
              disabled={applying || !hasAnyDraft}
            >
              Reset form
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
