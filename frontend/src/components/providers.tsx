"use client"

import { SessionProvider } from "next-auth/react"

import { ThemeProvider } from "@/components/theme-provider"

/**
 * Client providers shared by every route: the auth session and the theme.
 * Kept in one client boundary so the server layout stays a server component.
 */
export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider>
      <ThemeProvider>{children}</ThemeProvider>
    </SessionProvider>
  )
}
