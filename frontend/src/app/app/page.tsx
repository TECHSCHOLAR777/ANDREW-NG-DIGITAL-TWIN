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
  type VoiceState,
  type SpeechRecognitionLike,
  type SpeechRecognitionResultEventLike,
  type SpeechRecognitionErrorEventLike,
  type SpeechWindow,
} from "@/app/app/chat-types";

export default function ChatPage() {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [userInput, setUserInput] = useState("");
  const [geminiKey, setGeminiKey] = useState("");
  const [tenantId, setTenantId] = useState("");
  // When signed in, the account owns a tenant that follows the user across
  // devices. A guest keeps the per-browser tenant generated below.
  const { data: authSession, status: authStatus } = useSession();
  const [graphView, setGraphView] = useState<"session" | "global">("session");
  const [isLoading, setIsLoading] = useState(false);
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

  // Always-fresh handle to submitDialogueMessage for browser speech callbacks.
  // The recognition handlers are registered once on mount; without this ref
  // they capture the FIRST render's closure (activeSession=null, tenantId=""),
  // which silently discarded every voice-mode utterance.
  const submitRef = useRef<(text: string) => Promise<void>>(async () => {});

  // Custom Cloned TTS Audio Player Refs
  const currentAudioRef = useRef<HTMLAudioElement | null>(null);
  const ttsAbortRef = useRef<AbortController | null>(null);
  const isPlayingRef = useRef<boolean>(false);
  // Set when the cloned-voice service returns 502, so playback switches to
  // browser speech for the rest of the answer instead of going quiet.
  const clonedVoiceDownRef = useRef<boolean>(false);
  const [clonedVoiceAvailable, setClonedVoiceAvailable] = useState<boolean | null>(null);

  // Keep state sync ref for async timers/callbacks
  useEffect(() => {
    voiceStateRef.current = voiceState;
  }, [voiceState]);
  
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
    fetch(`${API_BASE_URL}/api/v1/chat/tts/status`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => setClonedVoiceAvailable(d ? Boolean(d.available) : false))
      .catch(() => setClonedVoiceAvailable(false));

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
          if (voiceStateRef.current === "listening") {
            try {
              rec.start();
            } catch {
              // Ignore
            }
          } else if (voiceStateRef.current === "inactive") {
            setIsRecording(false);
          }
        };

        rec.onerror = (event: SpeechRecognitionErrorEventLike) => {
          console.error("Speech recognition error:", event);
          if (voiceStateRef.current === "listening" && event.error === "no-speech") {
            try {
              rec.start();
            } catch {
              // Ignore
            }
          } else {
            setVoiceState("inactive");
            setIsRecording(false);
          }
        };

        recognitionRef.current = rec;
      }
    }
    // Speech recognition is initialized once so browser callbacks can call the latest ref-backed state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
      try {
        stopSpeaking();
        recognitionRef.current.start();
      } catch (e) {
        console.warn("Speech recognition starting warning:", e);
      }
    } else {
      try {
        recognitionRef.current.stop();
      } catch {
        // Safe to ignore
      }
    }
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
  });

  // Rebuild the sidebar and the active transcript from the server.
  const restoreSessions = async (tenant: string) => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/chat/sessions`, {
        headers: { "X-Tenant-Id": tenant },
      });
      if (!res.ok) throw new Error(String(res.status));

      const rows: { id: string; title: string; message_count: number }[] = await res.json();
      if (!rows.length) {
        const fresh = makeEmptySession();
        setSessions([fresh]);
        setActiveSessionId(fresh.id);
        return;
      }

      const restored: ChatSession[] = rows.map((r) => ({
        id: r.id,
        title: r.title || "Conversation",
        messages: [],       // filled lazily when the session is opened
        triplets: [],
        edges: [],
      }));
      setSessions(restored);

      // Reopen whatever was last active, when it still exists.
      const remembered = localStorage.getItem(KEY_LOCAL_STORAGE_ACTIVE);
      const target = restored.find((s) => s.id === remembered) ?? restored[0];
      setActiveSessionId(target.id);
      await loadSessionMessages(target.id, tenant);
    } catch (e) {
      console.error("Could not restore sessions:", e);
      const fresh = makeEmptySession();
      setSessions([fresh]);
      setActiveSessionId(fresh.id);
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
    try {
      await fetch(`${API_BASE_URL}/api/v1/chat/clear`, {
        method: "POST",
        headers: { "X-Tenant-Id": tenantId }
      });
    } catch (e) {
      console.error("Failed to clear backend memory:", e);
    }

    const freshTenant = crypto.randomUUID();
    localStorage.setItem(KEY_LOCAL_STORAGE_TENANT, freshTenant);
    localStorage.removeItem(KEY_LOCAL_STORAGE_ACTIVE);
    setTenantId(freshTenant);

    const fresh = makeEmptySession();
    setSessions([fresh]);
    setActiveSessionId(fresh.id);
  };

  // Save key to storage
  const handleSaveKey = (val: string) => {
    setGeminiKey(val);
    sessionStorage.setItem(KEY_LOCAL_STORAGE_GEMINI, val);
  };

  // Create new chat. The session row is created server-side on the first
  // message, so nothing is persisted until there is something to persist.
  const handleNewChat = () => {
    const newSession = makeEmptySession();
    setSessions((prev) => [newSession, ...prev]);
    setActiveSessionId(newSession.id);
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

    const filtered = sessions.filter((s) => s.id !== id);
    const replacement = filtered.length ? filtered : [makeEmptySession()];
    setSessions(replacement);
    if (activeSessionId === id) {
      setActiveSessionId(replacement[0].id);
      if (filtered.length) void loadSessionMessages(replacement[0].id);
    }

    try {
      await fetch(`${API_BASE_URL}/api/v1/chat/sessions/${id}`, {
        method: "DELETE",
        headers: { "X-Tenant-Id": tenantId },
      });
    } catch (err) {
      console.error("Could not delete conversation on the server:", err);
    }
  };
  // Cancel speech helper — also aborts in-flight TTS network requests so
  // interrupting the tutor stops burning synthesis compute on unheard audio.
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
  };

  // Fallback when the cloned-voice service is unreachable. The browser's own
  // synthesis is generic, but a generic voice that works beats a cloned voice
  // that does not, and the GPU session backing the clone is ephemeral by
  // design (see notebooks/kaggle_tts_server.py).
  const speakWithBrowser = (text: string, onFinished?: () => void) => {
    if (typeof window === "undefined" || !window.speechSynthesis) {
      onFinished?.();
      return;
    }
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = ttsSpeed;
    utterance.onend = () => onFinished?.();
    utterance.onerror = () => onFinished?.();
    window.speechSynthesis.speak(utterance);
  };

  // Incremental speaker for the streaming path.
  //
  // Sentences are pushed in as the model produces them. Each one is sent for
  // synthesis the moment it arrives, and playback runs sequentially behind
  // that. This is what collapses time-to-first-audio: previously the client
  // waited for the entire answer, then synthesised sentence by sentence, so
  // nothing was audible for 8 to 30 seconds.
  const createStreamingSpeaker = (onFinished?: () => void) => {
    const controller = new AbortController();
    ttsAbortRef.current = controller;
    isPlayingRef.current = true;

    const pending: Promise<string | null>[] = [];
    const pendingText: string[] = [];   // parallel to `pending`, for fallback
    let playIndex = 0;
    let inputClosed = false;
    let playing = false;

    const synthesize = async (sentence: string): Promise<string | null> => {
      try {
        const res = await fetch(`${API_BASE_URL}/api/v1/chat/tts`, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Tenant-Id": tenantId },
          body: JSON.stringify({ text: sentence, speed: ttsSpeed }),
          signal: controller.signal,
        });
        if (!res.ok) {
          // 502 means the cloned-voice service is down, which is expected
          // whenever the GPU session has expired. Fall back rather than
          // dropping the sentence silently.
          if (res.status === 502) clonedVoiceDownRef.current = true;
          return null;
        }
        clonedVoiceDownRef.current = false;
        return URL.createObjectURL(await res.blob());
      } catch {
        return null; // aborted or failed: skip this sentence, keep the flow
      }
    };

    const playNext = async () => {
      if (playing) return;
      playing = true;

      while (playIndex < pending.length) {
        if (!isPlayingRef.current || controller.signal.aborted) break;

        const url = await pending[playIndex];
        const sentenceText = pendingText[playIndex];
        playIndex += 1;
        if (!url) {
          // No cloned audio for this sentence. Speak it with the browser so
          // the answer is still heard end to end.
          if (clonedVoiceDownRef.current && sentenceText) {
            await new Promise<void>((resolve) => speakWithBrowser(sentenceText, resolve));
          }
          continue;
        }
        if (!isPlayingRef.current || controller.signal.aborted) {
          URL.revokeObjectURL(url);
          break;
        }

        await new Promise<void>((resolve) => {
          const audio = new Audio(url);
          currentAudioRef.current = audio;
          const done = () => {
            URL.revokeObjectURL(url);
            resolve();
          };
          audio.onended = done;
          audio.onerror = done;
          audio.play().catch(done);
        });
      }

      playing = false;
      if (inputClosed && playIndex >= pending.length) {
        isPlayingRef.current = false;
        onFinished?.();
      }
    };

    return {
      push(sentence: string) {
        if (!sentence.trim() || controller.signal.aborted) return;
        pendingText.push(sentence);
        pending.push(synthesize(sentence));   // synthesis starts immediately
        void playNext();
      },
      finish() {
        inputClosed = true;
        if (!playing && playIndex >= pending.length) {
          isPlayingRef.current = false;
          onFinished?.();
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
    if (isVoiceActive) {
      setVoiceState("thinking");
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
        if (isVoiceActive) setVoiceState("inactive");
        setIsLoading(false);
        return;
      }

      // ── Consume the SSE stream ──────────────────────────────────────────
      // Text appears as it is generated, and each completed sentence is sent
      // for synthesis immediately rather than after the whole answer.
      const shouldSpeak = readAloudEnabled || isVoiceActive;
      const speaker = shouldSpeak ? createStreamingSpeaker(() => {
        if (voiceStateRef.current === "speaking") setVoiceState("listening");
      }) : null;

      if (isVoiceActive) setVoiceState("speaking");

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let streamedText = "";
      let data: Record<string, unknown> = {};
      let streamError: string | null = null;

      // Placeholder assistant message that fills in as deltas arrive
      setSessions((prev) =>
        prev.map((s) =>
          s.id === activeSession.id
            ? { ...s, messages: [...updatedMessages, { role: "assistant" as const, content: "" }] }
            : s
        )
      );

      while (reader) {
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
          } else if (eventType === "meta") {
            data = { ...data, ...payload };
          } else if (eventType === "done") {
            data = { ...data, ...payload };
          } else if (eventType === "error") {
            streamError = payload.detail as string;
          }
        }
      }

      speaker?.finish();
      if (streamError) throw new Error(streamError);

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

    } catch (err: unknown) {
      console.error(err);
      const message = err instanceof Error ? err.message : "Unknown error";
      if (isVoiceActive) setVoiceState("inactive");
      // A network failure has no HTTP status, which classifyError reads as offline.
      setChatError(classifyError(null, message));
      setSessions((prev) =>
        prev.map((s) =>
          s.id === activeSession.id ? { ...s, messages: activeSession.messages } : s
        )
      );
    } finally {
      setIsLoading(false);
      // Wait for graph extraction to actually finish, instead of guessing with
      // blind 5s and 12s timers that either fired too early or wasted a
      // request after the work was already done.
      void waitForGraphExtraction(activeSession.id);
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
      <div className="flex-1 min-w-0 bg-[var(--surface)] border border-[var(--border)] rounded-2xl shadow-sm flex flex-col overflow-hidden">
        
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
              <div className="px-4 py-3 rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-sm flex items-center gap-1.5">
                <span className="typing-dot" />
                <span className="typing-dot" />
                <span className="typing-dot" />
                <span className="sr-only">Andrew is composing a reply</span>
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
              <p className="text-[12px] text-[var(--text-muted)] mb-2">Try asking:</p>
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
              ? "Andrew is composing a reply"
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
          onChange={setUserInput}
          onSubmit={handleSendMessage}
          onToggleRecording={handleToggleRecording}
          onStartVoice={() => setVoiceState("listening")}
        />
      </div>

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
          ttsSpeed={ttsSpeed}
          transcript={lastMsg?.role === "assistant" ? lastMsg.content : ""}
          clonedVoiceAvailable={clonedVoiceAvailable}
          closeRef={voiceCloseRef}
          onExit={() => {
            stopSpeaking();
            setVoiceState("inactive");
          }}
          onInterrupt={() => {
            if (voiceState === "speaking") {
              stopSpeaking();
              setVoiceState("listening");
            } else if (voiceState === "listening") {
              setVoiceState("inactive");
            }
          }}
          onMute={stopSpeaking}
          onSpeedDown={() => setTtsSpeed((prev) => Math.max(0.8, prev - 0.1))}
          onSpeedUp={() => setTtsSpeed((prev) => Math.min(1.5, prev + 0.1))}
        />
      )}
    </div>
  );
}
