"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"

import { cn } from "@/lib/utils"

/**
 * Marketing navigation.
 *
 * Three destinations, not eight. The product has one thing to explain and one
 * thing to do, so a wide menu would be inventing structure that does not exist.
 */
const TABS = [
  { href: "/", label: "Overview" },
  { href: "/understand", label: "How it works" },
] as const

export function SiteHeader() {
  const pathname = usePathname()

  return (
    <header className="fixed inset-x-0 top-0 z-50">
      {/* The blur rather than a solid fill: the hero animates underneath, and
          hiding that behind an opaque bar wastes the one thing worth looking
          at. */}
      <div className="mx-auto mt-4 flex w-[min(1100px,calc(100%-2rem))] items-center justify-between rounded-full border border-white/10 bg-black/40 px-2 py-2 backdrop-blur-xl">
        <Link
          href="/"
          className="flex items-center gap-2.5 rounded-full px-3 py-1.5 text-sm font-medium text-white/90 transition-colors hover:text-white"
        >
          <span className="grid size-6 place-items-center rounded-md bg-white/10 text-[11px] font-semibold text-white">
            AN
          </span>
          <span className="hidden sm:inline">Andrew Ng Digital Twin</span>
          <span className="sm:hidden">Digital Twin</span>
        </Link>

        <nav className="flex items-center gap-1">
          {TABS.map((tab) => {
            const active = pathname === tab.href
            return (
              <Link
                key={tab.href}
                href={tab.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "rounded-full px-3.5 py-1.5 text-sm transition-colors sm:px-4",
                  active
                    ? "bg-white/10 text-white"
                    : "text-white/60 hover:text-white/90"
                )}
              >
                {tab.label}
              </Link>
            )
          })}

          <Link
            href="/login"
            className="ml-1 rounded-full bg-white px-4 py-1.5 text-sm font-medium text-black transition-opacity hover:opacity-90"
          >
            Start using
          </Link>
        </nav>
      </div>
    </header>
  )
}
