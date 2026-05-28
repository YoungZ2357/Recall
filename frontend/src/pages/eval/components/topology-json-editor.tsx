import { useState } from 'react';
import { Modal, message } from 'antd';
import type { TopologySpecJSON } from '../../../api/types';
import styles from '../eval-page.module.css';

interface Props {
  open: boolean;
  initialSpec: TopologySpecJSON | null;
  onClose: () => void;
  onSave: (spec: TopologySpecJSON) => void;
}

const EXAMPLE: TopologySpecJSON = {
  name: 'custom',
  nodes: [
    { node_id: 'vec', node_type: 'VectorSearcher', config: {} },
    { node_id: 'bm25', node_type: 'BM25Searcher', config: {} },
    { node_id: 'merge', node_type: 'RRFMerger', config: { k: 60 } },
    { node_id: 'rerank', node_type: 'Reranker', config: { alpha: 0.85, beta: 0.15, gamma: 0.0 } },
  ],
  edges: [
    { from_node: 'vec', to_node: 'merge' },
    { from_node: 'bm25', to_node: 'merge' },
    { from_node: 'merge', to_node: 'rerank' },
  ],
};

// State lives inside this child so it mounts/remounts each time the parent
// toggles `open` — initial JSON is derived from props at mount time without
// needing useEffect/setState ping-pong.
function EditorBody({
  initialSpec,
  onClose,
  onSave,
}: Omit<Props, 'open'>) {
  const [text, setText] = useState(() =>
    JSON.stringify(initialSpec ?? EXAMPLE, null, 2),
  );
  const [parseError, setParseError] = useState<string | null>(null);

  const validate = async (): Promise<TopologySpecJSON | null> => {
    let parsed: TopologySpecJSON;
    try {
      parsed = JSON.parse(text) as TopologySpecJSON;
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Invalid JSON';
      setParseError(msg);
      return null;
    }
    try {
      const res = await fetch('/api/topology/validate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(parsed),
      });
      if (!res.ok) {
        const body = await res.text().catch(() => '');
        setParseError(`Validation failed (${res.status}): ${body}`);
        return null;
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Network error';
      setParseError(msg);
      return null;
    }
    setParseError(null);
    return parsed;
  };

  const handleSave = async () => {
    const parsed = await validate();
    if (parsed) {
      onSave(parsed);
      void message.success('Custom topology saved');
      onClose();
    }
  };

  return (
    <Modal
      title="Custom topology JSON"
      open
      onCancel={onClose}
      onOk={handleSave}
      width={700}
      okText="Save"
    >
      <textarea
        className={styles.jsonTextarea}
        value={text}
        onChange={(e) => setText(e.target.value)}
        spellCheck={false}
      />
      {parseError && <div className={styles.jsonError}>{parseError}</div>}
    </Modal>
  );
}

export function TopologyJsonEditor({ open, initialSpec, onClose, onSave }: Props) {
  if (!open) return null;
  return <EditorBody initialSpec={initialSpec} onClose={onClose} onSave={onSave} />;
}
