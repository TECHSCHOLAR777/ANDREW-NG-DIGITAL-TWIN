import Link from "next/link"
import { ArrowRight, BookOpen, Mic, Network, Quote, Sparkles } from "lucide-react"

import { AndrewPortrait } from "@/components/andrew-portrait"
import { SiteHeader } from "@/components/site-header"
import { SiteFooter } from "@/components/site-footer"
import { AdaptiveConversation } from "@/components/marketing/adaptive-conversation"

/**
 * Portrait source. Drop a licensed photograph here and the hero picks it up.
 * Kept as one constant so swapping it is a single edit rather than a search.
 */
const PORTRAIT_SRC = "/andrew-portrait.png"

export const metadata = {
  title: "Andrew Ng Digital Twin",
  description:
    "Converse with a grounded, unofficial AI recreation of Andrew Ng's public knowledge, reasoning, and voice — with contextual memory across sessions.",
}

/**
 * Landing page.
 *
 * Positions the product as a general Andrew Ng digital twin — not a tutor —
 * within the first viewport, then proves each of its four ideas (grounded
 * corpus, adaptive persona, contextual continuity, voice embodiment) with a
 * concrete illustration rather than a paragraph. Marketing examples are curated
 * and clearly separated from any authenticated conversation. The page stays
 * cinematic-dark via the shared `.theme-dark` scope; every colour is a token,
 * so the light-mode redesign is a follow-on, not a rewrite.
 */
