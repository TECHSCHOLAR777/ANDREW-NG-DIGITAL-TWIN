import { BookOpen, Sparkles, User, Zap } from "lucide-react"

import { MessageContent } from "@/components/MessageContent"
import type { Message } from "@/app/app/chat-types"

/**
 * One turn in the transcript.
 *
 * Extracted verbatim from the page so the transcript can be reasoned about on
 * its own. Andrew turns carry the optional recall line, grounding notice,
 * citations, and cache badge; user turns are the compact right-aligned form.
 * Styling and behaviour are unchanged from the monolith.
 */
export function MessageBubble({ msg }: { msg: Message }) {
  const isUser = msg.role === "user"
  return (
    <div
      className={`flex gap-2 sm:gap-4 max-w-full sm:max-w-3xl min-w-0 ${
        isUser ? "ml-auto flex-row-reverse" : ""
      }`}
    >
      <div
        className={`w-8 h-8 rounded-full flex items-center justify-center font-medium text-[13px] flex-shrink-0 ${
          isUser
            ? "bg-[var(--text-muted)] text-[var(--brand-text)]"
            : "bg-[var(--brand)] text-[var(--brand-text)]"
        }`}
      >
        {isUser ? <User className="w-4 h-4" /> : "AN"}
      </div>

      <div
        className={`flex flex-col gap-3 p-3 sm:p-4 rounded-2xl text-[13px] leading-relaxed border min-w-0 break-words ${
          isUser
            ? "border-[var(--border)] bg-[var(--bg)] text-[var(--text)]"
            : "border-[var(--border)] bg-[var(--surface)] text-[var(--text)] shadow-sm"
        }`}
      >
        <div className="w-full min-w-0">
          <MessageContent content={msg.content} />
        </div>

        {!isUser && msg.recalled && msg.recalled.length > 0 && (
          <div className="flex items-start gap-1.5 text-[12px] text-[var(--text-muted)] -mt-1">
            <Sparkles className="w-3.5 h-3.5 mt-0.5 flex-shrink-0 text-[var(--brand)]" />
            <span>Building on what we covered before: {msg.recalled.join(", ")}</span>
          </div>
        )}

        {!isUser && msg.isGrounded === false && (
          <div
            className="flex items-start gap-1.5 text-[11px] px-2.5 py-1.5 rounded-lg mt-1 border"
            style={{
              color: "var(--warn)",
              background: "var(--warn-soft)",
              borderColor: "var(--warn-border)",
            }}
          >
            <span>
              Outside Andrew&apos;s written material. This answer is his general
              perspective rather than a grounded citation.
            </span>
          </div>
        )}

        {!isUser && msg.retrievedChunks && msg.retrievedChunks.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-2 border-t border-[var(--border)] pt-2">
            <span className="text-[11px] text-[var(--text-muted)] font-medium block w-full">
              {msg.isGrounded === false
                ? "Closest material:"
                : "From Andrew's materials:"}
            </span>
            {msg.retrievedChunks.slice(0, 3).map((chunk, cIdx) => (
              <span
                key={cIdx}
                title={
                  chunk.chunk_text
                    ? `${chunk.chunk_text.slice(0, 300)}…`
                    : `Score: ${chunk.final_score.toFixed(4)}`
                }
                className="text-[11px] text-[var(--brand)] hover:text-[var(--brand)]/80 bg-[var(--brand-soft)] px-2 py-1 rounded-lg border border-[var(--border)] max-w-[180px] truncate cursor-help flex items-center gap-1"
              >
                <BookOpen className="w-3 h-3 text-[var(--brand)] flex-shrink-0" />
                {chunk.source_file.replace(/_/g, " ").replace(".txt", "")}
              </span>
            ))}
          </div>
        )}

        {!isUser && (msg.cachedTokenCount ?? 0) > 0 && (
          <div className="flex items-center gap-1.5 text-[11px] font-normal mt-1">
            <span
              className="flex items-center gap-0.5 px-2 py-0.5 rounded-full border"
              style={{
                color: "var(--ok)",
                background: "var(--ok-soft)",
                borderColor: "var(--border)",
              }}
            >
              <Zap
                className="w-3 h-3"
                style={{ fill: "var(--ok)", color: "var(--ok)" }}
              />
              {msg.cachedTokenCount?.toLocaleString()} tokens served from cache
            </span>
          </div>
        )}
      </div>
    </div>
  )
}
