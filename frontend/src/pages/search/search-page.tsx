import { useState } from 'react';
import { Input, Slider, Select, Spin, message } from 'antd';
import { SearchOutlined } from '@ant-design/icons';
import { AppNav } from '../../components/app-nav';
import { ScoreBreakdown } from '../../components/score-breakdown';
import { fetchSearch } from '../../api/search';
import type { QueryMode, RetentionMode, SearchResultItem } from '../../api/types';
import styles from './search-page.module.css';

const QUERY_MODES: { key: QueryMode; label: string }[] = [
  { key: 'basic', label: 'Basic' },
  { key: 'rag_fusion', label: 'RAG-Fusion' },
  { key: 'hyde', label: 'HyDE' },
];

const RETENTION_OPTIONS = [
  { value: 'prefer_recent', label: 'prefer_recent' },
  { value: 'awaken_forgotten', label: 'awaken_forgotten' },
];

export function SearchPage() {
  const [query, setQuery] = useState('');
  const [topK, setTopK] = useState(10);
  const [retentionMode, setRetentionMode] = useState<RetentionMode>('prefer_recent');
  const [queryMode, setQueryMode] = useState<QueryMode>('basic');
  const [results, setResults] = useState<SearchResultItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [lastQuery, setLastQuery] = useState<string | null>(null);

  async function handleSearch() {
    const trimmed = query.trim();
    if (!trimmed) return;
    setLoading(true);
    try {
      const data = await fetchSearch({ query: trimmed, top_k: topK, mode: retentionMode });
      setResults(data);
      setLastQuery(trimmed);
      setExpandedId(data[0]?.chunk_id ?? null);
    } catch {
      void message.error('Search failed. Please try again.');
    } finally {
      setLoading(false);
    }
  }

  function toggleCard(id: string) {
    setExpandedId(prev => (prev === id ? null : id));
  }

  return (
    <div className={styles.shell}>
      <AppNav />
      <div className={styles.body}>
        {/* Sidebar */}
        <aside className={styles.sidebar}>
          <section className={styles.section}>
            <div className={styles.sectionLabel}>Query mode</div>
            <div className={styles.modeList}>
              {QUERY_MODES.map(({ key, label }) => (
                <div
                  key={key}
                  className={`${styles.modeItem} ${queryMode === key ? styles.modeItemActive : ''}`}
                  onClick={() => setQueryMode(key)}
                >
                  <span
                    className={`${styles.modeDot} ${queryMode === key ? styles.modeDotActive : ''}`}
                  />
                  <span className={queryMode === key ? styles.modeLabelActive : styles.modeLabel}>
                    {label}
                  </span>
                </div>
              ))}
              <div className={styles.futureSlot}>+ future modes</div>
            </div>
          </section>

          <section className={styles.section}>
            <div className={styles.sectionLabel}>
              Results <strong>{topK}</strong>
            </div>
            <Slider
              min={1}
              max={20}
              value={topK}
              onChange={setTopK}
              tooltip={{ formatter: v => `${v}` }}
            />
          </section>

          <section className={styles.section}>
            <div className={styles.sectionLabel}>Retention</div>
            <Select
              value={retentionMode}
              onChange={setRetentionMode}
              options={RETENTION_OPTIONS}
              style={{ width: '100%', fontSize: 12 }}
              size="small"
            />
          </section>

          <div className={styles.spacer} />
          <div className={styles.futureSlot}>+ topology preset</div>
          <div className={styles.futureSlot} style={{ marginTop: 6 }}>+ filter panel</div>

          <button className={styles.generateBtn}>Generate answer</button>
        </aside>

        {/* Main */}
        <main className={styles.main}>
          <div className={styles.searchRow}>
            <Input
              value={query}
              onChange={e => setQuery(e.target.value)}
              onPressEnter={handleSearch}
              placeholder="Enter your query…"
              style={{ flex: 1, fontSize: 13 }}
            />
            <button className={styles.searchBtn} onClick={handleSearch}>
              <SearchOutlined style={{ marginRight: 4 }} />
              Search
            </button>
          </div>

          {lastQuery && (
            <div className={styles.agentBanner}>
              <span className={styles.agentLabel}>Via Agent</span>
              <span className={styles.agentDot}>·</span>
              <span className={styles.agentQuery}>"{lastQuery}"</span>
              <div className={styles.spacer} />
              <span
                className={styles.agentClose}
                onClick={() => setLastQuery(null)}
              >
                ✕
              </span>
            </div>
          )}

          <Spin spinning={loading} tip="Searching…">
            <div className={styles.resultList}>
              {results.map((item, idx) => {
                const isExpanded = expandedId === item.chunk_id;
                return (
                  <div
                    key={item.chunk_id}
                    className={styles.resultCard}
                    onClick={() => toggleCard(item.chunk_id)}
                  >
                    <div className={styles.cardHeader}>
                      <span className={styles.cardRank}>#{idx + 1}</span>
                      <span className={styles.cardTitle}>{item.filename}</span>
                      <div className={styles.spacer} />
                      <span className={isExpanded ? styles.cardScoreAccent : styles.cardScore}>
                        {item.final_score.toFixed(3)}
                      </span>
                    </div>
                    <p className={styles.cardContent}>{item.content}</p>
                    {item.tags.length > 0 && (
                      <div className={styles.tagRow}>
                        {item.tags.map(tag => (
                          <span key={tag} className={styles.tag}>{tag}</span>
                        ))}
                      </div>
                    )}
                    {isExpanded && (
                      <ScoreBreakdown detail={item.score_detail} finalScore={item.final_score} />
                    )}
                  </div>
                );
              })}
              {results.length === 0 && !loading && (
                <div className={styles.emptySlot}>+ generation output area (expands below results on trigger)</div>
              )}
            </div>
          </Spin>
        </main>
      </div>
    </div>
  );
}
