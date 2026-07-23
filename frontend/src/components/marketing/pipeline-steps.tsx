"use client"

import * as React from "react"
import { BookOpen, Check, Mic, RotateCcw, Search, Trash2 } from "lucide-react"

import { cn } from "@/lib/utils"

/**
 * The "how it works" pipeline.
 *
 * Six stages, each with a real interface illustration rather than a paragraph
 * set beside a large number. A slim rail on the left fills with the brand
 * colour as the reader scrolls, which reads as one signal travelling through
 * the pipeline. The fill is written straight to the DOM in the scroll handler
 * (no React state, so no re-render churn), and reduced-motion users get a
 * complete static rail. Every stage is fully legible with motion disabled.
 */
export function PipelineSteps() {
  const containerRef = React.useRef<HTMLDivElement | null>(null)
  const fillRef = React.useRef<HTMLDivElement | null>(null)

  React.useEffect(() => {
    const container = containerRef.current
    const fill = fillRef.current
    if (!container || !fill) return

    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      fill.style.height = "100%"
      return
    }

    let ticking = false
    const update = () => {
      ticking = false
      const rect = container.getBoundingClientRect()
      const mid = window.innerHeight * 0.5
      const progress = (mid - rect.top) / rect.height
      const clamped = Math.max(0, Math.min(1, progress))
      fill.style.height = `${clamped * 100}%`
    }
    const onScroll = () => {
      if (ticking) return
      ticking = true
      requestAnimationFrame(update)
    }
    update()
    window.addEventListener("scroll", onScroll, { passive: true })
    window.addEventListener("resize", onScroll)
    return () => {
      window.removeEventListener("scroll", onScroll)
      window.removeEventListener("resize", onScroll)
    }
  }, [])

  return (
    <div ref={containerRef} className="relative">
      {/* Rail */}
      <div className="absolute left-[15px] top-2 bottom-2 w-px bg-[var(--border)] sm:left-[19px]">
        <div
          ref={fillRef}
          className="w-px bg-[var(--brand)]"
          style={{ height: "0%" }}
        />
      </div>

      <ol className="space-y-16 sm:space-y-24">
        {STEPS.map((step, i) => (
          <li key={step.title} className="relative grid grid-cols-[32px_1fr] gap-4 sm:grid-cols-[40px_1fr] sm:gap-8">
            <div className="relative z-10">
              <span className="grid size-8 place-items-center rounded-full border border-[var(--border)] bg-[var(--surface)] text-[12px] font-semibold text-[var(--text-muted)] sm:size-10 sm:text-[13px]">
                {String(i + 1).padStart(2, "0")}
              </span>
            </div>
            <div className="pt-1">
              <h2 className="text-xl font-semibold tracking-[-0.01em] sm:text-2xl">
                {step.title}
              </h2>
              <p className="mt-3 max-w-[58ch] leading-relaxed text-[var(--text-muted)]">
                {step.body}
              </p>
              <div className="mt-6">{step.figure}</div>
            </div>
          </li>
        ))}
      </ol>
    </div>
  )
}

/* ── Small illustration helpers, all built from tokens ── */

function Panel({
  className,
  children,
}: {
  className?: string
  children: React.ReactNode
}) {
  return (
    <div
      className={cn(
        "rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4 sm:p-5",
        className
      )}
    >
      {children}
    </div>
  )
}

function Chip({
  children,
  tone = "neutral",
  icon,
}: {
  children: React.ReactNode
  tone?: "neutral" | "brand"
  icon?: React.ReactNode
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[12px]",
        tone === "brand"
          ? "border-[color-mix(in_srgb,var(--brand)_28%,transparent)] bg-[var(--brand-soft)] text-[var(--brand)]"
          : "border-[var(--border)] bg-[var(--surface-alt)] text-[var(--text-muted)]"
      )}
    >
      {icon}
      {children}
    </span>
  )
}

const CORPUS = [
  { name: "The Batch", detail: "373 issues, 2019 to 2026" },
  { name: "DeepLearning.AI", detail: "130 blog and community posts" },
  { name: "CS229 and CS230", detail: "23 cleaned lecture transcripts" },
  { name: "Books and guides", detail: "CS229 notes, ML Yearning, Career in AI" },
]

