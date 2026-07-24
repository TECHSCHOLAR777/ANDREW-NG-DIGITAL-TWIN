"use client"

import * as React from "react"
import { Headphones, Mic, MicOff, Send, Settings } from "lucide-react"

/**
 * The message composer.
 *
 * An auto-growing multi-line textarea, so a detailed technical or strategic
 * question has room and pasted code or equations are not crammed into one line.
 * Enter sends; Shift+Enter inserts a newline. Dictation (one-shot) and the
 * hands-free voice conversation are separate, clearly labelled controls. The
 * focus state uses the restrained orange edge. Draft text is owned by the page,
 * so it survives panel changes and temporary errors.
 */
export function Composer({
  value,
  isRecording,
  isLoading,
  geminiKey,
  tenantReady,
  onChange,
  onSubmit,
  onToggleRecording,
  onStartVoice,
  onOpenSettings,
}: {
  value: string
  isRecording: boolean
  isLoading: boolean
  geminiKey: string
  tenantReady: boolean
  onChange: (v: string) => void
  onSubmit: (e: React.FormEvent) => void
  onToggleRecording: () => void
  onStartVoice: () => void
  onOpenSettings: () => void
}) {
  const textareaRef = React.useRef<HTMLTextAreaElement | null>(null)
  const notReady = !tenantReady || !geminiKey

  // Grow with content up to a ceiling, then scroll. Runs on every value change
  // so it also resizes when the draft is cleared after sending.
  React.useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = "auto"
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`
  }, [value])

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      if (value.trim() && !isLoading && !notReady) {
        e.currentTarget.form?.requestSubmit()
      }
    }
  }

  return (
    <div className="p-3 sm:p-6 border-t border-[var(--border)]">
      <form onSubmit={onSubmit} className="flex items-end gap-3">
        <div className="relative flex-1">
          <textarea
            ref={textareaRef}
            rows={1}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={
              notReady
                ? "Add your Gemini API key in settings to start"
                : isRecording
                  ? "Listening..."
                  : "Ask Andrew anything about ML, AI, or strategy"
            }
            disabled={isLoading || notReady}
            aria-label="Message"
            aria-disabled={notReady}
            className="w-full resize-none bg-[var(--surface)] border border-[var(--border)] text-[15px] leading-relaxed px-4 py-3 pr-20 rounded-xl focus:outline-none focus:border-[var(--brand)] focus:ring-1 focus:ring-[var(--brand)] text-[var(--text)] placeholder-[var(--text-subtle)] transition disabled:opacity-60 disabled:cursor-not-allowed"
          />
          <button
            type="button"
            onClick={onStartVoice}
            disabled={isLoading || notReady}
            className="absolute right-11 bottom-2.5 p-1 text-[var(--text-muted)] hover:text-[var(--brand)] transition disabled:opacity-40"
            title="Start a hands-free voice conversation"
            aria-label="Start a hands-free voice conversation"
          >
            <Headphones className="w-4 h-4" />
          </button>
          <button
            type="button"
            onClick={onToggleRecording}
            disabled={isLoading || notReady}
            className={`absolute right-3 bottom-2.5 p-1 transition disabled:opacity-40 ${
              isRecording
                ? "text-[var(--danger)]"
                : "text-[var(--text-muted)] hover:text-[var(--brand)]"
            }`}
            title={isRecording ? "Stop dictation" : "Dictate a message"}
            aria-label={isRecording ? "Stop dictation" : "Dictate a message"}
            aria-pressed={isRecording}
          >
            {isRecording ? <MicOff className="w-4 h-4" /> : <Mic className="w-4 h-4" />}
          </button>
        </div>

        <button
          type="submit"
          disabled={isLoading || !value.trim() || notReady}
          aria-label="Send message"
          className="bg-[var(--brand)] hover:opacity-90 disabled:opacity-50 text-[var(--brand-text)] p-3 rounded-xl flex items-center justify-center transition shadow-sm shrink-0"
        >
          <Send className="w-4 h-4" />
        </button>
      </form>
      {notReady ? (
        <p className="mt-2 text-[11px] text-[var(--text-subtle)] flex items-center gap-1">
          Add your Gemini API key in{" "}
          <button
            type="button"
            onClick={onOpenSettings}
            className="inline-flex items-center gap-0.5 text-[var(--brand)] hover:underline font-medium"
            aria-label="Open settings to add your Gemini API key"
          >
            <Settings className="w-3 h-3" />
            settings
          </button>{" "}
          to start.
        </p>
      ) : (
        <p className="mt-2 text-[11px] text-[var(--text-subtle)]">
          Enter to send, Shift + Enter for a new line.
        </p>
      )}
    </div>
  )
}
