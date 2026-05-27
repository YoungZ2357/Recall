import type { ReactNode } from 'react';
import type { Components } from 'react-markdown';
import { Spin } from 'antd';
import { MarkdownRenderer } from './markdown-renderer';
import styles from './generated-answer.module.css';

interface GeneratedAnswerProps {
  text: string;
  streaming: boolean;
}

/**
 * Split a plain string on [N] citation markers and render each marker as a
 * styled <sup>. Returns a React node array.
 */
function renderWithCitations(text: string): ReactNode[] {
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

/**
 * Walk React children, applying renderWithCitations to any plain string
 * children. Non-string children (bold, code, links from inline markdown)
 * are passed through unchanged.
 */
function applyCitations(children: ReactNode): ReactNode {
  if (typeof children === 'string') return renderWithCitations(children);
  if (Array.isArray(children)) {
    return children.map((child, i) =>
      typeof child === 'string'
        ? <span key={i}>{renderWithCitations(child)}</span>
        : child
    );
  }
  return children;
}

/**
 * Custom components passed to MarkdownRenderer: intercept paragraph and
 * list-item rendering to inject citation superscripts into text children.
 */
const citationComponents: Components = {
  p({ children })  { return <p>{applyCitations(children)}</p>;  },
  li({ children }) { return <li>{applyCitations(children)}</li>; },
};

export function GeneratedAnswer({ text, streaming }: GeneratedAnswerProps) {
  return (
    <div className={styles.card}>
      <div className={styles.header}>
        <span className={styles.icon}>✦</span>
        <span className={styles.label}>Generated answer</span>
        {streaming && <Spin size="small" style={{ marginLeft: 8 }} />}
      </div>
      <div className={styles.body}>
        {text ? (
          <MarkdownRenderer components={citationComponents}>
            {text}
          </MarkdownRenderer>
        ) : (
          <span className={styles.placeholder}>Generating…</span>
        )}
      </div>
    </div>
  );
}
