"use client"

import * as React from "react"
import { motion } from "motion/react"

import { cn } from "@/lib/utils"

/**
 * A segmented control whose active pill slides between options instead of
 * hard-swapping.
 *
 * HOW THE SLIDE WORKS
 * The moving pill is a single element with a shared `layoutId`. When `value`
 * changes, motion sees the same layout node under a new parent and animates
 * the gap between the two positions. There is no manual measuring of offsets,
 * which is what makes this robust to tabs of different widths.
 *
 * WHY GENERIC
 * The chat app has one of these today (Active Chat / Global Map). The design
 * plan calls for more (graph filters, settings sections), so this is written
 * once, typed over the caller's value union, rather than copied per use.
 *
 * ACCESSIBILITY
 * Rendered as a real radiogroup. Arrow keys move between options, which a row
 * of styled buttons does not give you for free.
 */
export interface SlidingTabsOption<T extends string> {
  value: T
  label: React.ReactNode
  /** Optional leading icon. */
  icon?: React.ReactNode
}

export interface SlidingTabsProps<T extends string> {
  options: SlidingTabsOption<T>[]
  value: T
  onValueChange: (value: T) => void
  /** A stable id so multiple instances do not share one animated pill. */
  layoutId?: string
  size?: "sm" | "md"
  className?: string
  "aria-label"?: string
}

export function SlidingTabs<T extends string>({
  options,
  value,
  onValueChange,
  layoutId,
  size = "md",
  className,
  "aria-label": ariaLabel,
}: SlidingTabsProps<T>) {
  // A per-instance id keeps two controls on the same screen from sharing the
  // pill and animating into each other.
  const reactId = React.useId()
  const pillId = layoutId ?? `sliding-tabs-${reactId}`

  const pad = size === "sm" ? "p-0.5" : "p-1"
  const cell =
    size === "sm"
      ? "px-2.5 py-1 text-[11px]"
      : "px-3.5 py-1.5 text-[13px]"

  function onKeyDown(e: React.KeyboardEvent) {
    const dir = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0
    if (!dir) return
    e.preventDefault()
    const i = options.findIndex((o) => o.value === value)
    const next = options[(i + dir + options.length) % options.length]
    onValueChange(next.value)
  }

  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      onKeyDown={onKeyDown}
      className={cn(
        "inline-flex items-center rounded-lg border border-[var(--border)] bg-[var(--surface-alt)]",
        pad,
        className
      )}
    >
      {options.map((opt) => {
        const active = opt.value === value
        return (
          <button
            key={opt.value}
            type="button"
            role="radio"
            aria-checked={active}
            tabIndex={active ? 0 : -1}
            onClick={() => onValueChange(opt.value)}
            className={cn(
              "relative inline-flex items-center gap-1.5 rounded-md font-medium transition-colors",
              cell,
              active
                ? "text-[var(--text)]"
                : "text-[var(--text-muted)] hover:text-[var(--text)]"
            )}
          >
            {active && (
              <motion.span
                layoutId={pillId}
                className="absolute inset-0 rounded-md bg-[var(--surface)] shadow-sm ring-1 ring-[var(--border)]"
                transition={{ type: "spring", stiffness: 380, damping: 32 }}
              />
            )}
            {/* Content sits above the moving pill. */}
            <span className="relative z-10 inline-flex items-center gap-1.5">
              {opt.icon}
              {opt.label}
            </span>
          </button>
        )
      })}
    </div>
  )
}
