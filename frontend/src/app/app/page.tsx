"use client";
/* eslint-disable react-hooks/set-state-in-effect, react-hooks/immutability */

import React, { useState, useEffect, useRef } from "react";
import { useSession } from "next-auth/react";

import { ErrorNotice, classifyError, type ChatError } from "@/components/ErrorNotice";
import { SessionRail } from "@/components/chat/session-rail";
import { ConversationHeader } from "@/components/chat/conversation-header";
import { MessageBubble } from "@/components/chat/message-bubble";
import { Composer } from "@/components/chat/composer";
import { ContextGraphPanel } from "@/components/chat/context-graph-panel";
import { VoiceOverlay } from "@/components/chat/voice-overlay";
import {
  readWavAmplitude,
  type WavAmplitudeEnvelope,
} from "@/lib/wavAmplitude";
import { selectPreferredBrowserVoice } from "@/lib/browserVoice";
import type { TripletRow } from "@/types/graph";
import {
  KEY_LOCAL_STORAGE_GEMINI,
  KEY_LOCAL_STORAGE_TENANT,
  KEY_LOCAL_STORAGE_ACTIVE,
  API_BASE_URL,
  SUGGESTED_QUESTIONS,
  type Message,
  type GraphContextNode,
  type ChatSession,
  type RetrievedChunk,
  type VoiceLatencyPhase,
  type VoiceProvider,
  type VoiceState,
  type SpeechRecognitionLike,
  type SpeechRecognitionResultEventLike,
  type SpeechRecognitionErrorEventLike,
  type SpeechWindow,
} from "@/app/app/chat-types";

const INTERACTIVE_TTS_DEADLINE_MS = 8_000;
const READ_ALOUD_TTS_DEADLINE_MS = 20_000;
const CHAT_TURN_DEADLINE_MS = 120_000;

