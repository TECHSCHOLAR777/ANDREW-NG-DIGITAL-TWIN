"use client"

import Link from "next/link"
import * as React from "react"

/**
 * Shared shell for the login and signup screens.
 *
 * The two pages differ only in copy and which link they offer, so the frame,
 * the BYOK note, and the layout live here once. The actual credential handling
 * is wired in phase 4 (Auth.js). For now the form posts nowhere; the button
 * carries a disabled note so it never looks broken or silently does nothing.
 */
export interface AuthCardProps {
  mode: "login" | "signup"
}

export function AuthCard({ mode }: AuthCardProps) {
  const isLogin = mode === "login"

  return (
    <div className="theme-dark flex min-h-[100svh] items-center justify-center bg-[var(--bg)] px-4 py-16 text-[var(--text)]">
      <div className="w-full max-w-[400px]">
        <Link
          href="/"
          className="mb-10 flex items-center justify-center gap-2.5 text-sm text-white/60 transition-colors hover:text-white"
        >
          <span className="grid size-7 place-items-center rounded-md bg-white/10 text-xs font-semibold text-white">
            AN
          </span>
          Andrew Ng Digital Twin
        </Link>

        <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-7 sm:p-8">
          <h1 className="text-2xl font-semibold tracking-[-0.02em]">
            {isLogin ? "Welcome back" : "Create your account"}
          </h1>
          <p className="mt-2 text-sm text-white/50">
            {isLogin
              ? "Sign in to pick up where your learning left off."
              : "Your progress and knowledge graph are saved to your account."}
          </p>

          <form className="mt-7 space-y-4" onSubmit={(e) => e.preventDefault()}>
            {!isLogin && (
              <Field
                label="Name"
                type="text"
                name="name"
                autoComplete="name"
                placeholder="Ada Lovelace"
              />
            )}
            <Field
              label="Email"
              type="email"
              name="email"
              autoComplete="email"
              placeholder="you@example.com"
            />
            <Field
              label="Password"
              type="password"
              name="password"
              autoComplete={isLogin ? "current-password" : "new-password"}
              placeholder="••••••••"
            />

            <button
              type="submit"
              disabled
              className="w-full cursor-not-allowed rounded-lg bg-white/90 px-4 py-2.5 text-sm font-medium text-black opacity-60"
              title="Authentication is not wired up yet"
            >
              {isLogin ? "Sign in" : "Create account"}
            </button>
            <p className="text-center text-xs text-white/35">
              Sign-in is being connected. This screen is the layout only.
            </p>
          </form>
        </div>

        <p className="mt-6 text-center text-sm text-white/50">
          {isLogin ? "New here? " : "Already have an account? "}
          <Link
            href={isLogin ? "/signup" : "/login"}
            className="text-white underline-offset-4 hover:underline"
          >
            {isLogin ? "Create an account" : "Sign in"}
          </Link>
        </p>

        <p className="mx-auto mt-8 max-w-[36ch] text-center text-xs leading-relaxed text-white/30">
          You bring your own Gemini API key. It stays in your browser and is
          never stored on the server.
        </p>
      </div>
    </div>
  )
}

function Field({
  label,
  ...props
}: { label: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  const id = React.useId()
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-sm text-white/70">
        {label}
      </label>
      <input
        id={id}
        {...props}
        className="w-full rounded-lg border border-white/10 bg-white/[0.04] px-3.5 py-2.5 text-sm text-white placeholder:text-white/25 focus:border-white/25 focus:outline-none focus:ring-2 focus:ring-white/10"
      />
    </div>
  )
}
