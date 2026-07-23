import { BookOpen, ChevronDown, Sparkles } from "lucide-react"

import { MessageContent } from "@/components/MessageContent"
import { StatusChip } from "@/components/ui/status-chip"
import type { Message, RetrievedChunk } from "@/app/app/chat-types"

/**
 * One turn in the transcript.
 *
 * User turns are compact and right-aligned. Andrew turns use the broader
 * editorial reading treatment: a grounding status in plain language, the answer
 * itself, an optional recall line, and an inspectable source drawer. Cache
 * telemetry and raw scores are intentionally NOT shown here; they belong in a
 * developer view, not the normal conversation.
 */

type Grounding = "grounded" | "related" | "general"

/**
 * Three honest states from the data the backend already sends: the grounded
 * boolean plus whether any related material came back. No score is exposed.
 */
function groundingOf(msg: Message): Grounding | null {
  if (msg.isGrounded === undefined) return null // restored message, no metadata
  if (msg.isGrounded) return "grounded"
  return (msg.retrievedChunks?.length ?? 0) > 0 ? "related" : "general"
}

const GROUNDING_LABEL: Record<Grounding, string> = {
  grounded: "Grounded in Andrew's public work",
  related: "Related material",
  general: "General analysis",
}

// Source folders map to readable categories.
const CATEGORY: Record<string, string> = {
  lecture: "Lecture",
  transcripts: "Transcript",
  newsletter: "The Batch",
  the_batch: "The Batch",
  blog_posts: "Blog",
  blog: "Blog",
}

function humanizeSource(file: string): string {
  return file.replace(/\.txt$/i, "").replace(/[_-]+/g, " ").trim()
}

export function MessageBubble({ msg }: { msg: Message }) {
  const isUser = msg.role === "user"
  const grounding = isUser ? null : groundingOf(msg)
  const sources = msg.retrievedChunks ?? []

  return (
    <div
      className={`flex gap-2 sm:gap-4 min-w-0 ${
        isUser ? "ml-auto max-w-[85%] sm:max-w-lg flex-row-reverse" : "max-w-full sm:max-w-3xl"
      }`}
    >
      <div
        className={`w-8 h-8 rounded-full flex items-center justify-center font-semibold text-[12px] flex-shrink-0 ${
          isUser
            ? "bg-[var(--surface-alt)] text-[var(--text-muted)]"
            : "bg-[var(--brand)] text-[var(--brand-text)]"
        }`}
      >
        {isUser ? "You" : "AN"}
      </div>

      {isUser ? (
        <div className="rounded-2xl rounded-tr-sm border border-[var(--border)] bg-[var(--surface-alt)] px-4 py-2.5 text-[15px] leading-relaxed text-[var(--text)] break-words min-w-0">
          <MessageContent content={msg.content} />
        </div>
      ) : (
        <div className="flex flex-col gap-3 min-w-0">
          {grounding && (
            <StatusChip tone={grounding === "grounded" ? "brand" : "neutral"}>
              {GROUNDING_LABEL[grounding]}
            </StatusChip>
          )}

          {msg.recalled && msg.recalled.length > 0 && (
            <div className="flex items-start gap-1.5 text-[13px] text-[var(--text-muted)]">
              <Sparkles className="w-3.5 h-3.5 mt-0.5 flex-shrink-0 text-[var(--brand)]" />
              <span>Building on what we covered before: {msg.recalled.join(", ")}</span>
            </div>
          )}

          <div className="text-[15px] leading-[1.65] text-[var(--text)] break-words min-w-0">
            <MessageContent content={msg.content} />
          </div>

          {sources.length > 0 && <SourceDrawer sources={sources} grounding={grounding} />}
        </div>
      )}
    </div>
  )
}

/**
 * An inspectable, keyboard-accessible source list. Native details/summary so it
 * opens with Enter/Space and is announced correctly. Shows a human title, the
 * category, and a short excerpt; never the filename or a raw score.
 */
function SourceDrawer({
  sources,
  grounding,
}: {
  sources: RetrievedChunk[]
  grounding: Grounding | null
}) {
  const heading =
    grounding === "grounded"
      ? "From Andrew's materials"
      : "Closest related material"

  return (
    <details className="group rounded-xl border border-[var(--border)] bg-[var(--surface)]">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-3 py-2 text-[12px] text-[var(--text-muted)] hover:text-[var(--text)]">
        <span className="flex items-center gap-1.5">
          <BookOpen className="w-3.5 h-3.5 text-[var(--brand)]" />
          {heading} ({sources.length})
        </span>
        <ChevronDown className="w-3.5 h-3.5 transition-transform group-open:rotate-180" />
      </summary>
      <ul className="flex flex-col gap-2 border-t border-[var(--border)] p-3">
        {sources.slice(0, 4).map((s, i) => (
          <li
            key={i}
            className="rounded-lg border border-[var(--border)] bg-[var(--surface-alt)] p-2.5"
          >
            <div className="flex items-center gap-2">
              <span className="text-[13px] font-medium text-[var(--text)] truncate">
                {humanizeSource(s.source_file)}
              </span>
              <span className="ml-auto shrink-0 rounded-full border border-[var(--border)] px-2 py-0.5 text-[10px] text-[var(--text-muted)]">
                {CATEGORY[s.source_type] ?? "Source"}
              </span>
            </div>
            {s.chunk_text && (
              <p className="mt-1.5 text-[12px] leading-relaxed text-[var(--text-muted)] line-clamp-3">
                {s.chunk_text.slice(0, 240)}
                {s.chunk_text.length > 240 ? "…" : ""}
              </p>
            )}
          </li>
        ))}
      </ul>
    </details>
  )
}
