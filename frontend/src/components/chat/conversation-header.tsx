import { Menu, Network, Volume2 } from "lucide-react"

import { ThemeToggle } from "@/components/theme-toggle"

/**
 * The conversation top bar.
 *
 * Identity plus state, mobile drawer toggles, the shared theme control, and the
 * read-aloud toggle. The old generic green "online" dot is gone: the backend
 * being reachable is not a person being online, and the spec calls it out
 * explicitly. State now reads as a quiet "Grounded conversation" label.
 */
export function ConversationHeader({
  onOpenSessions,
  onOpenGraph,
  readAloudEnabled,
  onToggleReadAloud,
}: {
  onOpenSessions: () => void
  onOpenGraph: () => void
  readAloudEnabled: boolean
  onToggleReadAloud: () => void
}) {
  return (
    <div className="h-16 border-b border-[var(--border)] px-3 sm:px-6 flex items-center justify-between bg-[var(--surface)]">
      <div className="flex items-center gap-2 sm:gap-3 min-w-0">
        <button
          onClick={onOpenSessions}
          className="lg:hidden p-2 -ml-1 rounded-lg border border-[var(--border)] text-[var(--text-muted)] hover:bg-[var(--bg)]"
          aria-label="Show conversations"
        >
          <Menu className="w-4 h-4" />
        </button>
        <div className="w-8 h-8 rounded-full bg-[var(--brand)] text-[var(--brand-text)] flex items-center justify-center font-semibold text-[14px] flex-shrink-0">
          AN
        </div>
        <div className="min-w-0">
          <h2 className="text-[14px] font-medium text-[var(--text)] truncate">
            Andrew Ng
          </h2>
          <span className="text-[11px] text-[var(--text-muted)] font-normal truncate">
            Grounded conversation
          </span>
        </div>
      </div>

      <div className="flex items-center gap-2 sm:gap-3">
        <button
          onClick={onOpenGraph}
          className="lg:hidden p-2 rounded-lg border border-[var(--border)] text-[var(--text-muted)] hover:bg-[var(--bg)]"
          aria-label="Show context graph"
        >
          <Network className="w-4 h-4" />
        </button>

        <ThemeToggle />

        <button
          onClick={onToggleReadAloud}
          className={`p-2 rounded-lg border transition ${
            readAloudEnabled
              ? "bg-[var(--brand-soft)] border-[var(--border-strong)] text-[var(--brand)]"
              : "border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--bg)]"
          }`}
          title="Toggle read aloud"
          aria-label="Toggle read aloud"
          aria-pressed={readAloudEnabled}
        >
          <Volume2 className="w-4 h-4" />
        </button>
      </div>
    </div>
  )
}