export default function LandingPage() {
  return (
    <div className="theme-dark min-h-screen bg-[var(--bg)] text-[var(--text)]">
      <SiteHeader />

      {/* ─── Hero ─────────────────────────────────────────────────────── */}
      <section className="relative isolate overflow-hidden">
        <div className="relative mx-auto grid min-h-[100svh] w-[min(1240px,calc(100%-2rem))] grid-cols-1 items-center gap-8 pt-28 pb-16 lg:grid-cols-[1.05fr_1fr] lg:gap-4 lg:pt-24">
          <div className="relative z-10 text-center lg:text-left">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-[var(--border)] bg-[var(--surface-hover)] px-3.5 py-1.5 text-[13px] text-[var(--text-muted)] backdrop-blur-sm">
              <Sparkles className="size-3.5 text-[var(--brand)]" />
              Unofficial, grounded AI recreation
            </span>

            <h1 className="mt-7 text-balance text-[2.5rem] font-semibold leading-[1.06] tracking-[-0.03em] sm:text-5xl lg:text-[3.5rem] lg:leading-[1.04] xl:text-[3.9rem]">
              A conversation with Andrew Ng&apos;s{" "}
              <span className="text-[var(--text-muted)]">
                knowledge and way of thinking
              </span>
            </h1>

            <p className="mx-auto mt-6 max-w-[52ch] text-pretty text-[15px] leading-[1.65] text-[var(--text-muted)] sm:text-[17px] lg:mx-0">
              Grounded in his own lectures, courses and letters. It adapts to
              researchers, engineers, founders, product leaders, and learners
              alike, remembers the context you share across sessions, and can
              answer in text or a synthetic voice.
            </p>

            <div className="mt-10 flex flex-col items-center gap-3 sm:flex-row sm:justify-center lg:justify-start">
              <Link
                href="/login"
                className="inline-flex w-full items-center justify-center gap-2 rounded-full bg-[var(--brand)] px-6 py-3 text-center text-sm font-medium text-[var(--brand-text)] transition-opacity hover:opacity-90 sm:w-auto"
              >
                Enter the Twin
                <ArrowRight className="size-4" />
              </Link>
              <Link
                href="/understand"
                className="inline-flex w-full items-center justify-center rounded-full border border-[var(--border)] bg-[var(--surface-hover)] px-6 py-3 text-center text-sm font-medium text-[var(--text)] backdrop-blur-sm transition-colors hover:bg-[var(--surface-alt)] sm:w-auto"
              >
                See how it works
              </Link>
            </div>

            <p className="mt-8 text-[13px] text-[var(--text-subtle)]">
              529 public sources · ~1.7M words · lectures, books, newsletters &amp; talks
            </p>
          </div>

          {/* On small screens the portrait sits behind the copy at low opacity;
              a block (not flex) parent so the absolutely-positioned canvas keeps
              its width. */}
          <div
            aria-hidden
            className="pointer-events-none absolute inset-0 z-0 opacity-40 lg:relative lg:inset-auto lg:z-10 lg:opacity-100"
          >
            <AndrewPortrait
              src={PORTRAIT_SRC}
              mode="hero"
              className="h-[360px] w-full lg:h-[460px] xl:h-[560px]"
            />
          </div>
        </div>

        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-[5] h-40 bg-gradient-to-b from-transparent to-[var(--bg)]" />
      </section>

      {/* ─── Proof band ───────────────────────────────────────────────── */}
      <section className="border-t border-[var(--border)]">
        <div className="mx-auto w-[min(1100px,calc(100%-2rem))] py-16 sm:py-20">
          <div className="grid grid-cols-2 gap-px overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--border)] sm:grid-cols-4">
            {[
              { n: "529", l: "cleaned source documents" },
              { n: "~1.7M", l: "words of public work" },
              { n: "2019–2026", l: "The Batch, spanning years" },
              { n: "Text + voice", l: "streamed, with memory" },
            ].map((s) => (
              <div key={s.l} className="bg-[var(--surface)] p-6">
                <div className="font-heading text-[1.6rem] font-semibold tracking-tight text-[var(--text)]">
                  {s.n}
                </div>
                <div className="mt-1.5 text-[13px] leading-snug text-[var(--text-muted)]">
                  {s.l}
                </div>
              </div>
            ))}
          </div>
          <p className="mt-5 max-w-[70ch] text-[13px] leading-relaxed text-[var(--text-subtle)]">
            Sources include CS229/CS230 lectures, <em>Machine Learning Yearning</em>,{" "}
            <em>How to Build a Career in AI</em>, The Batch, and DeepLearning.AI
            writing.
          </p>
        </div>
      </section>

      {/* ─── Adaptive conversation ────────────────────────────────────── */}
      <section className="border-t border-[var(--border)]">
        <div className="mx-auto w-[min(1100px,calc(100%-2rem))] py-20 sm:py-28">
          <div className="max-w-[46ch]">
            <h2 className="text-3xl font-semibold tracking-[-0.02em] sm:text-4xl">
              One presence, calibrated to whoever is asking
            </h2>
            <p className="mt-5 text-base leading-relaxed text-[var(--text-muted)]">
              The accuracy never changes. The depth, the notation, and the entry
              point do — the way a good mentor reads the room.
            </p>
          </div>
          <div className="mt-10">
            <AdaptiveConversation />
          </div>
        </div>
      </section>

      {/* ─── Grounding ────────────────────────────────────────────────── */}
      <section className="border-t border-[var(--border)]">
        <div className="mx-auto w-[min(1100px,calc(100%-2rem))] py-20 sm:py-28">
          <div className="grid gap-10 lg:grid-cols-[0.9fr_1.1fr] lg:items-center">
            <div className="max-w-[46ch]">
              <h2 className="text-3xl font-semibold tracking-[-0.02em] sm:text-4xl">
                Every answer traces back to the source
              </h2>
              <p className="mt-5 text-base leading-relaxed text-[var(--text-muted)]">
                A question runs against his public work through hybrid semantic
                and keyword retrieval. The answer is written from what came back
                — and you can open the exact passages behind it.
              </p>
              <p className="mt-4 text-[13px] text-[var(--text-subtle)]">
                When the material does not cover a question, the twin says so
                plainly rather than inventing a citation.
              </p>
            </div>

            {/* A compact illustration of the retrieval → answer → citation path */}
            <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5 sm:p-7">
              <p className="rounded-xl bg-[var(--surface-alt)] px-4 py-2.5 text-[14px] text-[var(--text)]">
                “What does Andrew mean by data-centric AI?”
              </p>
              <div className="my-4 flex items-center gap-2 text-[12px] text-[var(--brand)]">
                <span className="h-px flex-1 bg-gradient-to-r from-transparent via-[var(--brand)] to-[var(--brand)] opacity-60" />
                retrieved 3 passages
                <span className="h-px flex-1 bg-gradient-to-l from-transparent via-[var(--brand)] to-[var(--brand)] opacity-60" />
              </div>
              <p className="text-[15px] leading-relaxed text-[var(--text-muted)]">
                “So instead of endlessly tweaking the model, you systematically
                improve the data — the labels, the coverage, the edge cases…”
              </p>
              <div className="mt-5 flex flex-wrap gap-2">
                {["The Batch — Issue 84", "MLOps lecture, CS229", "A Chat with Andrew"].map(
                  (c) => (
                    <span
                      key={c}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--brand-soft)] px-2.5 py-1 text-[11px] text-[var(--brand)]"
                    >
                      <BookOpen className="size-3" />
                      {c}
                    </span>
                  )
                )}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ─── Continuity ───────────────────────────────────────────────── */}
      <section className="border-t border-[var(--border)]">
        <div className="mx-auto w-[min(1100px,calc(100%-2rem))] py-20 sm:py-28">
          <div className="max-w-[46ch]">
            <h2 className="text-3xl font-semibold tracking-[-0.02em] sm:text-4xl">
              It remembers where you left off
            </h2>
            <p className="mt-5 text-base leading-relaxed text-[var(--text-muted)]">
              A contextual-memory graph records what you share — your role, your
              projects, what you are building — and carries it forward. It is
              time-aware: revise something and the old version is retired, not
              left to contradict the new one.
            </p>
          </div>

          <div className="mt-10 grid gap-4 sm:grid-cols-[1fr_auto_1fr] sm:items-center">
            <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5">
              <div className="text-[11px] uppercase tracking-wider text-[var(--text-subtle)]">
                Last week
              </div>
              <p className="mt-2 text-[14px] text-[var(--text-muted)]">
                “I&apos;m leading a manufacturing vision-inspection project.”
              </p>
            </div>
            <div className="mx-auto grid size-9 place-items-center rounded-full border border-[var(--border)] text-[var(--brand)] sm:rotate-0">
              <Network className="size-4" />
            </div>
            <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5">
              <div className="text-[11px] uppercase tracking-wider text-[var(--text-subtle)]">
                Today
              </div>
              <p className="mt-2 text-[14px] text-[var(--text-muted)]">
                “Building on the inspection system you mentioned — here&apos;s how
                I&apos;d stage the data collection…”
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* ─── Voice preview ────────────────────────────────────────────── */}
      <section className="border-t border-[var(--border)]">
        <div className="mx-auto w-[min(1100px,calc(100%-2rem))] py-20 sm:py-28">
          <div className="grid gap-10 lg:grid-cols-[1fr_1fr] lg:items-center">
            <div className="order-2 lg:order-1">
              <span className="inline-flex items-center gap-1.5 rounded-full border border-[var(--border)] bg-[var(--surface-hover)] px-3 py-1 text-[12px] text-[var(--text-muted)]">
                <Mic className="size-3.5 text-[var(--brand)]" />
                Flagship voice mode
              </span>
              <h2 className="mt-5 text-3xl font-semibold tracking-[-0.02em] sm:text-4xl">
                Speak with the twin
              </h2>
              <p className="mt-5 max-w-[46ch] text-base leading-relaxed text-[var(--text-muted)]">
                Answers can be read aloud in a synthetic voice modelled on
                Andrew&apos;s, streamed sentence by sentence with visible
                listening, thinking, and speaking states. It carries a
                persistent “synthetic voice” label and an audio provenance
                watermark — it is never presented as a real recording.
              </p>
            </div>
            <div className="order-1 flex justify-center lg:order-2">
              <AndrewPortrait
                src={PORTRAIT_SRC}
                mode="identity"
                className="h-[240px] w-[240px] sm:h-[300px] sm:w-[300px]"
              />
            </div>
          </div>
        </div>
      </section>

      {/* ─── Pillars ──────────────────────────────────────────────────── */}
      <section className="border-t border-[var(--border)]">
        <div className="mx-auto w-[min(1100px,calc(100%-2rem))] py-20 sm:py-28">
          <div className="grid gap-px overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--border)] sm:grid-cols-2 [&>*]:bg-[var(--surface)] [&>*]:p-7">
            {[
              {
                icon: Quote,
                title: "Persona fidelity",
                body: "A calibrated voice built from his teaching, with mechanical checks against generic-assistant tells. It answers honestly when asked what it is.",
              },
              {
                icon: BookOpen,
                title: "Grounded public corpus",
                body: "529 documents and ~1.7M words. Structure-aware chunking keeps definitions with the passage that uses them.",
              },
              {
                icon: Network,
                title: "Contextual continuity",
                body: "A time-aware memory graph tracks context and connections, and lets you inspect, correct, or remove anything it recorded.",
              },
              {
                icon: Mic,
                title: "Voice embodiment",
                body: "Streamed synthetic speech with a browser fallback, an audio watermark, and a persistent synthetic-voice disclosure.",
              },
            ].map((p) => (
              <div key={p.title}>
                <p.icon className="size-5 text-[var(--brand)]" />
                <h3 className="mt-4 text-[16px] font-medium text-[var(--text)]">
                  {p.title}
                </h3>
                <p className="mt-2 text-[14px] leading-relaxed text-[var(--text-muted)]">
                  {p.body}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ─── Closing ──────────────────────────────────────────────────── */}
      <section className="border-t border-[var(--border)]">
        <div className="mx-auto w-[min(1100px,calc(100%-2rem))] py-24 text-center sm:py-32">
          <h2 className="mx-auto max-w-[22ch] text-balance text-3xl font-semibold tracking-[-0.02em] sm:text-4xl">
            Bring your own key. Nothing to pay.
          </h2>
          <p className="mx-auto mt-5 max-w-[54ch] text-base leading-relaxed text-[var(--text-muted)]">
            Your Gemini API key is sent through the backend to generate replies
            and is never stored. Your conversations and your memory graph belong
            to your account alone.
          </p>
          <Link
            href="/login"
            className="mt-10 inline-flex items-center gap-2 rounded-full bg-[var(--brand)] px-6 py-3 text-sm font-medium text-[var(--brand-text)] transition-opacity hover:opacity-90"
          >
            Enter the Twin
            <ArrowRight className="size-4" />
          </Link>
          <p className="mx-auto mt-6 max-w-[48ch] text-[12px] text-[var(--text-subtle)]">
            An unofficial, academic AI recreation. Not affiliated with or
            endorsed by Andrew Ng, DeepLearning.AI, or Stanford.
          </p>
        </div>
      </section>

      <SiteFooter />
    </div>
  )
}
