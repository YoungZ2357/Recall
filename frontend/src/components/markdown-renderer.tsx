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

// Some LLMs emit LaTeX-native delimiters \(...\) / \[...\] even when prompted
// to use $-delimiters. CommonMark's backslash-escape rule turns `\(` and `\[`
// into literal `(` `[` before remark-math runs, so without this normalization
// the math source falls through as plain text. Rewrite to $...$ / $$...$$
// before ReactMarkdown sees the input.
//
// Non-greedy matching means unbalanced delimiters (e.g. mid-stream SSE chunk
// with an opening `\(` but no closing `\)` yet) are left as-is and pass
// through untouched — they'll be normalized on the next streaming update
// once the closing delimiter arrives.
const BLOCK_MATH_DELIM  = /\\\[([\s\S]+?)\\\]/g;
const INLINE_MATH_DELIM = /\\\(([^\n]+?)\\\)/g;

function normalizeMathDelimiters(input: string): string {
  return input
    .replace(BLOCK_MATH_DELIM,  (_m, inner) => '$$' + inner + '$$')
    .replace(INLINE_MATH_DELIM, (_m, inner) => '$'  + inner + '$');
}

export function MarkdownRenderer({ children, components }: MarkdownRendererProps) {
  const normalized = normalizeMathDelimiters(children);
  return (
    // Wrapper div is required: react-markdown v8 renders a fragment and cannot
    // accept a className prop directly.
    <div className={styles.prose}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[[rehypeKatex, REHYPE_KATEX_OPTIONS]]}
        components={components}
      >
        {normalized}
      </ReactMarkdown>
    </div>
  );
}