export default function ChatPage() {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [userInput, setUserInput] = useState("");
  const [geminiKey, setGeminiKey] = useState("");
  const [tenantId, setTenantId] = useState("");
  // When signed in, the account owns a tenant that follows the user across
  // devices. A guest keeps the per-browser tenant generated below.
  const { data: authSession, status: authStatus } = useSession();
  const [graphView, setGraphView] = useState<"session" | "global">("session");
  const [isLoading, setIsLoading] = useState(false);
  const [waitElapsedSeconds, setWaitElapsedSeconds] = useState(0);
  const [isSyncingGraph, setIsSyncingGraph] = useState(false);

  // Which panel is visible below the lg breakpoint. On a phone this is a chat
  // app with two drawers; the three-column workspace is a desktop luxury and
  // holding onto it at small sizes is how the old fixed-width layout became
  // unusable under about 1200px.
  const [mobilePanel, setMobilePanel] = useState<"chat" | "sessions" | "graph">("chat");

  // Failures render as a dedicated notice, not as a message from the tutor.
  const [chatError, setChatError] = useState<ChatError | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [lastMessage, setLastMessage] = useState<string>("");
  
  // Voice controls
  const [readAloudEnabled, setReadAloudEnabled] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [voiceState, setVoiceState] = useState<VoiceState>("inactive");
  
  // Pedagogical Speed settings
  const [ttsSpeed, setTtsSpeed] = useState<number>(1.0);

  // Ref handles for speech engines
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const voiceStateRef = useRef<string>("inactive");
  const recognitionRestartTimerRef = useRef<number | null>(null);
  const recognitionRetryCountRef = useRef(0);
  const recognitionPermissionBlockedRef = useRef(false);
  const chatAbortRef = useRef<AbortController | null>(null);
  const chatAbortReasonRef = useRef<"interrupt" | "timeout" | null>(null);
  const sessionsRestoreGenerationRef = useRef(0);

  // Always-fresh handle to submitDialogueMessage for browser speech callbacks.
  // The recognition handlers are registered once on mount; without this ref
  // they capture the FIRST render's closure (activeSession=null, tenantId=""),
  // which silently discarded every voice-mode utterance.
  const submitRef = useRef<(text: string) => Promise<void>>(async () => {});

  // Custom Cloned TTS Audio Player Refs
  const currentAudioRef = useRef<HTMLAudioElement | null>(null);
  const ttsAbortRef = useRef<AbortController | null>(null);
  const isPlayingRef = useRef<boolean>(false);
  const voiceAmplitudeFrameRef = useRef<number | null>(null);
  const [voiceAmplitude, setVoiceAmplitude] = useState(0);
  const [voiceLatencyPhase, setVoiceLatencyPhase] =
    useState<VoiceLatencyPhase>("idle");
  const [voiceProvider, setVoiceProvider] =
    useState<VoiceProvider>("preparing");
  const voiceProviderRef = useRef<VoiceProvider>("preparing");
  const ttsStatusGenerationRef = useRef(0);
  const browserVoiceRef = useRef<SpeechSynthesisVoice | null>(null);
  const [voiceInputIssue, setVoiceInputIssue] = useState<string | null>(null);

  const updateVoiceProvider = (provider: VoiceProvider) => {
    voiceProviderRef.current = provider;
    setVoiceProvider(provider);
  };

  const refreshVoiceProvider = async (force = false) => {
    const generation = ++ttsStatusGenerationRef.current;
    if (force) updateVoiceProvider("preparing");
    try {
      const response = await fetch(
        `${API_BASE_URL}/api/v1/chat/tts/status${force ? "?refresh=true" : ""}`
      );
      const status = response.ok ? await response.json() : null;
      if (generation !== ttsStatusGenerationRef.current) return;
      updateVoiceProvider(status?.available ? "clone" : "browser");
    } catch {
      if (generation === ttsStatusGenerationRef.current) {
        updateVoiceProvider("browser");
      }
    }
  };

  const clearRecognitionRestart = () => {
    if (recognitionRestartTimerRef.current !== null) {
      window.clearTimeout(recognitionRestartTimerRef.current);
      recognitionRestartTimerRef.current = null;
    }
  };

  const scheduleRecognitionStart = (delayMs = 0) => {
    clearRecognitionRestart();
    if (
      voiceStateRef.current !== "listening" ||
      recognitionPermissionBlockedRef.current
    ) {
      return;
    }
    recognitionRestartTimerRef.current = window.setTimeout(() => {
      recognitionRestartTimerRef.current = null;
      if (
        voiceStateRef.current !== "listening" ||
        recognitionPermissionBlockedRef.current
      ) {
        return;
      }
      try {
        recognitionRef.current?.start();
        setIsRecording(true);
      } catch {
        recognitionRetryCountRef.current += 1;
        const retryDelay = Math.min(
          4_000,
          350 * 2 ** Math.min(recognitionRetryCountRef.current, 3)
        );
        scheduleRecognitionStart(retryDelay);
      }
    }, delayMs);
  };

  // Keep state sync ref for async timers/callbacks
  useEffect(() => {
    voiceStateRef.current = voiceState;
  }, [voiceState]);

  useEffect(() => {
    if (!isLoading) return;
    const timer = window.setInterval(() => {
      setWaitElapsedSeconds((seconds) => seconds + 1);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [isLoading]);
  
  const chatBottomRef = useRef<HTMLDivElement>(null);
  const voiceCloseRef = useRef<HTMLButtonElement>(null);
  const focusBeforeModalRef = useRef<HTMLElement | null>(null);

  // Theme is owned by the global ThemeProvider now (marketing and app share
  // one system); the header's theme control uses it directly, so the app keeps
  // no theme state of its own.

  // Modal behaviour: Escape closes, focus moves in on open and returns to
  // wherever it came from on close. Without this a keyboard user could tab
  // into the page behind the overlay and get lost.
  useEffect(() => {
    if (voiceState === "inactive") {
      focusBeforeModalRef.current?.focus?.();
      focusBeforeModalRef.current = null;
      return;
    }
    if (!focusBeforeModalRef.current) {
      focusBeforeModalRef.current = document.activeElement as HTMLElement;
    }
    voiceCloseRef.current?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        stopSpeaking();
        setVoiceState("inactive");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // stopSpeaking only reads live refs and stable React setters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [voiceState]);

  // 1. Initial configuration load & Web Speech API setup
  useEffect(() => {
    // Load BYOK key for this browser session only. Do not persist API keys long-term.
    const savedKey = sessionStorage.getItem(KEY_LOCAL_STORAGE_GEMINI) || "";
    setGeminiKey(savedKey);

    // Load or generate Tenant UUID for persistent cross-reload learning memory
    let savedTenant = localStorage.getItem(KEY_LOCAL_STORAGE_TENANT);
    if (!savedTenant || savedTenant === "undefined") {
      savedTenant = crypto.randomUUID();
      localStorage.setItem(KEY_LOCAL_STORAGE_TENANT, savedTenant);
    }
    setTenantId(savedTenant);

    // Ask whether the cloned voice is reachable, so the UI can say which
    // voice the user is about to hear instead of leaving them guessing.
    void refreshVoiceProvider();

    // Restore conversations from the server. Every turn has always been
    // written to Postgres; nothing ever read them back, so a refresh destroyed
    // history that was sitting safely in the database the whole time.
    //
    // For a signed-in user the account tenant takes over in the effect below,
    // which re-restores against it; a guest stays on this per-browser tenant.
    void restoreSessions(savedTenant);

    // Setup Speech Recognition
    if (typeof window !== "undefined") {
      const speechWindow = window as SpeechWindow;
      const SpeechRecognition =
        speechWindow.SpeechRecognition || speechWindow.webkitSpeechRecognition;
      if (SpeechRecognition) {
        const rec = new SpeechRecognition();
        rec.continuous = false;
        rec.interimResults = false;
        rec.lang = "en-US";

        rec.onresult = (event: SpeechRecognitionResultEventLike) => {
          const transcript = event.results[0][0].transcript;
          recognitionRetryCountRef.current = 0;
          recognitionPermissionBlockedRef.current = false;
          setVoiceInputIssue(null);
          const isVoiceActive = voiceStateRef.current !== "inactive";
          if (isVoiceActive) {
            // Call through the ref so we always hit the latest closure
            // (current session, current tenant, current key).
            submitRef.current(transcript);
          } else {
            setUserInput((prev) => (prev ? prev + " " + transcript : transcript));
          }
        };

        rec.onend = () => {
          setIsRecording(false);
          if (
            voiceStateRef.current === "listening" &&
            !recognitionPermissionBlockedRef.current &&
            recognitionRestartTimerRef.current === null
          ) {
            scheduleRecognitionStart(250);
          } else if (voiceStateRef.current === "inactive") {
            setIsRecording(false);
          }
        };

        rec.onerror = (event: SpeechRecognitionErrorEventLike) => {
          console.error("Speech recognition error:", event);
          setIsRecording(false);
          if (voiceStateRef.current !== "listening") {
            return;
          }

          if (
            event.error === "not-allowed" ||
            event.error === "service-not-allowed"
          ) {
            recognitionPermissionBlockedRef.current = true;
            clearRecognitionRestart();
            setVoiceInputIssue(
              "Microphone access is blocked. Allow it in the browser, then try again."
            );
            return;
          }

          recognitionRetryCountRef.current += 1;
          if (event.error === "no-speech") {
            setVoiceInputIssue(null);
          } else if (event.error === "audio-capture") {
            setVoiceInputIssue(
              "The microphone was interrupted by another capture. Reconnecting..."
            );
          } else {
            setVoiceInputIssue("Voice input paused briefly. Reconnecting...");
          }
          const retryDelay =
            event.error === "no-speech"
              ? 250
              : Math.min(
                  4_000,
                  500 * 2 ** Math.min(recognitionRetryCountRef.current, 3)
                );
          scheduleRecognitionStart(retryDelay);
        };

        recognitionRef.current = rec;
      }
    }
    return () => {
      clearRecognitionRestart();
      try {
        recognitionRef.current?.stop();
      } catch {
        // Safe to ignore during unmount.
      }
      recognitionRef.current = null;
    };
    // Speech recognition is initialized once so browser callbacks can call the latest ref-backed state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Prefer a known English male browser voice. Chrome loads some network
  // voices asynchronously, so reconsider the choice whenever that list
  // changes instead of permanently keeping the first operating-system default.
  useEffect(() => {
    if (typeof window === "undefined" || !window.speechSynthesis) return;
    const chooseBrowserVoice = () => {
      const voices = window.speechSynthesis.getVoices();
      if (!voices.length) return;
      browserVoiceRef.current = selectPreferredBrowserVoice(voices);
    };
    chooseBrowserVoice();
    window.speechSynthesis.addEventListener("voiceschanged", chooseBrowserVoice);
    return () =>
      window.speechSynthesis.removeEventListener(
        "voiceschanged",
        chooseBrowserVoice
      );
  }, []);

  // When authentication resolves to a signed-in account, switch to the tenant
  // that account owns so memory follows the user across devices. A guest is
  // left on the per-browser tenant set at mount.
  useEffect(() => {
    if (authStatus !== "authenticated") return;
    const accountTenant = authSession?.user?.tenantId;
    if (!accountTenant || accountTenant === tenantId) return;
    localStorage.setItem(KEY_LOCAL_STORAGE_TENANT, accountTenant);
    localStorage.removeItem(KEY_LOCAL_STORAGE_ACTIVE);
    setTenantId(accountTenant);
    void restoreSessions(accountTenant);
    // restoreSessions is a stable inner function; tenantId is intentionally a
    // trigger, not a subscription.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authStatus, authSession?.user?.tenantId]);

  // Monitor voiceState transitions to start/stop the web speech capture
  useEffect(() => {
    if (!recognitionRef.current) return;
    if (voiceState === "listening") {
      recognitionPermissionBlockedRef.current = false;
      recognitionRetryCountRef.current = 0;
      setVoiceInputIssue(null);
      stopSpeaking();
      scheduleRecognitionStart();
    } else {
      clearRecognitionRestart();
      try {
        recognitionRef.current.stop();
      } catch {
        // Safe to ignore
      }
    }
    // stopSpeaking only reads live refs and stable React setters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [voiceState]);

  // 2. Scroll to bottom, but only when the reader is already near it.
  // Unconditional autoscroll pulled the view away from anyone who had scrolled
  // up to reread something, which during a stream happened on every token.
  useEffect(() => {
    const el = chatBottomRef.current;
    if (!el) return;
    const container = el.parentElement;
    if (!container) return;
    const distanceFromBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight;
    if (distanceFromBottom < 160) {
      el.scrollIntoView({ behavior: "smooth" });
    }
  }, [sessions, activeSessionId]);

  const activeSession = sessions.find((s) => s.id === activeSessionId) || null;

  const lastMsg = activeSession?.messages[activeSession.messages.length - 1];
  const hasStreamingText = Boolean(
    isLoading && lastMsg?.role === "assistant" && lastMsg.content.length > 0
  );
  const waitingLabel =
    voiceLatencyPhase === "retrieving"
      ? "Finding the most relevant context"
      : voiceLatencyPhase === "generating"
        ? "Andrew is thinking through your question"
        : waitElapsedSeconds >= 4
          ? "The backend is waking up"
          : "Connecting to Andrew";
  const showSuggestions = Boolean(
    activeSession && !isLoading && !chatError &&
    activeSession.messages.filter((m) => m.role === "user").length === 0
  );

  const GREETING: Message = {
    role: "assistant",
    content:
      "Hi, I'm Andrew Ng, or rather a grounded recreation of him built from my public work. Ask me about machine learning, research, building AI products, career moves, or where the field is headed. I'll answer from what I've actually written and taught.",
  };

  const makeEmptySession = (title = "New conversation"): ChatSession => ({
    id: crypto.randomUUID(),
    title,
    messages: [GREETING],
    triplets: [],
    edges: [],
    persisted: false,
  });

  // Rebuild the sidebar and the active transcript from the server.
  const restoreSessions = async (tenant: string) => {
    const generation = ++sessionsRestoreGenerationRef.current;
    setSessionsLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/chat/sessions`, {
        headers: { "X-Tenant-Id": tenant },
      });
      if (!res.ok) throw new Error(String(res.status));

      const rows: { id: string; title: string; message_count: number }[] = await res.json();
      if (generation !== sessionsRestoreGenerationRef.current) return;
      const uniqueRows = Array.from(
        rows
          .reduce((byId, row) => {
            if (!byId.has(row.id)) byId.set(row.id, row);
            return byId;
          }, new Map<string, (typeof rows)[number]>())
          .values()
      );
      if (!uniqueRows.length) {
        const fresh = makeEmptySession();
        setSessions([fresh]);
        setActiveSessionId(fresh.id);
        return;
      }

      const restored: ChatSession[] = uniqueRows.map((r) => ({
        id: r.id,
        title: r.title || "Conversation",
        messages: [],       // filled lazily when the session is opened
        triplets: [],
        edges: [],
        persisted: true,
      }));
      setSessions(restored);

      // Reopen whatever was last active, when it still exists.
      const remembered = localStorage.getItem(KEY_LOCAL_STORAGE_ACTIVE);
      const target = restored.find((s) => s.id === remembered) ?? restored[0];
      setActiveSessionId(target.id);
      await loadSessionMessages(target.id, tenant);
    } catch (e) {
      if (generation !== sessionsRestoreGenerationRef.current) return;
      console.error("Could not restore sessions:", e);
      const fresh = makeEmptySession();
      setSessions([fresh]);
      setActiveSessionId(fresh.id);
    } finally {
      if (generation === sessionsRestoreGenerationRef.current) {
        setSessionsLoading(false);
      }
    }
  };

  // Transcripts load on demand rather than all at once, so a user with fifty
  // conversations does not download every one of them at startup.
  const loadSessionMessages = async (sessionId: string, tenant?: string) => {
    const tid = tenant || tenantId;
    if (!tid) return;
    try {
      const res = await fetch(
        `${API_BASE_URL}/api/v1/chat/sessions/${sessionId}/messages`,
        { headers: { "X-Tenant-Id": tid } },
      );
      if (!res.ok) return;
      const stored: Message[] = await res.json();
      setSessions((prev) =>
        prev.map((s) =>
          s.id === sessionId
            ? { ...s, messages: stored.length ? stored : [GREETING] }
            : s,
        ),
      );
    } catch (e) {
      console.error("Could not load transcript:", e);
    }
  };

  // Sync graph manually
  const handleSyncGraph = async (viewOverride?: "session" | "global") => {
    if (!activeSession || isSyncingGraph) return;
    setIsSyncingGraph(true);
    const viewToFetch = viewOverride || graphView;
    try {
      // Graph endpoint only needs tenant identity — no Gemini key.
      const response = await fetch(`${API_BASE_URL}/api/v1/chat/graph/${activeSession.id}?view=${viewToFetch}`, {
        headers: { "X-Tenant-Id": tenantId }
      });
      if (response.ok) {
        const graphData = await response.json();
        setSessions((prev) =>
          prev.map((s) =>
            s.id === activeSession.id
              ? { 
                  ...s, 
                  triplets: graphData.nodes, 
                  edges: graphData.edges 
                }
              : s
          )
        );
      }
    } catch (e) {
      console.error("Failed to sync graph:", e);
    } finally {
      setIsSyncingGraph(false);
    }
  };

  // Automatically sync graph when session, view, or tenant changes
  // Skip sync for brand-new sessions with only the greeting — nothing to fetch
  useEffect(() => {
    if (activeSession?.id && tenantId) {
      const hasUserMessages = activeSession.messages.some((m) => m.role === "user");
      if (hasUserMessages || graphView === "global") {
        handleSyncGraph(graphView);
      }
    }
    // Graph sync is event-driven by session/view changes; handleSyncGraph captures current request state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSession?.id, graphView, tenantId]);

  // Poll the cheap extraction-status endpoint until the background task has
  // finished, then refresh the graph once. Bounded so a stuck extraction can
  // never leave the client polling forever.
  const waitForGraphExtraction = async (sessionId: string, maxWaitMs = 30000) => {
    const startedAt = Date.now();
    let delay = 1500;

    while (Date.now() - startedAt < maxWaitMs) {
      await new Promise((r) => setTimeout(r, delay));
      delay = Math.min(delay * 1.4, 5000);   // back off rather than hammer

      try {
        const res = await fetch(
          `${API_BASE_URL}/api/v1/chat/graph/${sessionId}/status`,
          { headers: { "X-Tenant-Id": tenantId } },
        );
        if (!res.ok) break;
        const { pending_extractions: pending } = await res.json();
        if (pending === 0) break;
      } catch {
        break;   // network trouble: fall through to one final sync
      }
    }

    await handleSyncGraph();
  };

  // Retract one belief from the graph. Soft-deletes on the server (keeps
  // history), then refreshes the view so the connection disappears.
  const handleForgetEdge = async (edgeId: string) => {
    try {
      await fetch(`${API_BASE_URL}/api/v1/chat/graph/edge/${edgeId}`, {
        method: "DELETE",
        headers: { "X-Tenant-Id": tenantId },
      });
    } catch (e) {
      console.error("Could not forget that connection:", e);
    }
    void handleSyncGraph(graphView);
  };

  const handleResetMemory = async () => {
    if (!window.confirm("Are you sure you want to reset your learning history? This will clear all extracted graph concepts and dialogue history in the database.")) {
      return;
    }
    stopSpeaking();
    clearRecognitionRestart();
    if (chatAbortRef.current) {
      chatAbortReasonRef.current = "interrupt";
      chatAbortRef.current.abort();
    }
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/chat/clear`, {
        method: "POST",
        headers: { "X-Tenant-Id": tenantId }
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || `Reset failed (${response.status})`);
      }
    } catch (e) {
      console.error("Failed to clear backend memory:", e);
      const message =
        e instanceof Error
          ? e.message
          : "The learning history could not be cleared.";
      setChatError(classifyError(null, message));
      return;
    }

    // Keep the tenant identity. Rotating it here broke signed-in accounts:
    // the auth effect switched back to the account tenant and restored the
    // supposedly deleted sidebar. The server has now cleared this tenant.
    sessionsRestoreGenerationRef.current += 1;
    localStorage.removeItem(KEY_LOCAL_STORAGE_ACTIVE);
    const fresh = makeEmptySession();
    setSessions([fresh]);
    setActiveSessionId(fresh.id);
    setGraphView("session");
    setChatError(null);
  };

  // Save key to storage
  const handleSaveKey = (val: string) => {
    setGeminiKey(val);
    sessionStorage.setItem(KEY_LOCAL_STORAGE_GEMINI, val);
  };

  // Create new chat. The session row is created server-side on the first
  // message, so nothing is persisted until there is something to persist.
  const handleNewChat = () => {
    const untouchedDraft = sessions.find(
      (session) =>
        !session.persisted &&
        session.messages.length === 1 &&
        session.messages[0]?.role === "assistant"
    );
    if (untouchedDraft) {
      setActiveSessionId(untouchedDraft.id);
      localStorage.setItem(KEY_LOCAL_STORAGE_ACTIVE, untouchedDraft.id);
      setMobilePanel("chat");
      setGraphView("session");
      stopSpeaking();
      return;
    }
    const newSession = makeEmptySession();
    setSessions((prev) => [newSession, ...prev]);
    setActiveSessionId(newSession.id);
    localStorage.setItem(KEY_LOCAL_STORAGE_ACTIVE, newSession.id);
    setMobilePanel("chat");
    // Reset to session view so the KG panel starts empty for a fresh chat.
    // Global view would immediately show cross-session data which is confusing.
    setGraphView("session");
  };

  // Delete chat, on the server as well as locally. Previously this only
  // removed it from React state, so the conversation reappeared on refresh.
  const handleDeleteChat = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();

    const target = sessions.find((s) => s.id === id);
    const hasContent = (target?.messages.length ?? 0) > 1;
    if (hasContent && !window.confirm("Delete this conversation? This cannot be undone.")) {
      return;
    }

    if (target?.persisted) {
      try {
        const response = await fetch(
          `${API_BASE_URL}/api/v1/chat/sessions/${id}`,
          {
            method: "DELETE",
            headers: { "X-Tenant-Id": tenantId },
          }
        );
        if (!response.ok) {
          const body = await response.json().catch(() => null);
          throw new Error(body?.detail || `Delete failed (${response.status})`);
        }
      } catch (err) {
        console.error("Could not delete conversation on the server:", err);
        setChatError(
          classifyError(
            null,
            err instanceof Error
              ? err.message
              : "The conversation could not be deleted."
          )
        );
        return;
      }
    }

    const filtered = sessions.filter((s) => s.id !== id);
    const replacement = filtered.length ? filtered : [makeEmptySession()];
    setSessions(replacement);
    if (activeSessionId === id) {
      const next = replacement[0];
      setActiveSessionId(next.id);
      if (next.persisted) {
        localStorage.setItem(KEY_LOCAL_STORAGE_ACTIVE, next.id);
        if (next.messages.length === 0) void loadSessionMessages(next.id);
      } else {
        localStorage.removeItem(KEY_LOCAL_STORAGE_ACTIVE);
      }
    }
  };
  // Cancel speech helper — also aborts in-flight TTS network requests so
  // interrupting the tutor stops burning synthesis compute on unheard audio.
  const stopVoiceAmplitude = () => {
    if (voiceAmplitudeFrameRef.current !== null) {
      cancelAnimationFrame(voiceAmplitudeFrameRef.current);
      voiceAmplitudeFrameRef.current = null;
    }
    setVoiceAmplitude(0);
  };

  const trackClonedVoiceAmplitude = (
    audio: HTMLAudioElement,
    envelope: WavAmplitudeEnvelope | null
  ) => {
    stopVoiceAmplitude();
    if (!envelope?.values.length) {
      setVoiceAmplitude(0.55);
      return;
    }

    const update = () => {
      if (audio.paused || audio.ended) {
        stopVoiceAmplitude();
        return;
      }
      const index = Math.min(
        envelope.values.length - 1,
        Math.floor(audio.currentTime * envelope.samplesPerSecond)
      );
      setVoiceAmplitude(envelope.values[index] ?? 0);
      voiceAmplitudeFrameRef.current = requestAnimationFrame(update);
    };
    voiceAmplitudeFrameRef.current = requestAnimationFrame(update);
  };

  const trackBrowserVoiceAmplitude = () => {
    stopVoiceAmplitude();
    const startedAt = performance.now();
    const update = (now: number) => {
      const seconds = (now - startedAt) / 1000;
      setVoiceAmplitude(
        0.28 +
          Math.abs(Math.sin(seconds * 8.5)) * 0.42 +
          Math.abs(Math.sin(seconds * 13.5)) * 0.18
      );
      voiceAmplitudeFrameRef.current = requestAnimationFrame(update);
    };
    voiceAmplitudeFrameRef.current = requestAnimationFrame(update);
  };

  const stopSpeaking = () => {
    if (typeof window !== "undefined" && window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }
    if (ttsAbortRef.current) {
      ttsAbortRef.current.abort();
      ttsAbortRef.current = null;
    }
    if (currentAudioRef.current) {
      currentAudioRef.current.pause();
      currentAudioRef.current.src = "";
      currentAudioRef.current = null;
    }
    isPlayingRef.current = false;
    stopVoiceAmplitude();
    setVoiceLatencyPhase("idle");
  };

  // Fallback when the cloned-voice service is unreachable. The browser's own
  // synthesis is generic, but a generic voice that works beats a cloned voice
  // that does not, and the GPU session backing the clone is ephemeral by
  // design (see notebooks/kaggle_tts_server.py).
  const speakWithBrowser = (
    text: string,
    onStarted?: () => void,
    onFinished?: () => void
  ) => {
    if (typeof window === "undefined" || !window.speechSynthesis) {
      onFinished?.();
      return;
    }
    const utterance = new SpeechSynthesisUtterance(text);
    const selectedVoice =
      browserVoiceRef.current ??
      selectPreferredBrowserVoice(window.speechSynthesis.getVoices());
    if (selectedVoice) {
      browserVoiceRef.current = selectedVoice;
      utterance.voice = selectedVoice;
      utterance.lang = selectedVoice.lang || "en-US";
    } else {
      utterance.lang = "en-US";
    }
    utterance.rate = ttsSpeed;
    utterance.onstart = () => {
      trackBrowserVoiceAmplitude();
      onStarted?.();
    };
    const done = () => {
      stopVoiceAmplitude();
      onFinished?.();
    };
    utterance.onend = done;
    utterance.onerror = done;
    window.speechSynthesis.speak(utterance);
  };

  // Incremental speaker for the streaming path.
  //
  // Sentences are pushed in as the model produces them. Each one is sent for
  // synthesis the moment it arrives, and playback runs sequentially behind
  // that. This is what collapses time-to-first-audio: previously the client
  // waited for the entire answer, then synthesised sentence by sentence, so
  // nothing was audible for 8 to 30 seconds.
  const createStreamingSpeaker = (
    interactive: boolean,
    onFinished?: () => void
  ) => {
    const controller = new AbortController();
    ttsAbortRef.current = controller;
    isPlayingRef.current = true;

    type SynthesizedSentence = {
      url: string;
      envelope: WavAmplitudeEnvelope | null;
    } | null;
    type SpeechJob = {
      text: string;
      result: Promise<SynthesizedSentence>;
      resolve: (result: SynthesizedSentence) => void;
    };

    const jobs: SpeechJob[] = [];
    let playIndex = 0;
    let synthIndex = 0;
    let synthesizing = false;
    let inputClosed = false;
    let playing = false;
    let finished = false;
    // Snapshot the resolved provider for this answer. "Preparing" deliberately
    // means browser speech, not "try the clone and wait eight seconds"; the
    // next answer can use the clone once a fresh health check confirms it.
    let cloneEnabled = voiceProviderRef.current === "clone";
    const deadlineMs = interactive
      ? INTERACTIVE_TTS_DEADLINE_MS
      : READ_ALOUD_TTS_DEADLINE_MS;

    const finishOnce = () => {
      if (finished) return;
      finished = true;
      isPlayingRef.current = false;
      stopVoiceAmplitude();
      onFinished?.();
    };

    const markPlaybackStarted = (provider: "clone" | "browser") => {
      updateVoiceProvider(provider);
      if (interactive && voiceStateRef.current !== "inactive") {
        setVoiceLatencyPhase(provider === "clone" ? "playing" : "fallback");
        setVoiceState("speaking");
      }
    };

    const markPlaybackEnded = () => {
      stopVoiceAmplitude();
      if (
        interactive &&
        voiceStateRef.current !== "inactive" &&
        (!inputClosed || playIndex < jobs.length)
      ) {
        setVoiceLatencyPhase("synthesizing");
        setVoiceState("thinking");
      }
    };

    const synthesize = async (
      sentence: string
    ): Promise<SynthesizedSentence> => {
      if (!cloneEnabled || controller.signal.aborted) return null;

      const requestController = new AbortController();
      const abortRequest = () => requestController.abort();
      controller.signal.addEventListener("abort", abortRequest, { once: true });
      const timeout = window.setTimeout(
        () => requestController.abort(),
        deadlineMs
      );

      try {
        const res = await fetch(`${API_BASE_URL}/api/v1/chat/tts`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Tenant-Id": tenantId,
          },
          body: JSON.stringify({ text: sentence, speed: ttsSpeed }),
          signal: requestController.signal,
        });
        if (!res.ok) {
          cloneEnabled = false;
          updateVoiceProvider("browser");
          return null;
        }
        const blob = await res.blob();
        const envelope = await readWavAmplitude(blob);
        updateVoiceProvider("clone");
        return {
          url: URL.createObjectURL(blob),
          envelope,
        };
      } catch {
        if (!controller.signal.aborted) {
          cloneEnabled = false;
          updateVoiceProvider("browser");
        }
        return null;
      } finally {
        window.clearTimeout(timeout);
        controller.signal.removeEventListener("abort", abortRequest);
      }
    };

    const startNextSynthesis = () => {
      if (
        synthesizing ||
        synthIndex >= jobs.length ||
        controller.signal.aborted
      ) {
        return;
      }
      const job = jobs[synthIndex];
      synthIndex += 1;
      synthesizing = true;
      void synthesize(job.text)
        .then(job.resolve)
        .finally(() => {
          synthesizing = false;
          startNextSynthesis();
          void playNext();
        });
    };

    const playNext = async () => {
      if (playing) return;
      playing = true;

      while (playIndex < jobs.length) {
        if (!isPlayingRef.current || controller.signal.aborted) break;

        if (interactive && voiceStateRef.current !== "inactive") {
          setVoiceLatencyPhase("synthesizing");
        }
        const job = jobs[playIndex];
        const synthesized = await job.result;
        playIndex += 1;
        if (!isPlayingRef.current || controller.signal.aborted) break;

        if (!synthesized) {
          await new Promise<void>((resolve) =>
            speakWithBrowser(
              job.text,
              () => markPlaybackStarted("browser"),
              () => {
                markPlaybackEnded();
                resolve();
              }
            )
          );
          continue;
        }

        const played = await new Promise<boolean>((resolve) => {
          const audio = new Audio(synthesized.url);
          audio.playbackRate = ttsSpeed;
          audio.preservesPitch = true;
          currentAudioRef.current = audio;
          let started = false;
          let settled = false;
          const done = (completed: boolean) => {
            if (settled) return;
            settled = true;
            if (currentAudioRef.current === audio) {
              currentAudioRef.current = null;
            }
            URL.revokeObjectURL(synthesized.url);
            markPlaybackEnded();
            resolve(completed);
          };
          audio.onplay = () => {
            started = true;
            trackClonedVoiceAmplitude(audio, synthesized.envelope);
            markPlaybackStarted("clone");
          };
          audio.onended = () => done(started);
          audio.onerror = () => done(false);
          audio.play().catch(() => done(false));
        });

        if (!played && !controller.signal.aborted) {
          updateVoiceProvider("browser");
          await new Promise<void>((resolve) =>
            speakWithBrowser(
              job.text,
              () => markPlaybackStarted("browser"),
              () => {
                markPlaybackEnded();
                resolve();
              }
            )
          );
        }
      }

      playing = false;
      if (inputClosed && playIndex >= jobs.length) {
        finishOnce();
      }
    };

    return {
      push(sentence: string) {
        if (!sentence.trim() || controller.signal.aborted) return;
        let resolveResult!: (result: SynthesizedSentence) => void;
        const result = new Promise<SynthesizedSentence>((resolve) => {
          resolveResult = resolve;
        });
        jobs.push({
          text: sentence.trim(),
          result,
          resolve: resolveResult,
        });
        if (interactive && voiceStateRef.current !== "inactive") {
          setVoiceLatencyPhase("synthesizing");
        }
        startNextSynthesis();
        void playNext();
      },
      finish() {
        inputClosed = true;
        if (!playing && playIndex >= jobs.length) {
          finishOnce();
        } else {
          void playNext();
        }
      },
    };
  };


  // Toggle STT recording
  const handleToggleRecording = () => {
    if (!recognitionRef.current) {
      alert("Speech recognition is not supported in this browser. Try Google Chrome.");
      return;
    }

    if (isRecording) {
      recognitionRef.current.stop();
      setIsRecording(false);
    } else {
      setIsRecording(true);
      recognitionRef.current.start();
    }
  };

  // Reusable submit dialogue handler for both text and voice actions
  const submitDialogueMessage = async (messageText: string) => {
    if (!messageText.trim() || !activeSession || isLoading) return;

    const isVoiceActive = voiceStateRef.current !== "inactive";
    setVoiceLatencyPhase("connecting");
    setWaitElapsedSeconds(0);
    if (isVoiceActive) {
      setVoiceState("thinking");
      stopVoiceAmplitude();
    }

    setIsLoading(true);
    setChatError(null);
    setLastMessage(messageText);

    // NOTE: no persona reminder is appended here any more. The old inline
    // reminder polluted the query embedding, full-text search, stored
    // conversation history AND the knowledge-graph extractor (which mined
    // triples out of prompt boilerplate). Every rule it contained already
    // exists verbatim in the server-side persona system prompt.

    const updatedMessages = [
      ...activeSession.messages,
      { role: "user" as const, content: messageText }
    ];

    setSessions((prev) =>
      prev.map((s) =>
        s.id === activeSession.id
          ? {
              ...s,
              title: s.title === "New conversation" ? messageText.slice(0, 24) + "..." : s.title,
              messages: updatedMessages
            }
          : s
      )
    );

    const chatController = new AbortController();
    chatAbortRef.current = chatController;
    chatAbortReasonRef.current = null;
    const chatDeadline = window.setTimeout(() => {
      chatAbortReasonRef.current = "timeout";
      chatController.abort();
    }, CHAT_TURN_DEADLINE_MS);
    let turnCompleted = false;

    try {
      const turnHistory = updatedMessages.slice(0, -1).map((m) => ({
        role: m.role,
        content: m.content
      }));

      const headers: Record<string, string> = {
        "Content-Type": "application/json",
        "X-Tenant-Id": tenantId
      };
      // Only send the key header when a real key exists. The old code sent
      // the literal placeholder "AIzaSy...", which triggered the backend's
      // silent fallback to the server owner's key.
      if (geminiKey.trim()) {
        headers["X-Gemini-Api-Key"] = geminiKey.trim();
      }

      const response = await fetch(`${API_BASE_URL}/api/v1/chat/stream`, {
        method: "POST",
        headers,
        signal: chatController.signal,
        body: JSON.stringify({
          session_id: activeSession.id,
          message: messageText,
          turn_history: turnHistory,
          temperature: 0.2
        })
      });

      if (!response.ok) {
        const errBody = await response.json().catch(() => null);
        const detail = errBody?.detail || response.statusText;
        setChatError(classifyError(response.status, detail));
        // Remove the optimistic user bubble; the notice explains what happened.
        setSessions((prev) =>
          prev.map((s) =>
            s.id === activeSession.id ? { ...s, messages: activeSession.messages } : s
          )
        );
        if (isVoiceActive) {
          stopSpeaking();
          setVoiceState("inactive");
        }
        setIsLoading(false);
        return;
      }

      // ── Consume the SSE stream ──────────────────────────────────────────
      // Text appears as it is generated, and each completed sentence is sent
      // for synthesis immediately rather than after the whole answer.
      const shouldSpeak = readAloudEnabled || isVoiceActive;
      const speaker = shouldSpeak
        ? createStreamingSpeaker(isVoiceActive, () => {
            if (isVoiceActive && voiceStateRef.current !== "inactive") {
              setVoiceLatencyPhase("idle");
              setVoiceState("listening");
            }
          })
        : null;

      const reader = response.body?.getReader();
      if (!reader) {
        throw new Error("The server returned an empty response stream.");
      }
      const decoder = new TextDecoder();
      let buffer = "";
      let streamedText = "";
      let data: Record<string, unknown> = {};
      let streamErrorDetail: string | null = null;
      let streamErrorStatus: number | null = null;

      // Placeholder assistant message that fills in as deltas arrive
      setSessions((prev) =>
        prev.map((s) =>
          s.id === activeSession.id
            ? { ...s, messages: [...updatedMessages, { role: "assistant" as const, content: "" }] }
            : s
        )
      );

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const frames = buffer.split("\n\n");
        buffer = frames.pop() || "";

        for (const frame of frames) {
          const eventLine = frame.split("\n").find((l) => l.startsWith("event: "));
          const dataLine = frame.split("\n").find((l) => l.startsWith("data: "));
          if (!eventLine || !dataLine) continue;

          const eventType = eventLine.slice(7).trim();
          let payload: Record<string, unknown>;
          try {
            payload = JSON.parse(dataLine.slice(6));
          } catch {
            continue;
          }

          if (eventType === "delta") {
            if (voiceStateRef.current === "thinking" || !isVoiceActive) {
              setVoiceLatencyPhase("generating");
            }
            streamedText += payload.text as string;
            setSessions((prev) =>
              prev.map((s) =>
                s.id === activeSession.id
                  ? {
                      ...s,
                      messages: [
                        ...updatedMessages,
                        { role: "assistant" as const, content: streamedText }
                      ]
                    }
                  : s
              )
            );
          } else if (eventType === "sentence") {
            speaker?.push(payload.text as string);
          } else if (eventType === "status") {
            const phase = payload.phase;
            if (phase === "retrieving") {
              setVoiceLatencyPhase("retrieving");
            } else if (phase === "generating") {
              setVoiceLatencyPhase("generating");
            }
          } else if (eventType === "meta") {
            data = { ...data, ...payload };
          } else if (eventType === "done") {
            data = { ...data, ...payload };
          } else if (eventType === "error") {
            streamErrorDetail =
              typeof payload.detail === "string"
                ? payload.detail
                : "The AI service could not complete this request.";
            streamErrorStatus =
              typeof payload.status === "number" ? payload.status : null;
          }
        }
      }

      speaker?.finish();
      if (streamErrorDetail) {
        const error = new Error(streamErrorDetail) as Error & {
          status?: number | null;
        };
        error.status = streamErrorStatus;
        throw error;
      }

      const assistantText = (data.assistant_message as string) || streamedText;
      const rawGraph: GraphContextNode[] = (data.graph_context as GraphContextNode[]) || [];
      const updatedTriplets: TripletRow[] = rawGraph.map((node) => ({
        node_id: node.node_id,
        canonical_name: node.canonical_name,
        node_type: node.node_type,
        metadata: {},
        hop_distance: node.hop_distance,
        path_weight: node.combined_score,
        vector_score: node.combined_score,
        combined_score: node.combined_score,
        predicates_path: []
      }));

      setSessions((prev) =>
        prev.map((s) =>
          s.id === activeSession.id
            ? {
                ...s,
                persisted: true,
                messages: [
                  ...updatedMessages,
                  {
                    role: "assistant" as const,
                    content: assistantText,
                    cacheStatus: data.cache_status as string,
                    cachedTokenCount: data.cached_token_count as number,
                    isGrounded: data.is_grounded as boolean,
                    retrievedChunks: data.retrieved_chunks as RetrievedChunk[],
                    // Concepts the graph contributed, so recall can be shown
                    // inline at the moment it happened.
                    recalled: ((data.graph_context as GraphContextNode[]) || [])
                      .filter((n) => n.node_type === "Concept" && n.hop_distance > 0)
                      .slice(0, 3)
                      .map((n) => n.canonical_name)
                  }
                ],
                // Merge new graph nodes with existing (don't drop edges).
                // The chat response only provides nodes — edges arrive
                // via the delayed handleSyncGraph() calls at 5s/12s.
                triplets: updatedTriplets.length > 0
                  ? [...(s.triplets || []).filter(
                      (existing) => !updatedTriplets.some((u) => u.node_id === existing.node_id)
                    ), ...updatedTriplets]
                  : s.triplets,
                // Preserve existing edges — full sync will refresh them
              }
            : s
        )
      );
      turnCompleted = true;

    } catch (err: unknown) {
      console.error(err);
      stopSpeaking();
      const wasAborted =
        err instanceof DOMException
          ? err.name === "AbortError"
          : err instanceof Error && err.name === "AbortError";
      if (wasAborted && chatAbortReasonRef.current) {
        if (chatAbortReasonRef.current === "interrupt") {
          if (isVoiceActive) setVoiceState("listening");
        } else {
          if (isVoiceActive) setVoiceState("inactive");
          setChatError(
            classifyError(
              null,
              "The response timed out before the server completed it."
            )
          );
        }
        return;
      }
      const message = err instanceof Error ? err.message : "Unknown error";
      const possibleStatus =
        err && typeof err === "object" && "status" in err
          ? (err as { status?: unknown }).status
          : null;
      const status = typeof possibleStatus === "number" ? possibleStatus : null;
      if (isVoiceActive) setVoiceState("inactive");
      // A network failure has no HTTP status; SSE failures carry the status
      // supplied by the backend in their final error frame.
      setChatError(classifyError(status, message));
      setSessions((prev) =>
        prev.map((s) =>
          s.id === activeSession.id ? { ...s, messages: activeSession.messages } : s
        )
      );
    } finally {
      window.clearTimeout(chatDeadline);
      if (chatAbortRef.current === chatController) {
        chatAbortRef.current = null;
      }
      chatAbortReasonRef.current = null;
      setIsLoading(false);
      setWaitElapsedSeconds(0);
      if (!isVoiceActive) {
        setVoiceLatencyPhase("idle");
      }
      // Wait for graph extraction to actually finish, instead of guessing with
      // blind 5s and 12s timers that either fired too early or wasted a
      // request after the work was already done.
      if (turnCompleted) {
        void waitForGraphExtraction(activeSession.id);
      }
    }
  };

  // Keep the ref pointing at the freshest closure every render, so the
  // once-registered speech-recognition callbacks never act on stale state.
  useEffect(() => {
    submitRef.current = submitDialogueMessage;
  });

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!userInput.trim() || isLoading) return;
    const msg = userInput;
    setUserInput("");
    await submitDialogueMessage(msg);
  };

  // Old handleSyncGraph location removed (moved to top of file)

  return (
    <div className="flex flex-col lg:flex-row h-[100dvh] w-full overflow-hidden text-[var(--text)] bg-[var(--bg)] p-2 sm:p-4 gap-2 sm:gap-4">
      
      {/* ──────────────────────────────────────────────────
          1. SESSION RAIL (Left panel)
          ────────────────────────────────────────────────── */}
      <SessionRail
        sessions={sessions}
        activeSessionId={activeSessionId}
        sessionsLoading={sessionsLoading}
        geminiKey={geminiKey}
        ttsSpeed={ttsSpeed}
        settingsOpen={settingsOpen}
        mobileVisible={mobilePanel === "sessions"}
        onCloseMobile={() => setMobilePanel("chat")}
        onNewChat={handleNewChat}
        onToggleSettings={() => setSettingsOpen((v) => !v)}
        onSaveKey={handleSaveKey}
        onSetTtsSpeed={setTtsSpeed}
        onResetMemory={handleResetMemory}
        onSelectSession={(id) => {
          setActiveSessionId(id);
          localStorage.setItem(KEY_LOCAL_STORAGE_ACTIVE, id);
          setMobilePanel("chat");
          stopSpeaking();
          const s = sessions.find((x) => x.id === id);
          if (s && s.messages.length === 0) void loadSessionMessages(id);
        }}
        onDeleteChat={handleDeleteChat}
      />

      {/* ──────────────────────────────────────────────────
          2. CENTRAL PANEL (Chat bubbles window)
          ────────────────────────────────────────────────── */}
      <main id="main-content" className="flex-1 min-w-0 bg-[var(--surface)] border border-[var(--border)] rounded-2xl shadow-sm flex flex-col overflow-hidden">
        
        <ConversationHeader
          onOpenSessions={() => setMobilePanel("sessions")}
          onOpenGraph={() => setMobilePanel("graph")}
          readAloudEnabled={readAloudEnabled}
          onToggleReadAloud={() => {
            setReadAloudEnabled(!readAloudEnabled);
            stopSpeaking();
          }}
        />

        {/* Dialogue history scroll bubble */}
        <div className="flex-1 overflow-y-auto p-3 sm:p-6 flex flex-col gap-4 sm:gap-6" role="log" aria-label="Conversation">
          {activeSession?.messages.map((msg, index) => (
            <MessageBubble key={index} msg={msg} />
          ))}
          {/* Waiting state, only until the first token lands. Once the stream
              starts the partial answer is itself the indicator, which is why
              a static "Thinking..." for a 5 to 20 second wait read as a hang. */}
          {isLoading && !hasStreamingText && (
            <div className="flex gap-2 sm:gap-4 max-w-3xl">
              <div className="w-8 h-8 rounded-full bg-[var(--brand)] text-[var(--brand-text)] flex items-center justify-center font-medium text-[13px] flex-shrink-0">
                AN
              </div>
              <div className="px-4 py-3 rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-sm flex items-center gap-3">
                <span className="flex items-center gap-1.5" aria-hidden>
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                </span>
                <span className="text-[12px] text-[var(--text-muted)]">
                  {waitingLabel}
                  {waitElapsedSeconds >= 2 ? ` · ${waitElapsedSeconds}s` : ""}
                </span>
              </div>
            </div>
          )}

          {/* Failures get their own treatment instead of being spoken by the
              tutor in character. */}
          {chatError && (
            <div className="max-w-3xl">
              <ErrorNotice
                error={chatError}
                onOpenSettings={() => { setSettingsOpen(true); setMobilePanel("sessions"); }}
                onRetry={() => { const m = lastMessage; setChatError(null); if (m) void submitDialogueMessage(m); }}
                onDismiss={() => setChatError(null)}
              />
            </div>
          )}

          {/* Suggested openers on an untouched conversation. A first-time
              visitor previously had no indication of what this is good at. */}
          {showSuggestions && (
            <div className="max-w-3xl">
              <p className="text-[15px] font-medium text-[var(--text)] mb-1">Ask Andrew anything</p>
              <p className="text-[12px] text-[var(--text-muted)] mb-3">Try one of these to get started:</p>
              <div className="flex flex-wrap gap-2">
                {SUGGESTED_QUESTIONS.map((q) => (
                  <button
                    key={q}
                    onClick={() => void submitDialogueMessage(q)}
                    className="text-left text-[13px] px-3 py-2 rounded-xl border border-[var(--border)] bg-[var(--surface)] text-[var(--text)] hover:border-[var(--brand)] hover:bg-[var(--brand-soft)] transition"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Announces status changes to assistive tech. Polite so it waits
              for a pause rather than interrupting. */}
          <div aria-live="polite" aria-atomic="true" className="sr-only">
            {isLoading
              ? waitingLabel
              : lastMsg?.role === "assistant"
                ? `Andrew replied: ${lastMsg.content.slice(0, 200)}`
                : ""}
          </div>

          <div ref={chatBottomRef} />
        </div>

        <Composer
          value={userInput}
          isRecording={isRecording}
          isLoading={isLoading}
          geminiKey={geminiKey}
          tenantReady={!!tenantId}
          onChange={setUserInput}
          onSubmit={handleSendMessage}
          onToggleRecording={handleToggleRecording}
          onStartVoice={() => {
            void refreshVoiceProvider(true);
            setVoiceState("listening");
          }}
          onOpenSettings={() => { setSettingsOpen(true); setMobilePanel("sessions"); }}
        />
      </main>

      {/* ──────────────────────────────────────────────────
          3. CONTEXT GRAPH (Right panel)
          ────────────────────────────────────────────────── */}
      <ContextGraphPanel
        mobileVisible={mobilePanel === "graph"}
        onCloseMobile={() => setMobilePanel("chat")}
        graphView={graphView}
        onGraphViewChange={setGraphView}
        isSyncingGraph={isSyncingGraph}
        onSync={handleSyncGraph}
        triplets={activeSession?.triplets || []}
        edges={activeSession?.edges || []}
        onExploreNode={(concept) => {
          setUserInput(`Explain the concept of ${concept} and its connections in detail.`);
          submitDialogueMessage(`Explain the concept of ${concept} and its connections in detail.`);
        }}
        onForgetEdge={handleForgetEdge}
      />

      {/* ──────────────────────────────────────────────────
          4. VOICE OVERLAY (Glass modal)
          ────────────────────────────────────────────────── */}
      {voiceState !== "inactive" && (
        <VoiceOverlay
          voiceState={voiceState}
          latencyPhase={voiceLatencyPhase}
          voiceProvider={voiceProvider}
          inputIssue={voiceInputIssue}
          amplitude={voiceAmplitude}
          ttsSpeed={ttsSpeed}
          transcript={lastMsg?.role === "assistant" ? lastMsg.content : ""}
          closeRef={voiceCloseRef}
          onExit={() => {
            stopSpeaking();
            setVoiceState("inactive");
          }}
          onInterrupt={() => {
            if (voiceState === "listening") {
              setVoiceState("inactive");
            } else {
              if (chatAbortRef.current) {
                chatAbortReasonRef.current = "interrupt";
                chatAbortRef.current.abort();
              }
              stopSpeaking();
              setVoiceState("listening");
            }
          }}
          onRetryListening={() => {
            recognitionPermissionBlockedRef.current = false;
            recognitionRetryCountRef.current = 0;
            setVoiceInputIssue(null);
            try {
              recognitionRef.current?.stop();
            } catch {
              // Safe to ignore before a clean restart.
            }
            scheduleRecognitionStart(150);
          }}
          onMute={() => {
            stopSpeaking();
            setVoiceState("listening");
          }}
          onSpeedDown={() => setTtsSpeed((prev) => Math.max(0.8, prev - 0.1))}
          onSpeedUp={() => setTtsSpeed((prev) => Math.min(1.5, prev + 0.1))}
        />
      )}
    </div>
  );
}
