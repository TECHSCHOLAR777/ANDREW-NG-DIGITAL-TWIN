import {
  ChevronDown,
  Key,
  Plus,
  Sliders,
  Trash2,
  X,
} from "lucide-react"

import { NetworkMonogram } from "@/components/network-monogram"
import type { ChatSession } from "@/app/app/chat-types"

/**
 * The left conversation rail: identity, new conversation, a collapsed settings
 * surface (API key, speaking speed, memory reset), and the session list.
 *
 * Width follows the spec (about 264px) rather than the old 320px that squeezed
 * the transcript on laptops. Presentational: every action is a callback.
 */
export function SessionRail({
  sessions,
  activeSessionId,
  geminiKey,
  ttsSpeed,
  settingsOpen,
  mobileVisible,
  onCloseMobile,
  onNewChat,
  onToggleSettings,
  onSaveKey,
  onSetTtsSpeed,
  onResetMemory,
  onSelectSession,
  onDeleteChat,
}: {
  sessions: ChatSession[]
  activeSessionId: string | null
  geminiKey: string
  ttsSpeed: number
  settingsOpen: boolean
  mobileVisible: boolean
  onCloseMobile: () => void
  onNewChat: () => void
  onToggleSettings: () => void
  onSaveKey: (v: string) => void
  onSetTtsSpeed: (v: number) => void
  onResetMemory: () => void
  onSelectSession: (id: string) => void
  onDeleteChat: (id: string, e: React.MouseEvent) => void
}) {
  return (
    <div
      className={`${mobileVisible ? "flex" : "hidden"} lg:flex
        absolute lg:relative inset-2 lg:inset-auto z-30 lg:z-auto
        w-auto lg:w-[264px] lg:flex-shrink-0
        bg-[var(--surface)] border border-[var(--border)] rounded-2xl shadow-lg lg:shadow-sm
        flex-col overflow-hidden`}
    >
      <div className="p-5 border-b border-[var(--border)] flex items-center gap-3">
        <NetworkMonogram className="w-5 h-5 flex-shrink-0 text-[var(--text)]" />
        <div className="min-w-0 flex-1">
          <h1 className="font-semibold text-[14px] text-[var(--text)]">
            Andrew Ng
          </h1>
          <p className="text-[11px] text-[var(--text-muted)] font-normal">
            Unofficial AI recreation
          </p>
        </div>
        <button
          onClick={onCloseMobile}
          className="lg:hidden p-1.5 rounded-lg border border-[var(--border)] text-[var(--text-muted)] hover:bg-[var(--bg)]"
          aria-label="Close conversations"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="p-4">
        <button
          onClick={onNewChat}
          className="w-full bg-[var(--brand)] hover:bg-[var(--brand-hover)] text-[var(--brand-text)] font-medium text-[13px] py-2.5 rounded-lg flex items-center justify-center gap-2 transition shadow-sm"
        >
          <Plus className="w-4 h-4" />
          New conversation
        </button>
      </div>

      <div className="px-4 pb-2">
        <button
          onClick={onToggleSettings}
          aria-expanded={settingsOpen}
          aria-controls="settings-panel"
          className="w-full flex items-center justify-between text-[12px] text-[var(--text-muted)] hover:text-[var(--text)] py-1.5 transition"
        >
          <span className="flex items-center gap-1.5">
            <Sliders className="w-3.5 h-3.5" />
            Settings
          </span>
          <span className="flex items-center gap-1.5">
            {!geminiKey.trim() && (
              <span
                className="text-[10px] px-1.5 py-0.5 rounded-full border"
                style={{
                  background: "var(--warn-soft)",
                  borderColor: "var(--warn-border)",
                  color: "var(--warn)",
                }}
              >
                key needed
              </span>
            )}
            <ChevronDown
              className={`w-3.5 h-3.5 transition-transform ${
                settingsOpen ? "rotate-180" : ""
              }`}
            />
          </span>
        </button>
      </div>

      {settingsOpen && (
        <div
          id="settings-panel"
          className="px-4 pb-4 flex flex-col gap-4 border-b border-[var(--border)]"
        >
          <div className="flex flex-col gap-2">
            <label
              htmlFor="gemini-key"
              className="text-[11px] font-medium text-[var(--text-muted)] flex items-center gap-1.5"
            >
              <Key className="w-3.5 h-3.5 text-[var(--brand)]" />
              Your Gemini API key
            </label>
            <input
              id="gemini-key"
              type="password"
              placeholder="Paste your key"
              value={geminiKey}
              onChange={(e) => onSaveKey(e.target.value)}
              aria-describedby="gemini-key-help"
              className="w-full bg-[var(--surface)] border text-[13px] px-3 py-2 rounded-lg text-[var(--text)] placeholder-[var(--text-subtle)] focus:outline-none focus:border-[var(--brand)] transition"
              style={{ borderColor: geminiKey.trim() ? "var(--ok)" : "var(--border)" }}
            />
            <p
              id="gemini-key-help"
              className="text-[11px] text-[var(--text-muted)] leading-snug"
            >
              {geminiKey.trim()
                ? "Saved for this browser tab only. Sent through the backend to generate replies, and not stored."
                : "Get one free at aistudio.google.com. It stays in this browser."}
            </p>
          </div>

          <div className="flex flex-col gap-2">
            <label
              htmlFor="speech-rate"
              className="text-[11px] text-[var(--text-muted)] font-medium flex justify-between"
            >
              <span>Speaking speed</span>
              <span className="text-[var(--brand)]">{ttsSpeed.toFixed(2)}x</span>
            </label>
            <input
              id="speech-rate"
              type="range"
              min="0.8"
              max="1.5"
              step="0.05"
              value={ttsSpeed}
              onChange={(e) => onSetTtsSpeed(parseFloat(e.target.value))}
              className="w-full h-1 bg-[var(--border)] rounded-lg appearance-none cursor-pointer accent-[var(--brand)]"
            />
          </div>

          <button
            onClick={onResetMemory}
            className="w-full border text-[13px] py-2 rounded-lg flex items-center justify-center gap-2 transition"
            style={{ borderColor: "var(--danger-border)", color: "var(--danger)" }}
          >
            <Trash2 className="w-3.5 h-3.5" />
            Forget everything about me
          </button>
        </div>
      )}

      <div className="flex-1 overflow-y-auto px-3 py-2 flex flex-col gap-1.5">
        {sessions.map((session) => {
          const isActive = session.id === activeSessionId
          return (
            <div
              key={session.id}
              onClick={() => onSelectSession(session.id)}
              className={`group px-3 py-2.5 rounded-lg cursor-pointer flex items-center justify-between transition ${
                isActive
                  ? "bg-[var(--brand-soft)] border border-[var(--border)] text-[var(--brand)]"
                  : "hover:bg-[var(--bg)] text-[var(--text-muted)] hover:text-[var(--text)]"
              }`}
            >
              <span className="text-[13px] font-normal truncate max-w-[160px]">
                {session.title}
              </span>
              <button
                onClick={(e) => onDeleteChat(session.id, e)}
                aria-label={`Delete conversation: ${session.title}`}
                className="opacity-0 group-hover:opacity-100 focus-visible:opacity-100 p-1 text-[var(--text-muted)] hover:text-[var(--danger)] transition"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          )
        })}
      </div>
    </div>
  )
}