const STEPS: { title: string; body: string; figure: React.ReactNode }[] = [
  {
    title: "It reads from a real body of work",
    body: "Every answer starts from Andrew Ng's public writing and lectures: 529 cleaned documents, about 1.7 million words. The material is split around headings and section boundaries, so a retrieved passage keeps the definitions and notation it depends on.",
    figure: (
      <div className="grid gap-2 sm:grid-cols-2">
        {CORPUS.map((c) => (
          <Panel key={c.name} className="flex items-start gap-3">
            <BookOpen className="mt-0.5 size-4 shrink-0 text-[var(--brand)]" />
            <div>
              <div className="text-[14px] font-medium text-[var(--text)]">
                {c.name}
              </div>
              <div className="text-[12px] text-[var(--text-muted)]">
                {c.detail}
              </div>
            </div>
          </Panel>
        ))}
      </div>
    ),
  },
  {
    title: "It retrieves before it answers",
    body: "Your question runs two searches at once. One matches meaning, so a casually worded question still finds the right lecture. The other matches exact terms, so specific names and equations are not lost. The results are fused, and the answer is written from what came back.",
    figure: (
      <Panel>
        <div className="rounded-xl bg-[var(--surface-alt)] px-3 py-2 text-[13px] text-[var(--text)]">
          &ldquo;How does Andrew think about bias versus variance?&rdquo;
        </div>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          <div className="flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-[12px] text-[var(--text-muted)]">
            <Search className="size-3.5 text-[var(--brand)]" />
            Meaning search
          </div>
          <div className="flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-2 text-[12px] text-[var(--text-muted)]">
            <Search className="size-3.5 text-[var(--brand)]" />
            Keyword search
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <Chip tone="brand" icon={<BookOpen className="size-3" />}>
            CS229, lecture notes
          </Chip>
          <Chip tone="brand" icon={<BookOpen className="size-3" />}>
            The Batch, Issue 62
          </Chip>
        </div>
      </Panel>
    ),
  },
  {
    title: "It speaks in one voice, at your level",
    body: "The identity stays the same. What changes is the depth, the notation, and where the explanation starts. A researcher gets the assumptions and failure modes. A product leader gets the decision and the metric. A beginner gets an example first.",
    figure: (
      <Panel>
        <div className="flex items-center justify-between text-[12px] text-[var(--text-subtle)]">
          <span>Beginner</span>
          <span>Researcher</span>
        </div>
        <div className="mt-2 h-1.5 rounded-full bg-[var(--surface-alt)]">
          <div className="h-1.5 w-2/3 rounded-full bg-[var(--brand)]" />
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {["Founder", "Engineer", "Product lead", "Student", "Researcher"].map(
            (a) => (
              <Chip key={a}>{a}</Chip>
            )
          )}
        </div>
      </Panel>
    ),
  },
  {
    title: "It remembers your context, and you control it",
    body: "As you talk, it records what matters for later: your role, your projects, what you are building, what you have understood. Every item keeps the quote that produced it, and you can correct or remove any of it. Revise something and the old version is retired, not left to contradict the new one.",
    figure: (
      <Panel>
        <div className="flex flex-wrap items-center gap-2">
          <Chip tone="brand">You</Chip>
          <span className="text-[var(--text-subtle)]">leads</span>
          <Chip>Vision inspection project</Chip>
        </div>
        <div className="mt-3 border-l-2 border-[var(--border)] pl-3 text-[12px] italic leading-relaxed text-[var(--text-subtle)]">
          &ldquo;I&rsquo;m leading a manufacturing vision inspection project.&rdquo;
        </div>
        <div className="mt-3 flex gap-2">
          <Chip icon={<RotateCcw className="size-3" />}>Correct</Chip>
          <Chip icon={<Trash2 className="size-3" />}>Forget</Chip>
        </div>
      </Panel>
    ),
  },
  {
    title: "It tells you how sure it is",
    body: "Not every question has an answer in the material, and the interface says so plainly instead of inventing one. There are three states, and they read in plain language, never as a similarity score.",
    figure: (
      <div className="space-y-2">
        <Panel className="flex items-start gap-3">
          <Check className="mt-0.5 size-4 shrink-0 text-[var(--brand)]" />
          <div>
            <div className="text-[14px] font-medium text-[var(--text)]">
              Grounded in his public work
            </div>
            <div className="text-[12px] text-[var(--text-muted)]">
              Direct support from retrieved sources, shown with citations.
            </div>
          </div>
        </Panel>
        <Panel className="flex items-start gap-3">
          <div className="mt-1 size-2 shrink-0 rounded-full bg-[var(--text-muted)]" />
          <div>
            <div className="text-[14px] font-medium text-[var(--text)]">
              Related material
            </div>
            <div className="text-[12px] text-[var(--text-muted)]">
              The exact question is not covered, so the answer extends from
              nearby work and says so.
            </div>
          </div>
        </Panel>
        <Panel className="flex items-start gap-3">
          <div className="mt-1 size-2 shrink-0 rounded-full bg-[var(--text-subtle)]" />
          <div>
            <div className="text-[14px] font-medium text-[var(--text)]">
              General analysis
            </div>
            <div className="text-[12px] text-[var(--text-muted)]">
              Not enough in the material for an Andrew-specific answer. It offers
              a general view only after saying so.
            </div>
          </div>
        </Panel>
      </div>
    ),
  },
  {
    title: "It can speak, and it is honest about the voice",
    body: "Answers can be read aloud in a synthetic voice modelled on his, streamed sentence by sentence so it starts talking before the reply is finished. When the cloned voice is unavailable it falls back to a browser voice and tells you. The audio carries a provenance watermark, and a synthetic-voice label stays visible.",
    figure: (
      <Panel>
        <div className="flex flex-wrap items-center gap-2">
          <Chip icon={<Mic className="size-3 text-[var(--brand)]" />}>
            Listening
          </Chip>
          <Chip>Thinking</Chip>
          <Chip tone="brand">Speaking</Chip>
        </div>
        <p className="mt-3 text-[12px] text-[var(--text-subtle)]">
          Synthetic voice. An unofficial recreation, never presented as a real
          recording.
        </p>
      </Panel>
    ),
  },
]
