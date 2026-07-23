import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * A compact status pill for grounding levels, voice state, and provenance.
 *
 * Colour is never the only signal — every chip pairs a token colour with a
 * label and an optional icon (WCAG 2.2). "brand" is reserved for ACTIVE
 * evidence and live state, per the design system's rule that orange means
 * intelligence/activity, not warning. Insufficient evidence uses "neutral",
 * not a red alarm.
 */
type Tone = "neutral" | "brand" | "ok" | "warn" | "danger" | "info"

const TONE: Record<Tone, string> = {
  neutral:
    "text-[var(--text-muted)] bg-[var(--surface-alt)] border-[var(--border)]",
  brand:
    "text-[var(--brand)] bg-[var(--brand-soft)] border-[color-mix(in_srgb,var(--brand)_28%,transparent)]",
  ok: "text-[var(--ok)] bg-[var(--ok-soft)] border-[color-mix(in_srgb,var(--ok)_28%,transparent)]",
  warn: "text-[var(--warn)] bg-[var(--warn-soft)] border-[var(--warn-border)]",
  danger:
    "text-[var(--danger)] bg-[var(--danger-soft)] border-[var(--danger-border)]",
  info: "text-[var(--info)] bg-[var(--info-soft)] border-[color-mix(in_srgb,var(--info)_28%,transparent)]",
}

export interface StatusChipProps
  extends React.HTMLAttributes<HTMLSpanElement> {
  tone?: Tone
  icon?: React.ReactNode
}

export function StatusChip({
  tone = "neutral",
  icon,
  className,
  children,
  ...props
}: StatusChipProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-medium whitespace-nowrap",
        TONE[tone],
        className
      )}
      {...props}
    >
      {icon != null && (
        <span className="grid shrink-0 place-items-center [&>svg]:size-3">
          {icon}
        </span>
      )}
      {children}
    </span>
  )
}
