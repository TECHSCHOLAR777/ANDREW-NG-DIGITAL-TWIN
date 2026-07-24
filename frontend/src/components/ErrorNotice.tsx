"use client";

// components/ErrorNotice.tsx
// ─────────────────────────────────────────────────────────────────────────────
// Failures used to arrive as an assistant message:
//
//   "Error communicating with backend: Server error (502): ..."
//
// So the tutor broke character to deliver a stack-trace paraphrase, in the same
// bubble style as teaching, and every failure looked identical. A rate limit, a
// bad key and a dead backend are three different problems with three different
// remedies, and the user got the same wall of text for all of them with no
// action to take.
//
// This classifies the failure, says what happened in plain language, and offers
// exactly one thing to do about it.
// ─────────────────────────────────────────────────────────────────────────────

import React from "react";
import { AlertCircle, KeyRound, Clock, WifiOff, RefreshCw } from "lucide-react";

export type ErrorKind = "auth" | "config" | "rate_limit" | "offline" | "server" | "unknown";

export interface ChatError {
  kind: ErrorKind;
  message: string;
  retryAfterSeconds?: number;
}

/** Map a thrown error or HTTP status onto something actionable. */
export function classifyError(status: number | null, detail: string): ChatError {
  const text = (detail || "").toLowerCase();

  if (text.includes("api key is required") || text.includes("no api key")) {
    return {
      kind: "config",
      message: "Add your Gemini API key in Settings to start chatting.",
    };
  }
  if (status === 401) {
    return {
      kind: "auth",
      message: "Sign in to continue.",
    };
  }
  if (status === 429 || text.includes("rate limit") || text.includes("quota")) {
    const match = detail.match(/(\d+)\s*second/);
    return {
      kind: "rate_limit",
      message: "Too many requests. Wait a moment and try again.",
      retryAfterSeconds: match ? parseInt(match[1], 10) : 30,
    };
  }
  if (status === null || text.includes("failed to fetch") || text.includes("networkerror")) {
    return {
      kind: "offline",
      message: "Could not reach the server. Check your connection.",
    };
  }
  if (status && status >= 500) {
    return {
      kind: "server",
      message: "The server ran into a problem handling that.",
    };
  }
  return { kind: "unknown", message: detail || "Something went wrong." };
}

const ICONS: Record<ErrorKind, React.ComponentType<{ className?: string }>> = {
  auth: KeyRound,
  config: KeyRound,
  rate_limit: Clock,
  offline: WifiOff,
  server: AlertCircle,
  unknown: AlertCircle,
};

interface Props {
  error: ChatError;
  onRetry?: () => void;
  onOpenSettings?: () => void;
  onDismiss?: () => void;
}

export function ErrorNotice({ error, onRetry, onOpenSettings, onDismiss }: Props) {
  const Icon = ICONS[error.kind];
  const [countdown, setCountdown] = React.useState(error.retryAfterSeconds ?? 0);

  React.useEffect(() => {
    if (error.kind !== "rate_limit" || countdown <= 0) return;
    const id = setTimeout(() => setCountdown((c) => c - 1), 1000);
    return () => clearTimeout(id);
  }, [countdown, error.kind]);

  return (
    // role="alert" so a screen reader announces the failure. Previously nothing
    // was announced at all: a blind user asked a question and heard silence.
    <div
      role="alert"
      className="flex items-start gap-3 rounded-xl border px-4 py-3 text-[13px]"
      style={{
        background: "var(--danger-soft)",
        borderColor: "var(--danger-border)",
        color: "var(--danger)",
      }}
    >
      <Icon className="w-4 h-4 mt-0.5 flex-shrink-0" />

      <div className="flex-1 min-w-0">
        <p className="font-medium">{error.message}</p>

        {error.kind === "config" && (
          <p className="mt-1 opacity-90">
            Your key stays in this browser and is sent only to Google, never stored
            on the server.
          </p>
        )}
        {error.kind === "offline" && (
          process.env.NEXT_PUBLIC_API_BASE_URL ? (
            <p className="mt-1 opacity-90 text-[12px]">
              The backend may be waking from sleep. Wait a moment, then try again.
            </p>
          ) : (
            <p className="mt-1 opacity-90 font-mono text-[12px]">
              python -m uvicorn backend.app.main:app --reload
            </p>
          )
        )}
        {error.kind === "rate_limit" && countdown > 0 && (
          <p className="mt-1 opacity-90">Try again in {countdown}s.</p>
        )}

        <div className="flex flex-wrap items-center gap-2 mt-2">
          {error.kind === "config" && onOpenSettings && (
            <button
              onClick={onOpenSettings}
              className="px-2.5 py-1 rounded-lg text-[12px] font-medium border transition"
              style={{ borderColor: "var(--danger-border)" }}
            >
              Add your key
            </button>
          )}
          {error.kind === "auth" && (
            <a
              href="/login"
              className="px-2.5 py-1 rounded-lg text-[12px] font-medium border transition inline-block"
              style={{ borderColor: "var(--danger-border)" }}
            >
              Sign in
            </a>
          )}
          {onRetry && error.kind !== "auth" && error.kind !== "config" && (
            <button
              onClick={onRetry}
              disabled={error.kind === "rate_limit" && countdown > 0}
              className="px-2.5 py-1 rounded-lg text-[12px] font-medium border transition disabled:opacity-50 inline-flex items-center gap-1"
              style={{ borderColor: "var(--danger-border)" }}
            >
              <RefreshCw className="w-3 h-3" />
              Try again
            </button>
          )}
          {onDismiss && (
            <button
              onClick={onDismiss}
              className="px-2.5 py-1 rounded-lg text-[12px] opacity-80 hover:opacity-100 transition"
            >
              Dismiss
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export default ErrorNotice;
