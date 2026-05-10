import { useState } from 'react';
import { Input, InputNumber, Select, Segmented, Button } from 'antd';
import { SendOutlined } from '@ant-design/icons';
import type { ActionMode, QueryMode, RetentionMode } from '../api/types';
import styles from './chat-input.module.css';

const QUERY_MODE_OPTIONS = [
  { value: 'basic', label: 'Basic' },
  { value: 'rag_fusion', label: 'RAG-Fusion' },
  { value: 'hyde', label: 'HyDE' },
];

const RETENTION_OPTIONS = [
  { value: 'prefer_recent', label: 'prefer_recent' },
  { value: 'awaken_forgotten', label: 'awaken_forgotten' },
];

const ACTION_SEGMENTS = [
  { label: 'Search', value: 'search' },
  { label: 'Generate', value: 'generate' },
  { label: 'S+G', value: 'both' },
];

interface ChatInputProps {
  onSubmit: (
    query: string,
    actionMode: ActionMode,
    queryMode: QueryMode,
    topK: number,
    retentionMode: RetentionMode,
  ) => void;
  loading: boolean;
}

export function ChatInput({ onSubmit, loading }: ChatInputProps) {
  const [query, setQuery] = useState('');
  const [actionMode, setActionMode] = useState<ActionMode>('search');
  const [queryMode, setQueryMode] = useState<QueryMode>('basic');
  const [topK, setTopK] = useState(10);
  const [retentionMode, setRetentionMode] = useState<RetentionMode>('prefer_recent');
  function handleSubmit() {
    const trimmed = query.trim();
    if (!trimmed || loading) return;
    onSubmit(trimmed, actionMode, queryMode, topK, retentionMode);
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  }

  return (
    <div className={styles.chatArea}>
      <div className={styles.controlsRow}>
        <Select
          value={queryMode}
          onChange={setQueryMode}
          options={QUERY_MODE_OPTIONS}
          size="small"
          style={{ width: 112 }}
        />
        <div className={styles.topKControl}>
          <span className={styles.controlLabel}>Top-K</span>
          <InputNumber
            value={topK}
            onChange={v => setTopK(v ?? 10)}
            min={1}
            max={20}
            size="small"
            style={{ width: 56 }}
          />
        </div>
        <Select
          value={retentionMode}
          onChange={setRetentionMode}
          options={RETENTION_OPTIONS}
          size="small"
          style={{ width: 148 }}
        />
      </div>
      <div className={styles.inputRow}>
        <Segmented
          options={ACTION_SEGMENTS}
          value={actionMode}
          onChange={v => setActionMode(v as ActionMode)}
          size="small"
        />
        <Input.TextArea
          value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Enter your query… (Enter to send, Shift+Enter for newline)"
          autoSize={{ minRows: 1, maxRows: 6 }}
          className={styles.textarea}
        />
        <Button
          type="primary"
          icon={<SendOutlined />}
          onClick={handleSubmit}
          loading={loading}
          disabled={!query.trim()}
        >
          Send
        </Button>
      </div>
    </div>
  );
}
