import { Spin } from 'antd';
import styles from './generated-answer.module.css';

interface GeneratedAnswerProps {
  text: string;
  streaming: boolean;
}

function renderWithCitations(text: string): React.ReactNode[] {
  return text.split(/(\[\d+\])/).map((part, i) => {
    const match = part.match(/^\[(\d+)\]$/);
    if (match) {
      return (
        <sup key={i} className={styles.citation}>
          [{match[1]}]
        </sup>
      );
    }
    return <span key={i}>{part}</span>;
  });
}

export function GeneratedAnswer({ text, streaming }: GeneratedAnswerProps) {
  return (
    <div className={styles.card}>
      <div className={styles.header}>
        <span className={styles.icon}>✦</span>
        <span className={styles.label}>Generated answer</span>
        {streaming && <Spin size="small" style={{ marginLeft: 8 }} />}
      </div>
      <div className={styles.body}>
        {text ? renderWithCitations(text) : (
          <span className={styles.placeholder}>Generating…</span>
        )}
      </div>
    </div>
  );
}
