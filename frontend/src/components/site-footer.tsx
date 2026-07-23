import Link from "next/link"

import { NetworkMonogram } from "@/components/network-monogram"

/**
 * Shared public footer.
 *
 * Carries the standing unofficial-recreation disclosure at a READABLE weight —
 * the design system is explicit that the disclosure must not hide at extremely
 * low opacity — plus links to how the twin works and the privacy/posture
 * documents. Token-based, so it reads correctly in both themes.
 */
export function SiteFooter() {
  return (
    <footer className="border-t border-[var(--border)]">
      <div className="mx-auto w-[min(1100px,calc(100%-2rem))] py-10">
        <div className="flex flex-col gap-6 sm:flex-row sm:items-start sm:justify-between">
          <div className="max-w-[52ch] space-y-3">
            <div className="flex items-center gap-2 text-[var(--text)]">
              <NetworkMonogram className="size-5" />
              <span className="text-sm font-medium">Andrew Ng Digital Twin</span>
            </div>
            <p className="text-[13px] leading-relaxed text-[var(--text-muted)]">
              An unofficial, academic AI recreation. Not affiliated with,
              endorsed by, or reviewed by Andrew Ng, Stanford, or
              DeepLearning.AI. Responses are generated and are not real
              quotations; the voice is synthetic.
            </p>
          </div>

          <nav className="flex flex-col gap-2 text-[13px]">
            <Link
              href="/understand"
              className="text-[var(--text-muted)] transition-colors hover:text-[var(--text)]"
            >
              How it works
            </Link>
            <Link
              href="/login"
              className="text-[var(--text-muted)] transition-colors hover:text-[var(--text)]"
            >
              Enter the Twin
            </Link>
          </nav>
        </div>
      </div>
    </footer>
  )
}
