import * as React from "react"
import { X } from "lucide-react"

import type { VoiceState } from "@/app/app/chat-types"

/**
 * The hands-free voice modal.
 *
 * Presentational: the page owns the voice state machine, speech engines, and
 * TTS. This renders the waveform, the interrupt/exit controls, the live state
 * label, and the speed control, and reports intent through callbacks. Focus
 * trapping and Escape handling remain in the page effect that owns the refs.
 */
export function VoiceOverlay({
  voiceState,
  ttsSpeed,
  closeRef,
  onExit,
  onCenterAction,
  onSpeedDown,
  onSpeedUp,
}: {
  voiceState: Exclude<VoiceState, "inactive">
  ttsSpeed: number
  closeRef: React.RefObject<HTMLButtonElement | null>
  onExit: () => void
  onCenterAction: () => void
  onSpeedDown: () => void
  onSpeedUp: () => void
}) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Voice conversation"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm transition-all duration-300"
    >
      <div className="relative max-w-[400px] w-full bg-[var(--surface)] rounded-2xl border border-[var(--border)] shadow-2xl p-10 flex flex-col items-center">
        <button
          ref={closeRef}
          onClick={onExit}
          className="absolute top-4 right-4 w-7 h-7 flex items-center justify-center rounded-full border border-[var(--border)] hover:bg-[var(--surface-hover)] text-[var(--text-muted)] hover:text-[var(--text)] transition cursor-pointer"
          title="Exit voice mode"
          aria-label="Exit voice mode"
        >
          <X className="w-4 h-4" />
        </button>

        <div
          className={`waveform-container mb-8 ${
            voiceState === "listening"
              ? "waveform-listening"
              : voiceState === "thinking"
                ? "waveform-thinking"
                : "waveform-speaking"
          }`}
        >
          {Array.from({ length: 9 }, (_, i) => (
            <div key={i} className={`waveform-bar bar-${i + 1}`} />
          ))}
        </div>

        <button
          onClick={onCenterAction}
          className="px-6 py-2.5 bg-[var(--brand)] hover:opacity-90 text-[var(--brand-text)] rounded-full text-[13px] font-medium mb-6 transition"
        >
          {voiceState === "listening" ? "Stop listening" : "Tap to interrupt"}
        </button>

        <p className="text-[13px] text-[var(--text-muted)] font-normal mb-6 text-center capitalize">
          {voiceState}...
        </p>

        <div className="flex items-center gap-3 bg-[var(--bg)] border border-[var(--border)] px-3 py-1.5 rounded-full">
          <button
            onClick={onSpeedDown}
            aria-label="Slower"
            className="text-xs text-[var(--text-muted)] hover:text-[var(--text)] px-1 font-bold cursor-pointer"
          >
            -
          </button>
          <span className="text-[12px] text-[var(--brand)] font-medium min-w-[32px] text-center">
            {ttsSpeed.toFixed(1)}x
          </span>
          <button
            onClick={onSpeedUp}
            aria-label="Faster"
            className="text-xs text-[var(--text-muted)] hover:text-[var(--text)] px-1 font-bold cursor-pointer"
          >
            +
          </button>
        </div>
      </div>
    </div>
  )
}
