import { useEffect } from 'react';
import { message } from 'antd';
import { AppNav } from '../../components/app-nav';
import { ChatInput } from '../../components/chat-input';
import { ChunkCard } from '../../components/chunk-card';
import { ConfigPanel } from '../../components/config-panel';
import { GeneratedAnswer } from '../../components/generated-answer';
import { useSearchStore } from '../../stores/search-store';
import styles from './search-page.module.css';

const SCORE_COLORS = {
  retrieval: 'var(--signal-retrieval)',
  metadata:  'var(--signal-metadata)',
  retention: 'var(--signal-retention)',
};

interface MetaBarProps {
  ms: number;
  topo: string;
  rewrite: string;
  count: number;
}

function MetaBar({ ms, topo, rewrite, count }: MetaBarProps) {
  return (
    <div className={styles.metaBar}>
      <span>⏱ {ms}ms</span>
      <span>{topo}</span>
      <span className={styles.metaDot}>·</span>
      <span>{rewrite}</span>
      <span className={styles.metaDot}>·</span>
      <span>{count} chunks</span>
      <div className={styles.metaSpacer} />
      <div className={styles.legend}>
        {Object.entries(SCORE_COLORS).map(([k, c]) => (
          <span key={k} className={styles.legendItem}>
            <span className={styles.legendDot} style={{ background: c }} />
            {k}
          </span>
        ))}
      </div>
    </div>
  );
}

export function SearchPage() {
  const mode          = useSearchStore((s) => s.mode);
  const config        = useSearchStore((s) => s.config);
  const results       = useSearchStore((s) => s.results);
  const generated     = useSearchStore((s) => s.generated);
  const meta          = useSearchStore((s) => s.meta);
  const loading       = useSearchStore((s) => s.loading);
  const streaming     = useSearchStore((s) => s.streaming);
  const configOpen    = useSearchStore((s) => s.configOpen);
  const sourcesOpen   = useSearchStore((s) => s.sourcesOpen);
  const errorMessage  = useSearchStore((s) => s.errorMessage);

  const setMode       = useSearchStore((s) => s.setMode);
  const setConfig     = useSearchStore((s) => s.setConfig);
  const toggleConfig  = useSearchStore((s) => s.toggleConfig);
  const setConfigOpen = useSearchStore((s) => s.setConfigOpen);
  const toggleSources = useSearchStore((s) => s.toggleSources);
  const submit        = useSearchStore((s) => s.submit);
  const clearError    = useSearchStore((s) => s.clearError);

  useEffect(() => {
    if (errorMessage) {
      void message.error(errorMessage);
      clearError();
    }
  }, [errorMessage, clearError]);

  const showGenerate = mode >= 1;
  const showChunks   = mode <= 1;
  const hasContent   = results.length > 0 || generated.length > 0;

  return (
    <div className={styles.shell}>
      <AppNav />

      <div className={styles.contentArea}>
        {hasContent ? (
          <>
            {meta && <MetaBar {...meta} />}

            {showGenerate && (
              <GeneratedAnswer text={generated} streaming={streaming} />
            )}

            {showChunks && results.length > 0 && (
              <>
                <div
                  className={styles.sourcesToggle}
                  onClick={toggleSources}
                >
                  <span
                    className={styles.toggleArrow}
                    style={{ transform: sourcesOpen ? 'rotate(0deg)' : 'rotate(-90deg)' }}
                  >
                    ▾
                  </span>
                  {results.length} sources
                </div>

                {sourcesOpen && results.map((item, i) => (
                  <ChunkCard
                    key={item.chunk_id}
                    item={item}
                    rank={i + 1}
                    weights={{ alpha: config.alpha, beta: config.beta, gamma: config.gamma }}
                  />
                ))}
              </>
            )}
          </>
        ) : (
          <div className={styles.emptyState}>
            <span className={styles.emptyIcon}>⌕</span>
            <span className={styles.emptyText}>Enter a query to search your knowledge base</span>
          </div>
        )}
      </div>

      <ConfigPanel
        open={configOpen}
        onClose={() => setConfigOpen(false)}
        config={config}
        onChange={setConfig}
      />

      <ChatInput
        onSubmit={submit}
        loading={loading}
        mode={mode}
        onModeChange={setMode}
        configOpen={configOpen}
        onConfigToggle={toggleConfig}
      />
    </div>
  );
}
