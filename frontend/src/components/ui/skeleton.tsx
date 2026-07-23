import { cn } from "@/lib/utils"

/**
 * Shape-accurate loading placeholder.
 *
 * Uses a tonal surface, not a white block, so it works in both themes and
 * never flashes bright on a dark page. The shimmer is a slow opacity pulse
 * that reduced-motion turns into a static tone (handled globally in
 * globals.css), so it stays vestibular-safe.
 */
export function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden
      className={cn(
        "loading-glow rounded-md bg-[var(--surface-alt)]",
        className
      )}
      {...props}
    />
  )
}
