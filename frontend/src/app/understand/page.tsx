import Link from "next/link"
import { ArrowRight } from "lucide-react"

import { SiteHeader } from "@/components/site-header"
import { SiteFooter } from "@/components/site-footer"
import { PipelineSteps } from "@/components/marketing/pipeline-steps"

export const metadata = {
  title: "How it works - Andrew Ng Digital Twin",
  description:
    "How the twin reads from Andrew Ng's public work, retrieves before it answers, remembers your context, tells you how sure it is, and can speak.",
}

/**
 * The "how it works" page.
 *
 * A visual, honest walkthrough of the real mechanisms: grounded retrieval, a
 * stable persona with audience-aware depth, a memory graph you control, three
 * confidence states in plain language, and a synthetic voice with clear
 * provenance. Every claim matches what the system actually does, and the page
 * reads fully with motion disabled.
 */
export default function UnderstandPage() {
  return (
    <div className="theme-dark min-h-screen bg-[var(--bg)] text-[var(--text)]">
      <SiteHeader />

      <main className="mx-auto w-[min(900px,calc(100%-2rem))] pt-36 pb-24">
        <p className="text-sm font-medium uppercase tracking-[0.2em] text-[var(--text-subtle)]">
          How it works
        </p>
        <h1 className="mt-4 max-w-[22ch] text-balance text-[2.5rem] font-semibold leading-[1.08] tracking-[-0.02em] sm:text-5xl">
          A twin that reads the source and remembers you
        </h1>
        <p className="mt-6 max-w-[60ch] text-[17px] leading-relaxed text-[var(--text-muted)]">
          Six things hold the whole thing together. None of them is a chatbot in
          a costume. Here is what each one actually does, and what it does not.
        </p>

        <div className="mt-16">
          <PipelineSteps />
        </div>

        <div className="mt-20 flex flex-col items-start gap-4 border-t border-[var(--border)] pt-14">
          <h2 className="text-2xl font-semibold tracking-[-0.01em]">
            Ready to try it?
          </h2>
          <p className="max-w-[52ch] leading-relaxed text-[var(--text-muted)]">
            Bring your own Gemini key. It is sent through the backend to generate
            replies and is never stored.
          </p>
          <Link
            href="/login"
            className="inline-flex items-center gap-2 rounded-full bg-[var(--brand)] px-6 py-3 text-sm font-medium text-[var(--brand-text)] transition-opacity hover:opacity-90"
          >
            Enter the Twin
            <ArrowRight className="size-4" />
          </Link>
        </div>
      </main>

      <SiteFooter />
    </div>
  )
}
