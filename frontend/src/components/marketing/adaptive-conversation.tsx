"use client"

import * as React from "react"

import { SlidingTabs } from "@/components/ui/sliding-tabs"

/**
 * Landing demonstration: ONE persona adapting depth and framing to different
 * people. The examples are curated marketing content — deliberately static and
 * clearly separate from any authenticated conversation — so nothing here
 * fabricates real user data or a live model call. Switching a tab changes which
 * curated exchange is shown; that interactivity is real.
 */
type Audience = "researcher" | "product" | "founder" | "learner"

const EXCHANGES: Record<
  Audience,
  { label: string; ask: string; reply: string }
> = {
  researcher: {
    label: "Researcher",
    ask: "Where does the bias–variance decomposition actually break down in practice?",
    reply:
      "So the decomposition assumes squared loss and a fixed target distribution. The moment you're doing representation learning, the \"variance\" term starts absorbing optimisation noise and data-order effects, and it stops cleanly predicting test error — which is why I'd look at the learning curves before trusting the tidy story.",
  },
  product: {
    label: "Product leader",
    ask: "How do I decide which part of our workflow to automate with AI first?",
    reply:
      "I'd start with the one-second rule: anything a person on your team does in about a second of thought is a candidate now. Then ask whether you can specify the input and the desired output clearly. If you can, that's your first automation — and the metric to watch is throughput on that subtask, not model accuracy in isolation.",
  },
  founder: {
    label: "Founder",
    ask: "Is my AI idea a real business or just a feature?",
    reply:
      "The honest test I use: can you name the specific input and output, and is there proprietary data or a workflow only you can reach? If the mapping is generic and the data is public, it's a feature someone larger will ship. If you own the data loop, that's where a defensible company usually starts.",
  },
  learner: {
    label: "Learner",
    ask: "I keep getting lost in gradient descent. Can you explain it simply?",
    reply:
      "Picture walking downhill in thick fog. You can't see the whole valley — only the slope right under your feet. So you feel which way is down, take a small step, and check again. That step size is your learning rate: too big and you overshoot the bottom, too small and you're there all day.",
  },
}

const ORDER: Audience[] = ["researcher", "product", "founder", "learner"]

export function AdaptiveConversation() {
  const [audience, setAudience] = React.useState<Audience>("researcher")
  const ex = EXCHANGES[audience]

  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-5 sm:p-7">
      <SlidingTabs
        aria-label="Choose who is asking"
        options={ORDER.map((a) => ({ value: a, label: EXCHANGES[a].label }))}
        value={audience}
        onValueChange={(v) => setAudience(v as Audience)}
      />

      <div className="mt-6 space-y-4">
        <div className="flex justify-end">
          <p className="max-w-[80%] rounded-2xl rounded-tr-sm bg-[var(--surface-alt)] px-4 py-2.5 text-[14px] text-[var(--text)]">
            {ex.ask}
          </p>
        </div>
        <div className="flex gap-3">
          <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-full bg-[var(--brand)] text-[11px] font-semibold text-[var(--brand-text)]">
            AN
          </span>
          <p className="max-w-[85%] text-[15px] leading-relaxed text-[var(--text-muted)]">
            {ex.reply}
          </p>
        </div>
      </div>

      <p className="mt-6 border-t border-[var(--border)] pt-4 text-[12px] text-[var(--text-subtle)]">
        Same twin, same source material — only the depth and framing change.
        Illustrative examples, not a live conversation.
      </p>
    </div>
  )
}
