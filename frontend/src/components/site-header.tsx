"use client"

import * as React from "react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { useSession, signOut } from "next-auth/react"
import { Menu, X } from "lucide-react"

import { cn } from "@/lib/utils"
import { NetworkMonogram } from "@/components/network-monogram"
import { ThemeToggle } from "@/components/theme-toggle"

/**
 * Public navigation.
 *
 * Two destinations, not eight: the product has one thing to explain and one
 * thing to do, so a wide menu would invent structure that does not exist. The
 * bar is a real responsive surface — a floating glass pill on desktop, a
 * compact menu sheet on mobile — built on the unified theme tokens so it reads
 * correctly in light and dark. It grows slightly more opaque after scrolling so
 * it stays legible over the animated hero.
 */
const TABS = [
  { href: "/", label: "Overview" },
  { href: "/understand", label: "How it works" },
] as const

export function SiteHeader() {
  const pathname = usePathname()
  const { status } = useSession()
  const authed = status === "authenticated"
  const [scrolled, setScrolled] = React.useState(false)
  const [menuOpen, setMenuOpen] = React.useState(false)

  React.useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8)
    onScroll()
    window.addEventListener("scroll", onScroll, { passive: true })
    return () => window.removeEventListener("scroll", onScroll)
  }, [])

  // Escape closes the mobile menu.
  React.useEffect(() => {
    if (!menuOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenuOpen(false)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [menuOpen])

  return (
    <header className="fixed inset-x-0 top-0 z-50">
      <div
        className={cn(
          "mx-auto mt-4 flex w-[min(1100px,calc(100%-2rem))] items-center justify-between",
          "rounded-full border px-2 py-2 transition-colors duration-200",
          "border-[var(--border)] backdrop-blur-xl",
          scrolled
            ? "bg-[var(--surface-glass)] shadow-[0_8px_30px_-12px_var(--glass-shadow)]"
            : "bg-[color-mix(in_srgb,var(--surface)_45%,transparent)]"
        )}
      >
        <Link
          href="/"
          className="flex items-center gap-2.5 rounded-full px-3 py-1.5 text-sm font-medium text-[var(--text)] transition-colors hover:text-[var(--brand)]"
        >
          <NetworkMonogram className="size-6 text-[var(--text)]" />
          <span className="hidden sm:inline">Andrew Ng Digital Twin</span>
          <span className="sm:hidden">Digital Twin</span>
        </Link>

        {/* Desktop nav */}
        <nav className="hidden items-center gap-1 sm:flex">
          {TABS.map((tab) => {
            const active = pathname === tab.href
            return (
              <Link
                key={tab.href}
                href={tab.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "rounded-full px-4 py-1.5 text-sm transition-colors",
                  active
                    ? "bg-[var(--surface-hover)] text-[var(--text)]"
                    : "text-[var(--text-muted)] hover:text-[var(--text)]"
                )}
              >
                {tab.label}
              </Link>
            )
          })}
          <ThemeToggle className="ml-1" />
          {authed ? (
            <>
              <button
                type="button"
                onClick={() => signOut({ callbackUrl: "/" })}
                className="rounded-full px-3.5 py-1.5 text-sm text-[var(--text-muted)] transition-colors hover:text-[var(--text)]"
              >
                Sign out
              </button>
              <Link
                href="/app"
                className="ml-1 rounded-full bg-[var(--brand)] px-4 py-1.5 text-sm font-medium text-[var(--brand-text)] transition-opacity hover:opacity-90"
              >
                Open the Twin
              </Link>
            </>
          ) : (
            <Link
              href="/login"
              className="ml-1 rounded-full bg-[var(--brand)] px-4 py-1.5 text-sm font-medium text-[var(--brand-text)] transition-opacity hover:opacity-90"
            >
              Enter the Twin
            </Link>
          )}
        </nav>

        {/* Mobile controls */}
        <div className="flex items-center gap-1 sm:hidden">
          <ThemeToggle />
          <button
            type="button"
            aria-label={menuOpen ? "Close menu" : "Open menu"}
            aria-expanded={menuOpen}
            aria-controls="mobile-menu"
            onClick={() => setMenuOpen((v) => !v)}
            className="grid size-9 place-items-center rounded-full border border-[var(--border)] text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--text)]"
          >
            {menuOpen ? <X className="size-4" /> : <Menu className="size-4" />}
          </button>
        </div>
      </div>

      {/* Mobile menu sheet */}
      {menuOpen && (
        <div
          id="mobile-menu"
          className="mx-auto mt-2 w-[min(1100px,calc(100%-2rem))] rounded-2xl border border-[var(--border)] bg-[var(--surface-glass)] p-2 shadow-[0_8px_30px_-12px_var(--glass-shadow)] backdrop-blur-xl sm:hidden"
        >
          <nav className="flex flex-col gap-1">
            {TABS.map((tab) => {
              const active = pathname === tab.href
              return (
                <Link
                  key={tab.href}
                  href={tab.href}
                  aria-current={active ? "page" : undefined}
                  onClick={() => setMenuOpen(false)}
                  className={cn(
                    "rounded-xl px-4 py-2.5 text-sm transition-colors",
                    active
                      ? "bg-[var(--surface-hover)] text-[var(--text)]"
                      : "text-[var(--text-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--text)]"
                  )}
                >
                  {tab.label}
                </Link>
              )
            })}
            {authed ? (
              <>
                <Link
                  href="/app"
                  onClick={() => setMenuOpen(false)}
                  className="mt-1 rounded-xl bg-[var(--brand)] px-4 py-2.5 text-center text-sm font-medium text-[var(--brand-text)] transition-opacity hover:opacity-90"
                >
                  Open the Twin
                </Link>
                <button
                  type="button"
                  onClick={() => {
                    setMenuOpen(false)
                    signOut({ callbackUrl: "/" })
                  }}
                  className="rounded-xl px-4 py-2.5 text-left text-sm text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-hover)] hover:text-[var(--text)]"
                >
                  Sign out
                </button>
              </>
            ) : (
              <Link
                href="/login"
                onClick={() => setMenuOpen(false)}
                className="mt-1 rounded-xl bg-[var(--brand)] px-4 py-2.5 text-center text-sm font-medium text-[var(--brand-text)] transition-opacity hover:opacity-90"
              >
                Enter the Twin
              </Link>
            )}
          </nav>
        </div>
      )}
    </header>
  )
}
