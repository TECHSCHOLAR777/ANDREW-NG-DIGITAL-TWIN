"use client";

import React, { useState, useEffect, useRef } from "react";
import {
  Send,
  Plus,
  Trash2,
  Key,
  BookOpen,
  Volume2,
  Mic,
  MicOff,
  Cpu,
  RefreshCw,
  Zap,
  Headphones,
  X,
  Sliders,
} from "lucide-react";
import { KnowledgeGraphView } from "../components/KnowledgeGraphView";
import type { TripletRow, EdgeRow } from "../types/graph";

// Local storage keys
const KEY_LOCAL_STORAGE_GEMINI = "andrew_ng_byok_key";
const KEY_LOCAL_STORAGE_TENANT = "andrew_ng_tenant_uuid";

interface RetrievedChunk {
  source_file: string;
  source_type: string;
  final_score: number;
}

interface Message {
  role: "user" | "assistant";
  content: string;
  cacheStatus?: string;
  retrievedChunks?: RetrievedChunk[];
}

interface ChatSession {
  id: string;
  title: string;
  messages: Message[];
  triplets: TripletRow[];
  edges: EdgeRow[];
}

// Helper to parse simple markdown bold, inline code, lists, and LaTeX math formatting
function formatMessageContent(text: string): React.ReactNode {
  if (!text) return null;

  // 1. Pre-process LaTeX math symbols to unicode equivalents and clean text representations
  let processed = text;

  // Replace common LaTeX fractions: \frac{a}{b} -> (a)/(b)
  processed = processed.replace(/\\frac\{([^}]+)\}\{([^}]+)\}/g, "($1)/($2)");

  // Replace LaTeX sum: \sum_{a}^{b} -> Σ_{a}^{b}
  processed = processed.replace(/\\sum_\{([^}]+)\}\^\{([^}]+)\}/g, "Σ_{$1}^{$2}");
  processed = processed.replace(/\\sum_\{([^}]+)\}/g, "Σ_{$1}");

  // Replace subscript formatting to subscript representation: e.g. \theta_j -> θ_j
  processed = processed.replace(/\\theta_([a-zA-Z0-9])/g, "θ_$1");
  processed = processed.replace(/\\theta_\{([^}]+)\}/g, "θ_($1)");
  
  // Replace other common subscripts
  processed = processed.replace(/_\{([^}]+)\}/g, "_($1)");

  const greekLetters: Record<string, string> = {
    '\\alpha': 'α',
    '\\beta': 'β',
    '\\gamma': 'γ',
    '\\delta': 'δ',
    '\\epsilon': 'ε',
    '\\zeta': 'ζ',
    '\\eta': 'η',
    '\\theta': 'θ',
    '\\iota': 'ι',
    '\\kappa': 'κ',
    '\\lambda': 'λ',
    '\\mu': 'μ',
    '\\nu': 'ν',
    '\\xi': 'ξ',
    '\\pi': 'π',
    '\\rho': 'ρ',
    '\\sigma': 'σ',
    '\\tau': 'τ',
    '\\upsilon': 'υ',
    '\\phi': 'φ',
    '\\chi': 'χ',
    '\\psi': 'ψ',
    '\\omega': 'ω',
  };
  
  for (const [latex, unicode] of Object.entries(greekLetters)) {
    processed = processed.replace(new RegExp(`\\\\?${latex.replace('\\', '\\\\')}`, 'g'), unicode);
  }
  
  // Remove standalone math mode wrapper signs $ ... $ or $$ ... $$
  processed = processed.replace(/\$\$/g, "");
  processed = processed.replace(/\$/g, "");
  
  // 2. Parse markdown formatting line-by-line
  const lines = processed.split("\n");
  const elements: React.ReactNode[] = [];
  let inList = false;
  let listItems: React.ReactNode[] = [];

  const parseInlineStyles = (lineText: string, keyPrefix: string): React.ReactNode[] => {
    // Split by ** for bold
    const boldParts = lineText.split("**");
    return boldParts.flatMap((boldPart, boldIndex) => {
      const isBold = boldIndex % 2 === 1;
      
      if (isBold) {
        return <strong key={`${keyPrefix}-b-${boldIndex}`} className="font-semibold text-slate-900">{boldPart}</strong>;
      } else {
        // Handle code blocks or inline code if any (e.g. `code`)
        const codeParts = boldPart.split("`");
        return codeParts.map((codePart, codeIndex) => {
          const isCode = codeIndex % 2 === 1;
          if (isCode) {
            return <code key={`${keyPrefix}-c-${codeIndex}`} className="bg-slate-100 px-1 py-0.5 rounded text-rose-600 font-mono text-[12px]">{codePart}</code>;
          }
          return codePart;
        });
      }
    });
  };

  lines.forEach((line, lineIdx) => {
    const trimmed = line.trim();
    
    // Check if it's a bullet point
    if (trimmed.startsWith("* ") || trimmed.startsWith("- ")) {
      if (!inList) {
        inList = true;
        listItems = [];
      }
      const itemContent = trimmed.substring(2);
      listItems.push(
        <li key={`li-${lineIdx}`} className="ml-4 list-disc mb-1.5 pl-1 text-slate-800">
          {parseInlineStyles(itemContent, `li-content-${lineIdx}`)}
        </li>
      );
    } else {
      if (inList) {
        elements.push(
          <ul key={`ul-${lineIdx}`} className="my-2 pl-4">
            {listItems}
          </ul>
        );
        inList = false;
        listItems = [];
      }
      
      if (trimmed === "") {
        elements.push(<div key={`br-${lineIdx}`} className="h-2" />);
      } else {
        elements.push(
          <p key={`p-${lineIdx}`} className="mb-2 text-slate-800">
            {parseInlineStyles(line, `p-content-${lineIdx}`)}
          </p>
        );
      }
    }
  });

  if (inList) {
    elements.push(
      <ul key="ul-final" className="my-2 pl-4">
        {listItems}
      </ul>
    );
  }

  return <div className="space-y-1">{elements}</div>;
}

