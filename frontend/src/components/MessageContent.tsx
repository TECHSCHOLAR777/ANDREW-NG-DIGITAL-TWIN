"use client";

// components/MessageContent.tsx
// ─────────────────────────────────────────────────────────────────────────────
// Renders an assistant or user message.
//
// This replaces a hand-rolled parser that split on "**", stripped every "$",
// and mapped LaTeX commands to unicode with regexes. That approach fought the
// persona directly: the persona teaches with notation (theta for parameters,
// J(theta) for cost, h(x) for hypothesis), and the renderer was deleting the
// very characters that carry the meaning. "$J(\theta)$" arrived as mangled
// text, and anything with braces or subscripts came out worse.
//
// react-markdown with remark-math and rehype-katex renders the maths properly.
// GFM is included for tables, which show up in comparison answers.
//
// Note on the persona's formatting rules: it is instructed NOT to emit
// headers, bullet lists or numbered lists inside a conversational answer, and
// services/persona.py now enforces that with validators. So the list and
// heading styles below are a safety net for when the model slips, not the
// expected path.
// ─────────────────────────────────────────────────────────────────────────────

import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";

interface MessageContentProps {
  content: string;
  /** Assistant text is streamed, so it re-renders on every token. */
  isStreaming?: boolean;
}

function MessageContentImpl({ content }: MessageContentProps) {
  if (!content) return null;

  return (
    <div className="message-prose text-[13px] leading-relaxed text-[var(--text)]">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
          p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
          strong: ({ children }) => (
            <strong className="font-semibold text-[var(--text)]">{children}</strong>
          ),
          em: ({ children }) => <em className="italic">{children}</em>,
          code: ({ className, children, ...props }) => {
            // Fenced blocks carry a language class; inline code does not.
            const isBlock = Boolean(className);
            if (isBlock) {
              return (
                <code
                  className="block bg-[var(--bg)] border border-[var(--border)] rounded-lg p-3 my-2 overflow-x-auto font-mono text-[12px] text-[var(--text)]"
                  {...props}
                >
                  {children}
                </code>
              );
            }
            return (
              <code
                className="bg-[var(--surface-alt)] px-1 py-0.5 rounded text-rose-600 font-mono text-[12px]"
                {...props}
              >
                {children}
              </code>
            );
          },
          pre: ({ children }) => <pre className="my-2">{children}</pre>,
          ul: ({ children }) => (
            <ul className="list-disc pl-5 my-2 space-y-1">{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal pl-5 my-2 space-y-1">{children}</ol>
          ),
          li: ({ children }) => <li className="pl-1">{children}</li>,
          h1: ({ children }) => <p className="font-semibold mb-2">{children}</p>,
          h2: ({ children }) => <p className="font-semibold mb-2">{children}</p>,
          h3: ({ children }) => <p className="font-semibold mb-2">{children}</p>,
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-[var(--accent)] underline underline-offset-2"
            >
              {children}
            </a>
          ),
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-[var(--border)] pl-3 my-2 text-[var(--text-muted)]">
              {children}
            </blockquote>
          ),
          table: ({ children }) => (
            <div className="overflow-x-auto my-2">
              <table className="min-w-full text-[12px] border border-[var(--border)] rounded-lg">
                {children}
              </table>
            </div>
          ),
          th: ({ children }) => (
            <th className="border-b border-[var(--border)] bg-[var(--bg)] px-2 py-1 text-left font-medium">
              {children}
            </th>
          ),
          td: ({ children }) => (
            <td className="border-b border-[var(--surface-alt)] px-2 py-1">{children}</td>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

// Streaming re-renders this on every token, and markdown parsing is not free.
// Memoising on the text means a token that does not change this message costs
// nothing.
export const MessageContent = React.memo(
  MessageContentImpl,
  (prev, next) => prev.content === next.content,
);

export default MessageContent;
