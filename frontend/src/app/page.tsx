import Link from "next/link"

import { DotPortrait } from "@/components/dot-portrait"
import { SiteHeader } from "@/components/site-header"

/**
 * Portrait source. Drop a licensed photograph here and the hero picks it up.
 * Kept as one constant so swapping it is a single edit rather than a search.
 */
const PORTRAIT_SRC = "/andrew-ng.png"

export const metadata = {
  title: "Andrew Ng Digital Twin",
  description:
    "An ML tutor that answers from Andrew Ng's own teaching, remembers what you understand, and builds a path from there.",
}

/**
 * Landing page.
 *
 * The reference design put the paragraph and buttons directly on top of the
 * shader, which looks striking in a screenshot and is genuinely hard to read
 * once the metal moves underneath the text. The visual keeps its full size
 * here, but the reading column sits clear of it.
 */
export default function LandingPage() {
  return (
    <div className="min-h-screen bg-[#050505] text-white">
      <SiteHeader />

      {/* ─── Hero ─────────────────────────────────────────────────────── */}
      <section className="relative isolate overflow-hidden">
        {/* Split layout rather than a centred stack. Portrait and copy each
            get their own column, so neither has to be dimmed to rescue the
            other. */}
          <div className="relative mx-auto grid min-h-[100svh] w-[min(1240px,calc(100%-2rem))] grid-cols-1 items-center gap-8 pt-28 pb-16 lg:grid-cols-[1.05fr_1fr] lg:gap-4 lg:pt-24">
            {/* Copy */}
            <div className="relative z-10 text-center lg:text-left">
              <span className="inline-block rounded-full border border-white/15 bg-white/5 px-3.5 py-1.5 text-[13px] text-white/70 backdrop-blur-sm">
                Retrieval, memory and voice in one tutor
              </span>

              <h1 className="mt-7 text-balance text-5xl font-semibold leading-[0.95] tracking-[-0.03em] sm:text-6xl lg:text-[4.25rem]">
                Learn ML from the
                <span className="block text-white/55">
                  source, not a summary
                </span>
              </h1>

              <p className="mx-auto mt-7 max-w-[52ch] text-pretty text-base leading-relaxed text-white/60 sm:text-lg lg:mx-0">
                Every answer is grounded in Andrew Ng&apos;s own lectures,
                courses and letters. It tracks what you already understand,
                notices what you are missing, and teaches the gap rather than
                the question.
              </p>

              <div className="mt-10 flex flex-col items-center gap-3 sm:flex-row sm:justify-center lg:justify-start">
                <Link
                  href="/login"
                  className="w-full rounded-full bg-white px-6 py-3 text-center text-sm font-medium text-black transition-opacity hover:opacity-90 sm:w-auto"
                >
                  Start learning
                </Link>
                <Link
                  href="/understand"
                  className="w-full rounded-full border border-white/15 bg-white/5 px-6 py-3 text-center text-sm font-medium text-white/80 backdrop-blur-sm transition-colors hover:bg-white/10 hover:text-white sm:w-auto"
                >
                  See how it works
                </Link>
              </div>
            </div>

            {/* On small screens the portrait moves behind the copy at low
                opacity, because there is no room for a second column. The
                parent must be a block, not a flex box: the canvas is
                absolutely positioned, so a flex parent collapses it to zero
                width and the portrait silently disappears. */}
            <div
              aria-hidden
              className="pointer-events-none absolute inset-0 z-0 opacity-40 lg:relative lg:inset-auto lg:z-10 lg:opacity-100"
            >
              {/* Swap PORTRAIT_SRC for a photograph you hold the rights to.
                  The placeholder is a generated silhouette, there only so the
                  renderer has tonal structure to sample while the real image
                  is missing. The image must be same-origin: a cross-origin one
                  taints the canvas and cannot be read back pixel by pixel. */}
              <DotPortrait
                src={PORTRAIT_SRC}
                className="h-[360px] w-full lg:h-[460px] xl:h-[560px]"
                gap={5}
                maxRadius={2.6}
                cutoff={0.82}
                invert
                animate={false}
              />
            </div>
          </div>

          {/* Fades the portrait into the section below rather than letting it
              stop at a hard edge. */}
          <div className="pointer-events-none absolute inset-x-0 bottom-0 z-[5] h-40 bg-gradient-to-b from-transparent to-[#050505]" />
      </section>

      {/* ─── What it is ───────────────────────────────────────────────── */}
      <section className="relative border-t border-white/[0.06]">
        <div className="mx-auto w-[min(1100px,calc(100%-2rem))] py-24 sm:py-32">
          <div className="max-w-[46ch]">
            <h2 className="text-3xl font-semibold tracking-[-0.02em] sm:text-4xl">
              Most AI tutors answer the question you asked
            </h2>
            <p className="mt-5 text-base leading-relaxed text-white/55">
              That sounds like a good thing. It is not, when the question comes
              from a gap you cannot see yet. Asking about backprop when the
              actual problem is the chain rule gets you a fluent answer that
              does not help.
            </p>
          </div>

          <div className="mt-16 grid gap-px overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.06] sm:grid-cols-3">
            {[
              {
                title: "Grounded in real teaching",
                body: "Answers come from 529 sources: CS229, CS230, The Batch, and course transcripts. Retrieval blends meaning and keywords, so a question phrased casually still finds the right lecture.",
              },
              {
                title: "Remembers what you know",
                body: "A knowledge graph records what you have understood and what you contradicted later. It is time aware, so revising a belief updates the graph instead of leaving both versions sitting there.",
              },
              {
                title: "Teaches in the right order",
                body: "Topics carry prerequisites. When several struggles share one missing idea, it teaches that idea first rather than patching each symptom on its own.",
              },
            ].map((card) => (
              <div key={card.title} className="bg-[#080808] p-7 sm:p-8">
                <h3 className="text-[15px] font-medium text-white">
                  {card.title}
                </h3>
                <p className="mt-3 text-sm leading-relaxed text-white/50">
                  {card.body}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ─── Closing ──────────────────────────────────────────────────── */}
      <section className="border-t border-white/[0.06]">
        <div className="mx-auto w-[min(1100px,calc(100%-2rem))] py-24 text-center sm:py-32">
          <h2 className="mx-auto max-w-[20ch] text-balance text-3xl font-semibold tracking-[-0.02em] sm:text-4xl">
            Bring your own key. Nothing to pay.
          </h2>
          <p className="mx-auto mt-5 max-w-[52ch] text-base leading-relaxed text-white/55">
            Your Gemini API key stays on your side and is never stored on the
            server. Your conversations and your knowledge graph belong to your
            account alone.
          </p>
          <Link
            href="/login"
            className="mt-10 inline-block rounded-full bg-white px-6 py-3 text-sm font-medium text-black transition-opacity hover:opacity-90"
          >
            Start learning
          </Link>
        </div>
      </section>

      <footer className="border-t border-white/[0.06]">
        <div className="mx-auto flex w-[min(1100px,calc(100%-2rem))] flex-col gap-3 py-8 text-sm text-white/35 sm:flex-row sm:items-center sm:justify-between">
          <p>
            An educational project. Not affiliated with or endorsed by Andrew
            Ng, DeepLearning.AI or Stanford.
          </p>
          <Link href="/understand" className="hover:text-white/60">
            How it works
          </Link>
        </div>
      </footer>
    </div>
  )
}
