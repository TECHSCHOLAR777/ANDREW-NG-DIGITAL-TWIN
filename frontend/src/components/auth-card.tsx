"use client"

import Link from "next/link"
import { useRouter } from "next/navigation"
import * as React from "react"
import { signIn } from "next-auth/react"
import { Eye, EyeOff, Loader2 } from "lucide-react"

import { NetworkMonogram } from "@/components/network-monogram"

/**
 * Login and signup, on one shell.
 *
 * Both flows are real. Signup posts to /api/signup (which creates the account
 * and binds a tenant), then signs the person in. Login calls the Credentials
 * provider directly. On success the person lands in the app. The anonymous
 * tenant the browser was using is offered to signup so guest context carries
 * over. Nothing here is a layout-only placeholder.
 */
const TENANT_KEY = "andrew_ng_tenant_uuid"

export interface AuthCardProps {
  mode: "login" | "signup"
}

export function AuthCard({ mode }: AuthCardProps) {
  const isLogin = mode === "login"
  const router = useRouter()

  const [name, setName] = React.useState("")
  const [email, setEmail] = React.useState("")
  const [password, setPassword] = React.useState("")
  const [context, setContext] = React.useState("")
  const [showPassword, setShowPassword] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(false)

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      if (!isLogin) {
        const anonTenantId =
          typeof window !== "undefined"
            ? window.localStorage.getItem(TENANT_KEY) ?? undefined
            : undefined
        const res = await fetch("/api/signup", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, email, password, context, anonTenantId }),
        })
        if (!res.ok) {
          const data = await res.json().catch(() => ({}))
          setError(data.error ?? "Could not create the account.")
          return
        }
      }

      const result = await signIn("credentials", {
        email,
        password,
        redirect: false,
      })
      if (result?.error) {
        setError(
          isLogin
            ? "That email and password do not match."
            : "Account created, but sign-in failed. Try signing in."
        )
        return
      }
      router.push("/app")
      router.refresh()
    } catch {
      setError("Something went wrong. Please try again.")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="theme-dark flex min-h-[100svh] items-center justify-center bg-[var(--bg)] px-4 py-16 text-[var(--text)]">
      <div className="w-full max-w-[400px]">
        <Link
          href="/"
          className="mb-10 flex items-center justify-center gap-2.5 text-sm text-[var(--text-muted)] transition-colors hover:text-[var(--text)]"
        >
          <NetworkMonogram className="size-6" />
          Andrew Ng Digital Twin
        </Link>

        <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-7 sm:p-8">
          <h1 className="text-2xl font-semibold tracking-[-0.02em]">
            {isLogin ? "Welcome back" : "Create your account"}
          </h1>
          <p className="mt-2 text-sm text-[var(--text-muted)]">
            {isLogin
              ? "Sign in to pick up where you left off."
              : "Your conversations and memory graph are saved to your account."}
          </p>

          {error && (
            <p
              role="alert"
              className="mt-5 rounded-lg border px-3 py-2 text-[13px]"
              style={{
                color: "var(--danger)",
                background: "var(--danger-soft)",
                borderColor: "var(--danger-border)",
              }}
            >
              {error}
            </p>
          )}

          <form className="mt-6 space-y-4" onSubmit={onSubmit}>
            {!isLogin && (
              <Field
                label="Name"
                type="text"
                name="name"
                autoComplete="name"
                placeholder="Ada Lovelace"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            )}
            <Field
              label="Email"
              type="email"
              name="email"
              autoComplete="email"
              placeholder="you@example.com"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <div>
              <label
                htmlFor="password"
                className="mb-1.5 block text-sm text-[var(--text-muted)]"
              >
                Password
              </label>
              <div className="relative">
                <input
                  id="password"
                  name="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete={isLogin ? "current-password" : "new-password"}
                  placeholder={isLogin ? "Your password" : "At least 8 characters"}
                  required
                  minLength={isLogin ? undefined : 8}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface-alt)] px-3.5 py-2.5 pr-10 text-sm text-[var(--text)] placeholder:text-[var(--text-subtle)] focus:border-[var(--brand)] focus:outline-none focus:ring-2 focus:ring-[var(--brand-soft)]"
                />
                <button
                  type="button"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute inset-y-0 right-0 grid w-10 place-items-center text-[var(--text-subtle)] hover:text-[var(--text)]"
                >
                  {showPassword ? (
                    <EyeOff className="size-4" />
                  ) : (
                    <Eye className="size-4" />
                  )}
                </button>
              </div>
            </div>

            {!isLogin && (
              <div>
                <label
                  htmlFor="context"
                  className="mb-1.5 block text-sm text-[var(--text-muted)]"
                >
                  What should the twin remember about you?{" "}
                  <span className="text-[var(--text-subtle)]">(optional)</span>
                </label>
                <textarea
                  id="context"
                  name="context"
                  rows={2}
                  placeholder="Your role, what you are building, or what you want to learn."
                  value={context}
                  onChange={(e) => setContext(e.target.value)}
                  className="w-full resize-none rounded-lg border border-[var(--border)] bg-[var(--surface-alt)] px-3.5 py-2.5 text-sm text-[var(--text)] placeholder:text-[var(--text-subtle)] focus:border-[var(--brand)] focus:outline-none focus:ring-2 focus:ring-[var(--brand-soft)]"
                />
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="flex w-full items-center justify-center gap-2 rounded-lg bg-[var(--brand)] px-4 py-2.5 text-sm font-medium text-[var(--brand-text)] transition-opacity hover:opacity-90 disabled:opacity-60"
            >
              {loading && <Loader2 className="size-4 animate-spin" />}
              {isLogin ? "Sign in" : "Create account"}
            </button>
          </form>
        </div>

        <p className="mt-6 text-center text-sm text-[var(--text-muted)]">
          {isLogin ? "New here? " : "Already have an account? "}
          <Link
            href={isLogin ? "/signup" : "/login"}
            className="text-[var(--text)] underline-offset-4 hover:underline"
          >
            {isLogin ? "Create an account" : "Sign in"}
          </Link>
        </p>

        <p className="mx-auto mt-8 max-w-[38ch] text-center text-xs leading-relaxed text-[var(--text-subtle)]">
          You bring your own Gemini API key. It is sent through the backend to
          generate replies and is never stored.
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
      <label
        htmlFor={id}
        className="mb-1.5 block text-sm text-[var(--text-muted)]"
      >
        {label}
      </label>
      <input
        id={id}
        {...props}
        className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface-alt)] px-3.5 py-2.5 text-sm text-[var(--text)] placeholder:text-[var(--text-subtle)] focus:border-[var(--brand)] focus:outline-none focus:ring-2 focus:ring-[var(--brand-soft)]"
      />
    </div>
  )
}