export default function ChatPage() {
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [userInput, setUserInput] = useState("");
  const [geminiKey, setGeminiKey] = useState("");
  const [tenantId, setTenantId] = useState("");
  const [graphView, setGraphView] = useState<"session" | "global">("session");
  const [isLoading, setIsLoading] = useState(false);
  const [isSyncingGraph, setIsSyncingGraph] = useState(false);
  
  // Voice controls
  const [readAloudEnabled, setReadAloudEnabled] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [voiceState, setVoiceState] = useState<"inactive" | "listening" | "thinking" | "speaking">("inactive");
  
  // Pedagogical Speed and Catchphrase settings
  const [ttsSpeed, setTtsSpeed] = useState<number>(1.0);
  const useCatchphrases = true;

  // Ref handles for speech engines
  const recognitionRef = useRef<any>(null);
  const voiceStateRef = useRef<string>("inactive");

  // Custom Cloned TTS Audio Player Refs
  const currentAudioRef = useRef<HTMLAudioElement | null>(null);
  const audioQueueRef = useRef<{ text: string; audio: HTMLAudioElement | null; url: string }[]>([]);
  const isPlayingRef = useRef<boolean>(false);

  // Keep state sync ref for async timers/callbacks
  useEffect(() => {
    voiceStateRef.current = voiceState;
  }, [voiceState]);
  
  const chatBottomRef = useRef<HTMLDivElement>(null);

  // 1. Initial configuration load & Web Speech API setup
  useEffect(() => {
    // Load BYOK key
    const savedKey = localStorage.getItem(KEY_LOCAL_STORAGE_GEMINI) || "";
    setGeminiKey(savedKey);

    // Load or generate Tenant UUID for persistent cross-reload learning memory
    let savedTenant = localStorage.getItem(KEY_LOCAL_STORAGE_TENANT);
    if (!savedTenant || savedTenant === "undefined") {
      savedTenant = crypto.randomUUID();
      localStorage.setItem(KEY_LOCAL_STORAGE_TENANT, savedTenant);
    }
    setTenantId(savedTenant);

    // Build default initial session
    const initialSessionId = crypto.randomUUID();
    const defaultSession: ChatSession = {
      id: initialSessionId,
      title: "New Dialogue",
      messages: [
        {
          role: "assistant",
          content: "Hello! I am Andrew Ng. I teach machine learning concepts using CS229 notes and DeepLearning.ai resources. Ask me anything about neural networks, bias-variance analysis, or AI strategy."
        }
      ],
      triplets: [],
      edges: []
    };
    setSessions([defaultSession]);
    setActiveSessionId(initialSessionId);

    // Setup Speech Recognition
    if (typeof window !== "undefined") {
      const SpeechRecognition =
        (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
      if (SpeechRecognition) {
        const rec = new SpeechRecognition();
        rec.continuous = false;
        rec.interimResults = false;
        rec.lang = "en-US";

        rec.onresult = (event: any) => {
          const transcript = event.results[0][0].transcript;
          const isVoiceActive = voiceStateRef.current !== "inactive";
          if (isVoiceActive) {
            submitDialogueMessage(transcript);
          } else {
            setUserInput((prev) => (prev ? prev + " " + transcript : transcript));
          }
        };

        rec.onend = () => {
          if (voiceStateRef.current === "listening") {
            try {
              rec.start();
            } catch (e) {
              // Ignore
            }
          } else if (voiceStateRef.current === "inactive") {
            setIsRecording(false);
          }
        };

        rec.onerror = (event: any) => {
          console.error("Speech recognition error:", event);
          if (voiceStateRef.current === "listening" && event.error === "no-speech") {
            try {
              rec.start();
            } catch (e) {
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
  }, []);

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
      } catch (e) {
        // Safe to ignore
      }
    }
  }, [voiceState]);

  // 2. Scroll to bottom on new message
  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [sessions, activeSessionId]);

  const activeSession = sessions.find((s) => s.id === activeSessionId) || null;

  // Sync graph manually
  const handleSyncGraph = async (viewOverride?: "session" | "global") => {
    if (!activeSession || isSyncingGraph) return;
    setIsSyncingGraph(true);
    const viewToFetch = viewOverride || graphView;
    try {
      const response = await fetch(`http://127.0.0.1:8000/api/v1/chat/graph/${activeSession.id}?view=${viewToFetch}`, {
        headers: {
          "X-Gemini-Api-Key": geminiKey.trim() || "AIzaSy...",
          "X-Tenant-Id": tenantId
        }
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
  useEffect(() => {
    if (activeSession?.id && tenantId) {
      handleSyncGraph(graphView);
    }
  }, [activeSession?.id, graphView, tenantId]);

  const handleResetMemory = async () => {
    if (!window.confirm("Are you sure you want to reset your learning history? This will clear all extracted graph concepts and dialogue history in the database.")) {
      return;
    }
    try {
      await fetch("http://127.0.0.1:8000/api/v1/chat/clear", {
        method: "POST",
        headers: {
          "X-Gemini-Api-Key": geminiKey.trim() || "AIzaSy...",
          "X-Tenant-Id": tenantId
        }
      });
    } catch (e) {
      console.error("Failed to clear backend memory:", e);
    }

    const freshTenant = crypto.randomUUID();
    localStorage.setItem(KEY_LOCAL_STORAGE_TENANT, freshTenant);
    setTenantId(freshTenant);

    const newId = crypto.randomUUID();
    const defaultSession: ChatSession = {
      id: newId,
      title: "New Dialogue",
      messages: [
        {
          role: "assistant",
          content: "Hello! I am Andrew Ng. I teach machine learning concepts using CS229 notes and DeepLearning.ai resources. Ask me anything about neural networks, bias-variance analysis, or AI strategy."
        }
      ],
      triplets: [],
      edges: []
    };
    setSessions([defaultSession]);
    setActiveSessionId(newId);
  };

  // Save key to storage
  const handleSaveKey = (val: string) => {
    setGeminiKey(val);
    localStorage.setItem(KEY_LOCAL_STORAGE_GEMINI, val);
  };

  // Create new chat
  const handleNewChat = () => {
    const newId = crypto.randomUUID();
    const newSession: ChatSession = {
      id: newId,
      title: "New Dialogue",
      messages: [
        {
          role: "assistant",
          content: "Hello! What concept or project are we diving into today?"
        }
      ],
      triplets: [],
      edges: []
    };
    setSessions((prev) => [newSession, ...prev]);
    setActiveSessionId(newId);
  };

  // Delete chat
  const handleDeleteChat = (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    const filtered = sessions.filter((s) => s.id !== id);
    setSessions(filtered);
    if (activeSessionId === id) {
      if (filtered.length > 0) {
        setActiveSessionId(filtered[0].id);
      } else {
        const newId = crypto.randomUUID();
        const newSession: ChatSession = {
          id: newId,
          title: "New Dialogue",
          messages: [
            {
              role: "assistant",
              content: "Hello! What concept or project are we diving into today?"
            }
          ],
          triplets: [],
          edges: []
        };
        setSessions([newSession]);
        setActiveSessionId(newId);
      }
    }
  };
  // Cancel speech helper
  const stopSpeaking = () => {
    if (typeof window !== "undefined" && window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }
    if (currentAudioRef.current) {
      currentAudioRef.current.pause();
      currentAudioRef.current = null;
    }
    audioQueueRef.current = [];
    isPlayingRef.current = false;
  };

  // Voice Speech (TTS)
  const speakText = (text: string, onSpeechFinished?: () => void) => {
    const isVoiceActive = voiceStateRef.current !== "inactive";
    if (!readAloudEnabled && !isVoiceActive) return;

    // Stop any running speech first
    stopSpeaking();

    // Clean formatting characters to ensure smooth speech flow
    let cleanText = text.replace(/[*#`_\-]/g, "").trim();
    // Clean latex math symbols
    const greekLetters: Record<string, string> = {
      '\\alpha': 'alpha',
      '\\beta': 'beta',
      '\\gamma': 'gamma',
      '\\delta': 'delta',
      '\\epsilon': 'epsilon',
      '\\zeta': 'zeta',
      '\\eta': 'eta',
      '\\theta': 'theta',
      '\\iota': 'iota',
      '\\kappa': 'kappa',
      '\\lambda': 'lambda',
      '\\mu': 'mu',
      '\\nu': 'nu',
      '\\xi': 'xi',
      '\\pi': 'pi',
      '\\rho': 'rho',
      '\\sigma': 'sigma',
      '\\tau': 'tau',
      '\\upsilon': 'upsilon',
      '\\phi': 'phi',
      '\\chi': 'chi',
      '\\psi': 'psi',
      '\\omega': 'omega',
    };
    for (const [latex, name] of Object.entries(greekLetters)) {
      cleanText = cleanText.replace(new RegExp(`\\$?${latex.replace('\\', '\\\\')}\\$?`, 'g'), name);
    }
    cleanText = cleanText.replace(/\$([^$]+)\$/g, '$1');

    // Content-adaptive speed: auto-slow down for complex equations or code blocks
    let dynamicSpeed = ttsSpeed;
    if (ttsSpeed === 1.0) {
      const hasMathOrCode = /```|[\$\\\{\}\_\]\[\^=+\-*\/]/.test(text) && text.length > 50;
      if (hasMathOrCode) {
        dynamicSpeed = 0.88; // Slow down slightly for math and code formulations
      }
    }

    // Split text into sentences using lookbehind pattern
    const rawSentences = cleanText.split(/(?<=[.!?])\s+/);
    const sentences = rawSentences.map(s => s.trim()).filter(s => s.length > 0);

    if (sentences.length === 0) {
      if (onSpeechFinished) onSpeechFinished();
      return;
    }

    // Build audio queue items
    const queue = sentences.map(s => {
      const url = `http://127.0.0.1:8000/api/v1/chat/tts?text=${encodeURIComponent(s)}`;
      return { text: s, audio: null as HTMLAudioElement | null, url };
    });

    audioQueueRef.current = queue;
    isPlayingRef.current = true;

    // Define function to play a specific queue item
    const playQueueIndex = (index: number) => {
      if (!isPlayingRef.current || index >= queue.length) {
        isPlayingRef.current = false;
        if (onSpeechFinished) onSpeechFinished();
        return;
      }

      const item = queue[index];
      let audio = item.audio;

      if (!audio) {
        audio = new Audio(item.url);
        item.audio = audio;
      }

      audio.playbackRate = dynamicSpeed;
      currentAudioRef.current = audio;

      audio.onended = () => {
        playQueueIndex(index + 1);
      };

      audio.onerror = (e) => {
        console.error("Audio playback error for sentence:", item.text, e);
        playQueueIndex(index + 1);
      };

      audio.play().catch(err => {
        console.error("Failed to start audio playback:", err);
        playQueueIndex(index + 1);
      });

      // Pre-fetch next item
      if (index + 1 < queue.length) {
        const nextItem = queue[index + 1];
        if (!nextItem.audio) {
          const nextAudio = new Audio(nextItem.url);
          nextAudio.preload = "auto";
          nextAudio.playbackRate = dynamicSpeed;
          nextItem.audio = nextAudio;
        }
      }
    };

    playQueueIndex(0);
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

    // Optional Persona prompts injection
    let payloadMessage = messageText;
    if (useCatchphrases) {
      payloadMessage += "\n\n(Persona reminder: Do NOT open with any compliment about the question — no 'Great question', 'That's a thoughtful question', etc. Start with substance. Ground claims in retrieved sources when possible. Use Andrew's natural connectives: 'so', 'actually', 'right?', 'I think'. End with a concrete next step or a targeted comprehension check, never 'does that make sense?')";
    }

    const updatedMessages = [
      ...activeSession.messages,
      { role: "user" as const, content: messageText }
    ];

    setSessions((prev) =>
      prev.map((s) =>
        s.id === activeSession.id
          ? {
              ...s,
              title: s.title === "New Dialogue" ? messageText.slice(0, 24) + "..." : s.title,
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

      const response = await fetch("http://127.0.0.1:8000/api/v1/chat/message", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Gemini-Api-Key": geminiKey.trim() || "AIzaSy...",
          "X-Tenant-Id": tenantId
        },
        body: JSON.stringify({
          session_id: activeSession.id,
          message: payloadMessage,
          turn_history: turnHistory,
          temperature: 0.2
        })
      });

      if (!response.ok) {
        if (response.status === 429) {
          throw new Error("Gemini API rate limit reached. Please wait a moment and try again.");
        }
        const errBody = await response.json().catch(() => null);
        const detail = errBody?.detail || response.statusText;
        throw new Error(`Server error (${response.status}): ${detail}`);
      }

      const data = await response.json();
      const assistantText = data.assistant_message;

      if (isVoiceActive) {
        setVoiceState("speaking");
        speakText(assistantText, () => {
          if (voiceStateRef.current === "speaking") {
            setVoiceState("listening");
          }
        });
      } else {
        speakText(assistantText);
      }

      const rawGraph: any[] = data.graph_context || [];
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
                    cacheStatus: data.cache_status,
                    retrievedChunks: data.retrieved_chunks
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

    } catch (err: any) {
      console.error(err);
      if (isVoiceActive) {
        setVoiceState("inactive");
      }
      setSessions((prev) =>
        prev.map((s) =>
          s.id === activeSession.id
            ? {
                ...s,
                messages: [
                  ...updatedMessages,
                  { role: "assistant" as const, content: `Error communicating with backend: ${err.message}.` }
                ]
              }
            : s
        )
      );
    } finally {
      setIsLoading(false);
      // Automatically refresh the knowledge graph after delays
      // to allow the background extraction task to complete in the database.
      setTimeout(() => {
        handleSyncGraph();
      }, 5000);
      // Second refresh to catch slower extractions
      setTimeout(() => {
        handleSyncGraph();
      }, 12000);
    }
  };

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!userInput.trim() || isLoading) return;
    const msg = userInput;
    setUserInput("");
    await submitDialogueMessage(msg);
  };

  // Old handleSyncGraph location removed (moved to top of file)

  return (
    <div className="flex h-screen w-screen overflow-hidden text-[#111827] bg-[#F7F8FA] p-4 gap-4">
      
      {/* ──────────────────────────────────────────────────
          1. SIDEBAR (Left panel)
          ────────────────────────────────────────────────── */}
      <div className="w-80 bg-white border border-[#E5E7EB] rounded-2xl shadow-sm flex flex-col overflow-hidden">
        
        {/* Header / Logo */}
        <div className="p-5 border-b border-[#E5E7EB] flex items-center gap-3">
          <BookOpen className="text-[#1A56DB] w-5 h-5" />
          <div>
            <h1 className="font-semibold text-[14px] text-[#111827]">Andrew Ng</h1>
            <p className="text-[11px] text-[#6B7280] font-normal tracking-[0.07em]">Digital twin</p>
          </div>
        </div>

        {/* API Settings */}
        <div className="p-4 border-b border-[#E5E7EB] flex flex-col gap-3">
          <label className="text-[11px] font-medium text-[#6B7280] tracking-[0.07em] flex items-center gap-1.5">
            <Key className="w-4 h-4 text-[#1A56DB]" />
            Developer API key
          </label>
          <input
            type="password"
            placeholder="AIzaSy..."
            value={geminiKey}
            onChange={(e) => handleSaveKey(e.target.value)}
            className="w-full bg-[#FFFFFF] border border-[#E5E7EB] text-[13px] px-3 py-2 rounded-lg text-[#111827] placeholder-[#9CA3AF] focus:outline-none focus:border-[#1A56DB] focus:ring-1 focus:ring-[#1A56DB] transition"
          />
        </div>

        {/* Twin Dialectics / Pedagogical Settings */}
        <div className="p-4 border-b border-[#E5E7EB] flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-medium text-[#6B7280] tracking-[0.07em] flex items-center gap-1.5">
              <Sliders className="w-4 h-4 text-[#1A56DB]" />
              Pedagogical voice
            </span>
          </div>
          <div className="flex flex-col gap-2">
            <label className="text-[12px] text-[#6B7280] font-normal flex justify-between">
              <span>Speech rate:</span>
              <span className="text-[#1A56DB] font-medium">{ttsSpeed.toFixed(2)}x</span>
            </label>
            <input
              type="range"
              min="0.8"
              max="1.5"
              step="0.05"
              value={ttsSpeed}
              onChange={(e) => setTtsSpeed(parseFloat(e.target.value))}
              className="w-full h-1 bg-[#E5E7EB] rounded-lg appearance-none cursor-pointer accent-[#1A56DB]"
            />
          </div>
        </div>

        {/* Memory Management */}
        <div className="p-4 border-b border-[#E5E7EB] flex flex-col gap-3">
          <label className="text-[11px] font-medium text-[#6B7280] tracking-[0.07em] flex items-center gap-1.5">
            <Cpu className="w-4 h-4 text-[#1A56DB]" />
            Memory management
          </label>
          <button
            onClick={handleResetMemory}
            className="w-full border border-red-200 hover:bg-red-50 text-red-600 font-medium text-[13px] py-2.5 rounded-lg flex items-center justify-center gap-2 transition"
          >
            <Trash2 className="w-4 h-4" />
            Reset learning memory
          </button>
        </div>

        {/* New Chat Action */}
        <div className="p-4">
          <button
            onClick={handleNewChat}
            className="w-full bg-[#1A56DB] hover:bg-[#1A56DB]/90 text-white font-medium text-[13px] py-2.5 rounded-lg flex items-center justify-center gap-2 transition shadow-sm"
          >
            <Plus className="w-4 h-4" />
            New conversation
          </button>
        </div>

        {/* Session List */}
        <div className="flex-1 overflow-y-auto px-3 py-2 flex flex-col gap-1.5">
          {sessions.map((session) => {
            const isActive = session.id === activeSessionId;
            return (
              <div
                key={session.id}
                onClick={() => {
                  setActiveSessionId(session.id);
                  stopSpeaking();
                }}
                className={`group px-3 py-2.5 rounded-lg cursor-pointer flex items-center justify-between transition ${
                  isActive ? "bg-[#E8EEFB] border border-[#E5E7EB] text-[#1A56DB]" : "hover:bg-[#F7F8FA] text-[#6B7280] hover:text-[#111827]"
                }`}
              >
                <span className="text-[13px] font-normal truncate max-w-[160px]">{session.title}</span>
                <button
                  onClick={(e) => handleDeleteChat(session.id, e)}
                  className="opacity-0 group-hover:opacity-100 p-1 text-[#6B7280] hover:text-red-500 transition"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            );
          })}
        </div>
      </div>

      {/* ──────────────────────────────────────────────────
          2. CENTRAL PANEL (Chat bubbles window)
          ────────────────────────────────────────────────── */}
      <div className="flex-1 bg-white border border-[#E5E7EB] rounded-2xl shadow-sm flex flex-col overflow-hidden">
        
        {/* Top bar with Online status */}
        <div className="h-16 border-b border-[#E5E7EB] px-6 flex items-center justify-between bg-white">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-[#1A56DB] text-white flex items-center justify-center font-semibold text-[14px]">AN</div>
            <div>
              <h2 className="text-[14px] font-medium text-[#111827]">Andrew Ng</h2>
              <span className="text-[11px] text-green-600 font-normal flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-green-600 animate-pulse" />
                Grounded twin • Online
              </span>
            </div>
          </div>
          
          <div className="flex items-center gap-3">
            {/* Read aloud toggle */}
            <button
              onClick={() => {
                setReadAloudEnabled(!readAloudEnabled);
                stopSpeaking();
              }}
              className={`p-2 rounded-lg border transition ${
                readAloudEnabled
                  ? "bg-[#E8EEFB] border-[#D1D5DB] text-[#1A56DB]"
                  : "border-[#E5E7EB] text-[#6B7280] hover:text-[#111827] hover:bg-[#F7F8FA]"
              }`}
              title="Toggle read aloud"
            >
              <Volume2 className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Dialogue history scroll bubble */}
        <div className="flex-1 overflow-y-auto p-6 flex flex-col gap-6">
          {activeSession?.messages.map((msg, index) => {
            const isUser = msg.role === "user";
            return (
              <div
                key={index}
                className={`flex gap-4 max-w-3xl ${isUser ? "ml-auto flex-row-reverse" : ""}`}
              >
                {/* Avatar */}
                <div
                  className={`w-8 h-8 rounded-full flex items-center justify-center font-medium text-[13px] flex-shrink-0 ${
                    isUser ? "bg-[#6B7280] text-white" : "bg-[#1A56DB] text-white"
                  }`}
                >
                  {isUser ? "S" : "AN"}
                </div>
                
                {/* Message Box */}
                <div className={`flex flex-col gap-3 p-4 rounded-2xl text-[13px] leading-relaxed border whitespace-pre-wrap ${
                  isUser ? "border-[#E5E7EB] bg-[#F7F8FA] text-[#111827]" : "border-[#E5E7EB] bg-white text-[#111827] shadow-sm"
                }`}>
                  <div className="w-full">{formatMessageContent(msg.content)}</div>

                  {/* Cache Status Badge */}
                  {!isUser && msg.cacheStatus && (
                    <div className="flex items-center gap-1.5 text-[11px] font-normal mt-1">
                      {msg.cacheStatus === "hit" ? (
                        <span className="flex items-center gap-0.5 text-cyan-800 bg-cyan-50 px-2 py-0.5 rounded-full border border-cyan-200">
                          <Zap className="w-3 h-3 fill-cyan-700 text-cyan-700" />
                          Context cache hit (saved tokens)
                        </span>
                      ) : msg.cacheStatus === "miss" ? (
                        <span className="text-[#6B7280] bg-[#F7F8FA] px-2 py-0.5 rounded-full border border-[#E5E7EB]">
                          Context cache miss (cold session)
                        </span>
                      ) : null}
                    </div>
                  )}

                  {/* Citation Badges */}
                  {!isUser && msg.retrievedChunks && msg.retrievedChunks.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mt-2 border-t border-[#E5E7EB] pt-2">
                      <span className="text-[11px] text-[#6B7280] font-medium block w-full">Grounding sources:</span>
                      {msg.retrievedChunks.slice(0, 3).map((chunk, cIdx) => (
                        <span
                          key={cIdx}
                          title={`Score: ${chunk.final_score.toFixed(4)}`}
                          className="text-[11px] text-[#1A56DB] hover:text-[#1A56DB]/80 bg-[#E8EEFB] px-2 py-1 rounded-lg border border-[#E5E7EB] max-w-[180px] truncate cursor-help flex items-center gap-1"
                        >
                          <BookOpen className="w-3 h-3 text-[#1A56DB] flex-shrink-0" />
                          {chunk.source_file.replace(/_/g, " ").replace(".txt", "")}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
          {isLoading && (
            <div className="flex gap-4 max-w-3xl loading-glow">
              <div className="w-8 h-8 rounded-full bg-[#1A56DB] text-white flex items-center justify-center font-medium text-[13px]">AN</div>
              <div className="p-4 rounded-2xl text-[13px] border border-[#E5E7EB] bg-white text-[#111827] shadow-sm">
                Thinking...
              </div>
            </div>
          )}
          <div ref={chatBottomRef} />
        </div>

        {/* Input box */}
        <div className="p-6 border-t border-[#E5E7EB] flex flex-col gap-3">
          


          <form onSubmit={handleSendMessage} className="flex gap-3">
            <div className="flex-1 relative">
              <input
                type="text"
                value={userInput}
                onChange={(e) => setUserInput(e.target.value)}
                placeholder={isRecording ? "Listening..." : "Ask Andrew a question about ML models..."}
                disabled={isLoading}
                className="w-full bg-white border border-[#E5E7EB] text-[13px] px-4 py-3.5 pr-20 rounded-xl focus:outline-none focus:border-[#1A56DB] focus:ring-1 focus:ring-[#1A56DB] text-[#111827] placeholder-[#9CA3AF] transition"
              />
              <button
                type="button"
                onClick={() => {
                  setVoiceState("listening");
                }}
                className="absolute right-10 top-3.5 text-[#6B7280] hover:text-[#1A56DB] transition animate-pulse"
                title="Start voice dialogue mode"
              >
                <Headphones className="w-4 h-4" />
              </button>
              <button
                type="button"
                onClick={handleToggleRecording}
                className={`absolute right-3 top-3.5 transition ${
                  isRecording ? "text-red-500 hover:text-red-700" : "text-[#6B7280] hover:text-[#1A56DB]"
                }`}
                title={isRecording ? "Stop recording" : "Record voice input"}
              >
                {isRecording ? <MicOff className="w-4 h-4" /> : <Mic className="w-4 h-4" />}
              </button>
            </div>
            
            <button
              type="submit"
              disabled={isLoading}
              className="bg-[#1A56DB] hover:bg-[#1A56DB]/90 disabled:opacity-50 text-white p-3.5 rounded-xl flex items-center justify-center transition shadow-sm"
            >
              <Send className="w-4 h-4" />
            </button>
          </form>
        </div>
      </div>

      {/* ──────────────────────────────────────────────────
          3. GRAPH MEMORY MATRIX (Right panel)
          ────────────────────────────────────────────────── */}
      <div className="w-[480px] bg-white border border-[#E5E7EB] rounded-2xl shadow-sm flex flex-col overflow-hidden">
        
        {/* Header with Sync buttons & View Toggle */}
        <div className="p-4 border-b border-[#E5E7EB] flex items-center justify-between bg-white">
          <div className="flex items-center gap-2">
            <Cpu className="text-[#1A56DB] w-4 h-4" />
            <h2 className="text-[14px] font-medium text-[#111827]">Memory matrix</h2>
          </div>
          
          {/* Segment control toggle & Sync button */}
          <div className="flex items-center gap-3">
            <div className="flex bg-[#F3F4F6] p-0.5 rounded-lg border border-[#E5E7EB]">
              <button
                onClick={() => setGraphView("session")}
                className={`px-2.5 py-1 text-[11px] font-medium rounded-md transition-all ${
                  graphView === "session"
                    ? "bg-white text-[#111827] shadow-sm"
                    : "text-[#6B7280] hover:text-[#111827]"
                }`}
              >
                Active Chat
              </button>
              <button
                onClick={() => setGraphView("global")}
                className={`px-2.5 py-1 text-[11px] font-medium rounded-md transition-all ${
                  graphView === "global"
                    ? "bg-white text-[#111827] shadow-sm"
                    : "text-[#6B7280] hover:text-[#111827]"
                }`}
              >
                Global Map
              </button>
            </div>
            
            <button
              onClick={() => handleSyncGraph(graphView)}
              disabled={isSyncingGraph}
              className="p-1.5 rounded-lg border border-[#E5E7EB] hover:bg-[#F7F8FA] text-[#6B7280] transition"
              title="Refresh knowledge graph"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${isSyncingGraph ? "animate-spin" : ""}`} />
            </button>
          </div>
        </div>

        {/* Network visualizer graph */}
        <div className="flex-1 relative h-full w-full">
          <KnowledgeGraphView
            triplets={activeSession?.triplets || []}
            edges={activeSession?.edges || []}
            isLoading={isSyncingGraph}
            width="100%"
            height="100%"
            onExploreNode={(concept) => {
              setUserInput(`Explain the concept of ${concept} and its connections in detail.`);
              submitDialogueMessage(`Explain the concept of ${concept} and its connections in detail.`);
            }}
          />
        </div>
      </div>

      {/* ──────────────────────────────────────────────────
          4. INTERACTIVE VOICE OVERLAY (Glass modal)
          ────────────────────────────────────────────────── */}
      {voiceState !== "inactive" && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/35 backdrop-blur-sm transition-all duration-300">
          
          <div className="relative max-w-[400px] w-full bg-white rounded-2xl border border-slate-200 shadow-2xl p-10 flex flex-col items-center">
            
            {/* Sleek Ghost Close Button inside card top-right */}
            <button
              onClick={() => {
                stopSpeaking();
                setVoiceState("inactive");
              }}
              className="absolute top-4 right-4 w-7 h-7 flex items-center justify-center rounded-full border border-slate-200 hover:bg-slate-100 text-slate-500 hover:text-slate-700 transition cursor-pointer"
              title="Exit Voice Mode"
            >
              <X className="w-4 h-4" />
            </button>

            {/* Audio Waveform Visualization: 9 dynamic vertical bars */}
            <div className={`waveform-container ${
              voiceState === "listening" ? "waveform-listening" :
              voiceState === "thinking" ? "waveform-thinking" :
              "waveform-speaking"
            } mb-8`}>
              <div className="waveform-bar bar-1" />
              <div className="waveform-bar bar-2" />
              <div className="waveform-bar bar-3" />
              <div className="waveform-bar bar-4" />
              <div className="waveform-bar bar-5" />
              <div className="waveform-bar bar-6" />
              <div className="waveform-bar bar-7" />
              <div className="waveform-bar bar-8" />
              <div className="waveform-bar bar-9" />
            </div>

            {/* Central control button */}
            <button
              onClick={() => {
                if (voiceState === "speaking") {
                  stopSpeaking();
                  setVoiceState("listening");
                } else if (voiceState === "listening") {
                  setVoiceState("inactive");
                }
              }}
              className="px-6 py-2.5 bg-[#1A56DB] hover:bg-[#1A56DB]/90 text-white rounded-full text-[13px] font-medium mb-6 transition"
            >
              {voiceState === "listening" ? "Stop listening" : "Tap to interrupt"}
            </button>

            {/* Voice Status Text */}
            <p className="text-[13px] text-[#6B7280] font-normal mb-6 text-center capitalize">
              {voiceState}...
            </p>

            {/* Speed controller inside voice modal */}
            <div className="flex items-center gap-3 bg-[#F7F8FA] border border-[#E5E7EB] px-3 py-1.5 rounded-full">
              <button
                onClick={() => setTtsSpeed(prev => Math.max(0.8, prev - 0.1))}
                className="text-xs text-[#6B7280] hover:text-[#111827] px-1 font-bold cursor-pointer"
              >
                -
              </button>
              <span className="text-[12px] text-[#1A56DB] font-medium min-w-[32px] text-center">{ttsSpeed.toFixed(1)}x</span>
              <button
                onClick={() => setTtsSpeed(prev => Math.min(1.5, prev + 0.1))}
                className="text-xs text-[#6B7280] hover:text-[#111827] px-1 font-bold cursor-pointer"
              >
                +
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
