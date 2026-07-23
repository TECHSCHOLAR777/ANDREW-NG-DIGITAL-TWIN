// Shared types and constants for the conversation workspace.
//
// Pulled out of the page component so the presentational pieces (session rail,
// transcript, composer, context panel, voice overlay) can import the same
// contracts without dragging the whole page in. Behaviour is unchanged; this is
// only where the definitions live.
import type { TripletRow, EdgeRow } from "@/types/graph"

export const KEY_LOCAL_STORAGE_GEMINI = "andrew_ng_byok_key"
export const KEY_LOCAL_STORAGE_TENANT = "andrew_ng_tenant_uuid"
export const KEY_LOCAL_STORAGE_ACTIVE = "andrew_ng_active_session"

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000"

// Shown on an untouched conversation. Concrete questions teach what the twin is
// for far faster than any description.
export const SUGGESTED_QUESTIONS = [
  "What is gradient descent?",
  "Explain the bias-variance tradeoff",
  "How should I actually start learning ML?",
]

export interface RetrievedChunk {
  source_file: string
  source_type: string
  final_score: number
  chunk_text?: string
}

export interface Message {
  role: "user" | "assistant"
  content: string
  /** Concepts from earlier sessions that informed this answer. */
  recalled?: string[]
  cacheStatus?: string
  cachedTokenCount?: number
  isGrounded?: boolean
  retrievedChunks?: RetrievedChunk[]
}

export interface GraphContextNode {
  node_id: string
  canonical_name: string
  node_type: TripletRow["node_type"]
  hop_distance: number
  combined_score: number
}

export interface ChatSession {
  id: string
  title: string
  messages: Message[]
  triplets: TripletRow[]
  edges: EdgeRow[]
}

export type VoiceState = "inactive" | "listening" | "thinking" | "speaking"

// ── Browser speech-recognition typings (no DOM lib guarantee across targets) ──
export type SpeechRecognitionConstructor = new () => SpeechRecognitionLike

export interface SpeechRecognitionResultEventLike {
  results: {
    [index: number]: { [index: number]: { transcript: string } }
  }
}

export interface SpeechRecognitionErrorEventLike {
  error: string
}

export interface SpeechRecognitionLike {
  continuous: boolean
  interimResults: boolean
  lang: string
  onresult: ((event: SpeechRecognitionResultEventLike) => void) | null
  onend: (() => void) | null
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null
  start: () => void
  stop: () => void
}

export type SpeechWindow = Window &
  typeof globalThis & {
    SpeechRecognition?: SpeechRecognitionConstructor
    webkitSpeechRecognition?: SpeechRecognitionConstructor
  }
