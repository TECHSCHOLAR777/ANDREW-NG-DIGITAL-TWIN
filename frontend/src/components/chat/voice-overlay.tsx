"use client"
/* eslint-disable react-hooks/set-state-in-effect */
// The amplitude driver resets state synchronously when the voice state changes
// and updates it from a throttled rAF loop; both are legitimate animation
// synchronisation, not render-time state churn.

import * as React from "react"
import { Minus, Volume2, VolumeX, X } from "lucide-react"

import { AndrewPortrait } from "@/components/andrew-portrait"
import type { VoiceState } from "@/app/app/chat-types"

const PORTRAIT_SRC = "/andrew-portrait.png"

/**
 * The flagship voice experience.
 *
 * A near-full-screen session with the audio-reactive Andrew portrait at its
 * centre, not a small card with a nine-bar meter. The portrait's mouth region
 * reacts while speaking; a supporting waveform sits under it. Listening,
 * thinking, and speaking are each stated plainly, the live transcript follows
 * the answer, and the voice provider (cloned versus browser fallback) and the
 * synthetic-voice provenance are always visible.
 *
 * Presentational only: the page still owns the speech engines, TTS, and the
 * state machine, and the audio pipeline is untouched. The amplitude here is a
 * light visual driver derived from the speaking state (a real Web Audio
 * analyser on the playback path is a later refinement), and it is suppressed
 * under reduced motion.
 */
export function VoiceOverlay({
  voiceState,
  ttsSpeed,
  transcript,
  clonedVoiceAvailable,
  closeRef,
  onExit,
  onInterrupt,
  onMute,
  onSpeedDown,
  onSpeedUp,
}: {
  voiceState: Exclude<VoiceState, "inactive">
  ttsSpeed: number
  transcript: string
  clonedVoiceAvailable: boolean | null
  closeRef: React.RefObject<HTMLButtonElement | null>
  onExit: () => void
  onInterrupt: () => void
  onMute: () => void
  onSpeedDown: () => void
  onSpeedUp: () => void
}) {
  // A gentle amplitude while speaking so the portrait feels alive. Throttled and
  // disabled under reduced motion; the page's audio path is not touched.
  const [amp, setAmp] = React.useState(0)
  React.useEffect(() => {
    if (voiceState !== "speaking") {
      setAmp(0)
      return
    }
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setAmp(0.5)
      return
    }
    const start = performance.now()
    let raf = 0
    let last = 0
    const loop = (t: number) => {
      if (t - last > 40) {
        last = t
        const s = (t - start) / 1000
        setAmp(0.35 + 0.4 * Math.abs(Math.sin(s * 6)) + 0.2 * Math.abs(Math.sin(s * 11)))
      }
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [voiceState])

  const STATE_LABEL: Record<typeof voiceState, string> = {
    listening: "Listening",
    thinking: "Thinking",
    speaking: "Speaking",
  }

  const provider =
    clonedVoiceAvailable === null
      ? "Preparing voice"
      : clonedVoiceAvailable
        ? "Andrew's cloned voice"
        : "Browser voice (fallback)"

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Voice conversation"
      className="fixed inset-0 z-50 flex flex-col bg-[var(--bg)]/95 backdrop-blur-md"
    >
      {/* Atmospheric field behind the portrait */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(60% 50% at 50% 38%, color-mix(in srgb, var(--brand) 10%, transparent), transparent 70%)",
        }}
      />

      {/* Top bar: provenance + provider + controls */}
      <div className="relative flex items-center justify-between px-4 sm:px-6 py-4">
        <div className="flex flex-wrap items-center gap-2 text-[11px]">
          <span className="rounded-full border border-[var(--border)] bg-[var(--surface)] px-2.5 py-1 text-[var(--text-muted)]">
            Synthetic voice
          </span>
          <span className="rounded-full border border-[var(--border)] bg-[var(--surface)] px-2.5 py-1 text-[var(--text-subtle)]">
            Unofficial AI recreation
          </span>
        </div>
        <button
          ref={closeRef}
          onClick={onExit}
          className="grid size-9 place-items-center rounded-full border border-[var(--border)] bg-[var(--surface)] text-[var(--text-muted)] hover:text-[var(--text)] transition"
          title="Exit voice mode"
          aria-label="Exit voice mode"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Center: portrait + state */}
      <div className="relative flex flex-1 flex-col items-center justify-center px-6 min-h-0">
        <AndrewPortrait
          src={PORTRAIT_SRC}
          mode="voice"
          amplitude={amp}
          className="h-[240px] w-[240px] sm:h-[320px] sm:w-[320px]"
        />

        <div
          className={`waveform-container mt-2 ${
            voiceState === "listening"
              ? "waveform-listening"
              : voiceState === "thinking"
                ? "waveform-thinking"
                : "waveform-speaking"
          }`}
          aria-hidden
        >
          {Array.from({ length: 9 }, (_, i) => (
            <div key={i} className={`waveform-bar bar-${i + 1}`} />
          ))}
        </div>

        <p className="mt-3 text-[15px] font-medium text-[var(--text)]">
          {STATE_LABEL[voiceState]}
        </p>
        <p className="mt-1 text-[12px] text-[var(--text-subtle)]">{provider}</p>

        {/* Live transcript */}
        {transcript && (
          <div className="mt-5 max-h-28 w-full max-w-xl overflow-y-auto rounded-xl border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-center text-[14px] leading-relaxed text-[var(--text-muted)]">
            {transcript}
          </div>
        )}

        {/* Live-region announcement for screen readers, without re-reading the
            whole streamed answer. */}
        <div aria-live="polite" className="sr-only">
          {STATE_LABEL[voiceState]}
        </div>
      </div>

      {/* Bottom controls */}
      <div className="relative flex items-center justify-center gap-3 px-6 pb-8 pt-4">
        <button
          onClick={onMute}
          className="grid size-11 place-items-center rounded-full border border-[var(--border)] bg-[var(--surface)] text-[var(--text-muted)] hover:text-[var(--text)] transition"
          title="Mute current speech"
          aria-label="Mute current speech"
        >
          {voiceState === "speaking" ? <Volume2 className="w-4 h-4" /> : <VolumeX className="w-4 h-4" />}
        </button>

        <button
          onClick={onInterrupt}
          className="rounded-full bg-[var(--brand)] px-6 py-3 text-[14px] font-medium text-[var(--brand-text)] hover:opacity-90 transition"
        >
          {voiceState === "listening" ? "Stop listening" : "Tap to interrupt"}
        </button>

        <div className="flex items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--surface)] px-3 py-2">
          <button
            onClick={onSpeedDown}
            aria-label="Slower"
            className="px-1 text-sm font-bold text-[var(--text-muted)] hover:text-[var(--text)]"
          >
            -
          </button>
          <span className="min-w-[34px] text-center text-[12px] font-medium text-[var(--brand)]">
            {ttsSpeed.toFixed(1)}x
          </span>
          <button
            onClick={onSpeedUp}
            aria-label="Faster"
            className="px-1 text-sm font-bold text-[var(--text-muted)] hover:text-[var(--text)]"
          >
            +
          </button>
        </div>

        <button
          onClick={onExit}
          className="grid size-11 place-items-center rounded-full border border-[var(--border)] bg-[var(--surface)] text-[var(--text-muted)] hover:text-[var(--text)] transition"
          title="Minimise to text"
          aria-label="Minimise to text"
        >
          <Minus className="w-4 h-4" />
        </button>
      </div>
    </div>
  )
}
