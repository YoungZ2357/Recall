import { useState } from 'react';
import { message } from 'antd';
import { AppNav } from '../../components/app-nav';
import { ChatInput } from '../../components/chat-input';
import { ChunkCard } from '../../components/chunk-card';
import { ConfigPanel, DEFAULT_CONFIG } from '../../components/config-panel';
import { GeneratedAnswer } from '../../components/generated-answer';
import { fetchSearch } from '../../api/search';
import { streamGenerate } from '../../api/generate';
import { buildTopology } from '../../api/topology-builder';
import type { SearchResultItem, TopologySpecJSON } from '../../api/types';
import type { SearchConfig } from '../../components/config-panel';
import styles from './search-page.module.css';

const SCORE_COLORS = {
  retrieval: 'var(--signal-retrieval)',
  metadata:  'var(--signal-metadata)',
  retention: 'var(--signal-retention)',
};

const TOPO_LABELS: Record<SearchConfig['topo'], string> = {
  vector_only: 'Vector only',
  bm25_only:   'BM25 only',
  rrf:         'Vector + BM25',
  custom:      'Custom',
};

interface SearchMeta {
  ms: number;
  topo: string;
  rewrite: string;
  count: number;
}

function MetaBar({ ms, topo, rewrite, count }: SearchMeta) {
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
  const [mode, setMode] = useState(0);
  const [configOpen, setConfigOpen] = useState(false);
  const [sourcesOpen, setSourcesOpen] = useState(true);
  const [config, setConfig] = useState<SearchConfig>(DEFAULT_CONFIG);

  const [results, setResults] = useState<SearchResultItem[]>([]);
  const [generated, setGenerated] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [loading, setLoading] = useState(false);
  const [meta, setMeta] = useState<SearchMeta | null>(null);

  const showGenerate = mode >= 1;
  const showChunks   = mode <= 1;
  const hasContent   = results.length > 0 || generated.length > 0;

  function patchConfig(patch: Partial<SearchConfig>) {
    setConfig(prev => ({ ...prev, ...patch }));
  }

  async function runStreamGenerate(query: string, topology: TopologySpecJSON) {
    setStreaming(true);
    try {
      for await (const frame of streamGenerate({ query, top_k: config.topK, mode: config.retention, topology })) {
        if (frame.kind === 'token') {
          setGenerated(prev => prev + frame.content);
        }
        // 'sources' and 'unknown' frames are intentionally ignored for now.
      }
    } finally {
      setStreaming(false);
    }
  }

  async function handleSubmit(query: string) {
    let topology: TopologySpecJSON;
    try {
      topology = buildTopology(config);
    } catch (e) {
      void message.error(e instanceof Error ? e.message : 'Invalid topology config');
      return;
    }

    setLoading(true);
    setGenerated('');
    const t0 = Date.now();

    try {
      const searchPromise = showChunks
        ? fetchSearch({ query, top_k: config.topK, mode: config.retention, topology })
        : Promise.resolve([] as SearchResultItem[]);

      const generatePromise = showGenerate
        ? runStreamGenerate(query, topology)
        : Promise.resolve();

      const [data] = await Promise.all([searchPromise, generatePromise]);
      setResults(data);
      setMeta({ ms: Date.now() - t0, topo: TOPO_LABELS[config.topo], rewrite: config.rewrite, count: data.length });
    } catch {
      void message.error('Request failed. Please try again.');
    } finally {
      setLoading(false);
    }
  }

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
                  onClick={() => setSourcesOpen(o => !o)}
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
                  <ChunkCard key={item.chunk_id} item={item} rank={i + 1} />
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
        onChange={patchConfig}
      />

      <ChatInput
        onSubmit={handleSubmit}
        loading={loading}
        mode={mode}
        onModeChange={setMode}
        configOpen={configOpen}
        onConfigToggle={() => setConfigOpen(o => !o)}
      />
    </div>
  );
}
