"use client"

import * as React from "react"
import { Moon, Sun } from "lucide-react"

import { cn } from "@/lib/utils"
import { useTheme } from "@/components/theme-provider"

/**
 * Global light/dark control.
 *
 * The label and icon are resolved from the ACTUAL current theme, not the raw
 * preference, so "system" resolving to dark shows a sun (the action) rather
 * than a confusing system glyph. Rendered as a real button with an accessible
 * name and a live-updating aria-label.
 *
 * Guards against a hydration flash: until mounted, it renders a neutral
 * placeholder of the same size so the layout never shifts.
 */
// Hydration-safe "is this the client yet?" flag with no setState-in-effect:
// false during SSR, true on the client's first snapshot.
const noopSubscribe = () => () => {}

export function ThemeToggle({ className }: { className?: string }) {
  const { resolved, toggle } = useTheme()
  const mounted = React.useSyncExternalStore(
    noopSubscribe,
    () => true,
    () => false
  )

  const next = resolved === "dark" ? "light" : "dark"

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={mounted ? `Switch to ${next} theme` : "Toggle theme"}
      title={mounted ? `Switch to ${next} theme` : undefined}
      className={cn(
        "grid size-9 place-items-center rounded-full border border-[var(--border)]",
        "text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--text)]",
        className
      )}
    >
      {mounted && resolved === "dark" ? (
        <Sun className="size-4" />
      ) : (
        <Moon className="size-4" />
      )}
    </button>
  )
}
