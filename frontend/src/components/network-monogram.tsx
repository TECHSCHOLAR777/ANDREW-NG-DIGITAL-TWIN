import { cn } from "@/lib/utils"

/**
 * The brand monogram: a small node-and-link network rather than a generic "AN"
 * square. It rhymes with the particle portrait and the Context Graph — the twin
 * is a presence reconstructed from connected evidence — so the mark carries the
 * same idea at favicon scale.
 *
 * One node is the bio-orange accent (active intelligence); the rest are drawn
 * in currentColor so the mark inherits its surrounding text colour and works in
 * both themes without per-theme overrides.
 */
export function NetworkMonogram({
  className,
  ...props
}: React.SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden
      className={cn("size-6", className)}
      {...props}
    >
      {/* Links (under the nodes) */}
      <g stroke="currentColor" strokeWidth="1.1" opacity="0.5">
        <line x1="6" y1="7" x2="12" y2="12" />
        <line x1="12" y1="12" x2="18" y2="6" />
        <line x1="12" y1="12" x2="7" y2="18" />
        <line x1="12" y1="12" x2="18" y2="17" />
      </g>
      {/* Nodes */}
      <circle cx="12" cy="12" r="2.4" fill="currentColor" />
      <circle cx="6" cy="7" r="1.5" fill="currentColor" opacity="0.85" />
      <circle cx="7" cy="18" r="1.5" fill="currentColor" opacity="0.85" />
      <circle cx="18" cy="17" r="1.5" fill="currentColor" opacity="0.85" />
      {/* The one active node carries the brand accent. */}
      <circle cx="18" cy="6" r="1.8" fill="var(--brand)" />
    </svg>
  )
}
