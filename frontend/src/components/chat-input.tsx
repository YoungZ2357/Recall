import { useState } from 'react';
import styles from './chat-input.module.css';

const MODES = ['Search', 'S+G', 'Gen'] as const;

interface ChatInputProps {
  onSubmit: (query: string) => void;
  loading: boolean;
  mode: number;
  onModeChange: (m: number) => void;
  configOpen: boolean;
  onConfigToggle: () => void;
}

export function ChatInput({ onSubmit, loading, mode, onModeChange, configOpen, onConfigToggle }: ChatInputProps) {
  const [query, setQuery] = useState('');

  function handleSubmit() {
    const trimmed = query.trim();
    if (!trimmed || loading) return;
    onSubmit(trimmed);
    setQuery('');
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleSubmit();
    }
  }

  return (
    <div className={styles.bar}>
      {/* mode selector */}
      <div className={styles.modeGroup}>
        {MODES.map((m, i) => (
          <span
            key={m}
            className={mode === i ? styles.modeActive : styles.modeItem}
            onClick={() => onModeChange(i)}
          >
            {m}
          </span>
        ))}
      </div>

      {/* query input */}
      <div className={styles.inputWrap}>
        <span className={styles.searchIcon}>⌕</span>
        <input
          type="text"
          value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Enter query…"
          className={styles.input}
          disabled={loading}
        />
      </div>

      {/* config button */}
      <button
        className={configOpen ? styles.iconBtnActive : styles.iconBtn}
        onClick={onConfigToggle}
        title="Pipeline config"
      >
        ⚙
      </button>

      {/* send button */}
      <button
        className={styles.sendBtn}
        onClick={handleSubmit}
        disabled={!query.trim() || loading}
        title="Send"
      >
        ↑
      </button>
    </div>
  );
}
