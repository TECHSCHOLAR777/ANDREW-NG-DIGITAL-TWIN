"use client"

import * as React from "react"

/**
 * Theme system for the whole product — marketing and app share it.
 *
 * WHY NOT next-themes
 * The contract is small (three modes, one attribute) and we already need a
 * bespoke no-flash script tuned to this app's attribute name. Owning ~70 lines
 * is cheaper than owning a dependency's upgrade surface.
 *
 * THE MODEL
 * `preference` is what the user chose: "light", "dark", or "system".
 * `resolved` is the theme actually on screen after "system" is evaluated.
 * Only `resolved` reaches <html data-theme>, because CSS and the canvas
 * portrait need a concrete answer, never "system".
 *
 * WHY useSyncExternalStore
 * Theme lives in two external stores — localStorage and the OS colour-scheme
 * media query. useSyncExternalStore is React's supported way to read those
 * without a hydration flash and without setState-in-effect cascades: the
 * server snapshot is a sane default, the client subscribes to both sources,
 * and the pre-paint init script already applied the right attribute.
 */
export type ThemePreference = "light" | "dark" | "system"
export type ResolvedTheme = "light" | "dark"

const STORAGE_KEY = "andrew-twin-theme"
const CHANGE_EVENT = "andrew-twin-theme-change"

interface ThemeContextValue {
  preference: ThemePreference
  resolved: ResolvedTheme
  setPreference: (p: ThemePreference) => void
  /** Convenience: flip between the two concrete themes. */
  toggle: () => void
}

const ThemeContext = React.createContext<ThemeContextValue | undefined>(undefined)

function systemTheme(): ResolvedTheme {
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light"
}

function readPreference(): ThemePreference {
  const stored = window.localStorage.getItem(STORAGE_KEY)
  return stored === "light" || stored === "dark" || stored === "system"
    ? stored
    : "system"
}

/** Subscribe to both external theme sources plus our own change broadcast. */
function subscribe(onChange: () => void): () => void {
  const mq = window.matchMedia("(prefers-color-scheme: dark)")
  mq.addEventListener("change", onChange)
  window.addEventListener("storage", onChange)
  window.addEventListener(CHANGE_EVENT, onChange)
  return () => {
    mq.removeEventListener("change", onChange)
    window.removeEventListener("storage", onChange)
    window.removeEventListener(CHANGE_EVENT, onChange)
  }
}

// Snapshots return primitives, so useSyncExternalStore's default equality
// check never loops.
const getPreferenceSnapshot = (): ThemePreference => readPreference()
const getResolvedSnapshot = (): ResolvedTheme => {
  const pref = readPreference()
  return pref === "system" ? systemTheme() : pref
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const preference = React.useSyncExternalStore(
    subscribe,
    getPreferenceSnapshot,
    () => "system" as ThemePreference
  )
  const resolved = React.useSyncExternalStore(
    subscribe,
    getResolvedSnapshot,
    () => "dark" as ResolvedTheme
  )

  // Reflect the resolved theme onto the DOM (updating an external system is
  // exactly what effects are for).
  React.useEffect(() => {
    document.documentElement.setAttribute("data-theme", resolved)
  }, [resolved])

  const setPreference = React.useCallback((p: ThemePreference) => {
    window.localStorage.setItem(STORAGE_KEY, p)
    window.dispatchEvent(new Event(CHANGE_EVENT))
  }, [])

  const toggle = React.useCallback(() => {
    setPreference(resolved === "dark" ? "light" : "dark")
  }, [resolved, setPreference])

  const value = React.useMemo<ThemeContextValue>(
    () => ({ preference, resolved, setPreference, toggle }),
    [preference, resolved, setPreference, toggle]
  )

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

export function useTheme(): ThemeContextValue {
  const ctx = React.useContext(ThemeContext)
  if (!ctx) throw new Error("useTheme must be used within <ThemeProvider>")
  return ctx
}

/**
 * Runs before first paint. Dependency-free and tiny because it is inlined into
 * the document head as a raw string. Any throw must not block render, hence the
 * try/catch fallback to dark.
 */
export const themeInitScript = `
(function(){
  try {
    var k = "${STORAGE_KEY}";
    var p = localStorage.getItem(k);
    var sys = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    var t = (p === "light" || p === "dark") ? p : sys;
    document.documentElement.setAttribute("data-theme", t);
  } catch (e) {
    document.documentElement.setAttribute("data-theme", "dark");
  }
})();
`
