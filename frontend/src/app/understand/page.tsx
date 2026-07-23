import Link from "next/link"

import { SiteHeader } from "@/components/site-header"

export const metadata = {
  title: "How it works — Andrew Ng Digital Twin",
  description:
    "How the tutor retrieves from Andrew Ng's teaching, remembers what you understand, and sequences what to learn next.",
}

/**
 * The "how it works" page.
 *
 * Written to explain the three real mechanisms without pretending they are
 * magic: grounded retrieval, a knowledge graph that tracks understanding over
 * time, and prerequisite-aware sequencing. Each section says plainly what the
 * system does and, just as importantly, what it does not.
 */

const STEPS = [
  {
    n: "01",
    title: "It retrieves before it answers",
    body: "Every question runs against a corpus of Andrew Ng's own lectures, courses and Batch letters. Retrieval blends two signals: semantic similarity, which catches meaning, and full-text search, which catches exact terms. The two are fused so a casually worded question still lands on the right passage, and the answer is written from what came back, not from the model's memory.",
    aside: "Fusing meaning and keywords is the difference between finding the lecture that answers you and finding one that merely sounds similar.",
  },
  {
    n: "02",
    title: "It remembers what you understand",
    body: "As you talk, a knowledge graph records the concepts you have grasped and how they connect. It is time aware: if you understand something one week and revise that belief the next, the graph invalidates the old claim rather than leaving both to contradict each other. What you know is a living record, not a transcript.",
    aside: "Most tutors start every session from zero. This one carries your understanding forward and reasons over it.",
  },
  {
    n: "03",
    title: "It teaches in the right order",
    body: "Concepts carry prerequisites, held as a graph. When you are stuck, the tutor looks for the idea underneath the struggle instead of answering only the surface question. If several difficulties trace back to one missing foundation, it teaches that foundation first, so you fix the cause rather than patch each symptom.",
    aside: "Answering the question you asked is easy. Finding the gap you could not see is the point.",
  },
]

export default function UnderstandPage() {
  return (
    <div className="min-h-screen bg-[#050505] text-white">
      <SiteHeader />

      <main className="mx-auto w-[min(900px,calc(100%-2rem))] pt-36 pb-24">
        <p className="text-sm font-medium uppercase tracking-[0.2em] text-white/40">
          How it works
        </p>
        <h1 className="mt-4 max-w-[20ch] text-balance text-4xl font-semibold leading-[1.05] tracking-[-0.02em] sm:text-5xl">
          A tutor that reads the source and remembers you
        </h1>
        <p className="mt-6 max-w-[58ch] text-lg leading-relaxed text-white/55">
          Three ideas hold the whole thing together. None of them is a chatbot
          wrapper. Here is what each one actually does.
        </p>

        <div className="mt-20 space-y-20">
          {STEPS.map((step) => (
            <section
              key={step.n}
              className="grid gap-6 border-t border-white/[0.08] pt-10 sm:grid-cols-[auto_1fr] sm:gap-10"
            >
              <div className="font-heading text-5xl font-semibold text-white/15">
                {step.n}
              </div>
              <div>
                <h2 className="text-2xl font-semibold tracking-[-0.01em]">
                  {step.title}
                </h2>
                <p className="mt-4 max-w-[60ch] leading-relaxed text-white/60">
                  {step.body}
                </p>
                <p className="mt-5 max-w-[52ch] border-l-2 border-white/15 pl-4 text-sm italic leading-relaxed text-white/40">
                  {step.aside}
                </p>
              </div>
            </section>
          ))}
        </div>

        {/* Voice, kept honest about what it is. */}
        <section className="mt-20 rounded-2xl border border-white/[0.08] bg-white/[0.03] p-8">
          <h2 className="text-xl font-semibold">And it can speak</h2>
          <p className="mt-3 max-w-[60ch] leading-relaxed text-white/55">
            Answers can be read aloud in a voice modelled on Andrew Ng&apos;s,
            streamed sentence by sentence so it starts talking before the whole
            reply is written. The audio carries an inaudible marker identifying
            it as synthetic, because cloning a real, identifiable person&apos;s
            voice without that would be indefensible.
          </p>
        </section>

        <div className="mt-16 flex flex-col items-center gap-4 border-t border-white/[0.08] pt-16 text-center">
          <h2 className="text-2xl font-semibold tracking-[-0.01em]">
            Ready to try it?
          </h2>
          <Link
            href="/login"
            className="rounded-full bg-white px-6 py-3 text-sm font-medium text-black transition-opacity hover:opacity-90"
          >
            Start learning
          </Link>
        </div>
      </main>

      <footer className="border-t border-white/[0.06]">
        <div className="mx-auto w-[min(900px,calc(100%-2rem))] py-8 text-sm text-white/35">
          An educational project. Not affiliated with or endorsed by Andrew Ng,
          DeepLearning.AI or Stanford.
        </div>
      </footer>
    </div>
  )
}
