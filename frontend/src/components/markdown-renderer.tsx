import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import type { Components } from 'react-markdown';
import styles from './markdown-renderer.module.css';

interface MarkdownRendererProps {
  children: string;
  /** Optional component overrides forwarded directly to ReactMarkdown */
  components?: Components;
}

// KaTeX: never throw on bad input — render the offending source inline in a
// muted color so malformed/half-streamed formulas don't crash the answer.
const REHYPE_KATEX_OPTIONS = {
  throwOnError: false,
  errorColor: 'var(--text-muted)',
};

export function MarkdownRenderer({ children, components }: MarkdownRendererProps) {
  return (
    // Wrapper div is required: react-markdown v8 renders a fragment and cannot
    // accept a className prop directly.
    <div className={styles.prose}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[[rehypeKatex, REHYPE_KATEX_OPTIONS]]}
        components={components}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
