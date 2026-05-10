import { useState } from 'react';
import { Spin, message } from 'antd';
import { AppNav } from '../../components/app-nav';
import { ScoreBreakdown } from '../../components/score-breakdown';
import { ChatInput } from '../../components/chat-input';
import { fetchSearch } from '../../api/search';
import type { ActionMode, QueryMode, RetentionMode, SearchResultItem } from '../../api/types';
import styles from './search-page.module.css';

export function SearchPage() {
  const [results, setResults] = useState<SearchResultItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [lastQuery, setLastQuery] = useState<string | null>(null);

  async function handleSubmit(
    query: string,
    actionMode: ActionMode,
    queryMode: QueryMode,
    topK: number,
    retentionMode: RetentionMode,
  ) {
    // TODO F-3: handle 'generate' and 'both' action modes
    if (actionMode === 'generate') return;

    setLoading(true);
    try {
      const data = await fetchSearch({ query, top_k: topK, mode: retentionMode });
      // NOTE: queryMode is not yet passed to backend — tracked in F-5
      void queryMode;
      setResults(data);
      setLastQuery(query);
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
      <main className={styles.resultArea}>
        {lastQuery && (
          <div className={styles.agentBanner}>
            <span className={styles.agentLabel}>Via Agent</span>
            <span className={styles.agentDot}>·</span>
            <span className={styles.agentQuery}>"{lastQuery}"</span>
            <div className={styles.spacer} />
            <span className={styles.agentClose} onClick={() => setLastQuery(null)}>✕</span>
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
      <ChatInput onSubmit={handleSubmit} loading={loading} />
    </div>
  );
}
