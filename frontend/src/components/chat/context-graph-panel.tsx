import { Network, RefreshCw, X } from "lucide-react"

import { SlidingTabs } from "@/components/ui/sliding-tabs"
import { KnowledgeGraphView } from "@/components/KnowledgeGraphView"
import type { TripletRow, EdgeRow } from "@/types/graph"

/**
 * The right context region: the Context Graph and its scope control.
 *
 * Renamed from "What I know about you" / "Active Chat" / "Global Map" to the
 * spec's plainer language, and narrowed to about 340px so it collapses to a
 * drawer earlier and stops crowding the transcript. Rendering of the graph
 * itself stays in KnowledgeGraphView (rebuilt fully in the Context Graph phase).
 */
export function ContextGraphPanel({
  mobileVisible,
  onCloseMobile,
  graphView,
  onGraphViewChange,
  isSyncingGraph,
  onSync,
  triplets,
  edges,
  onExploreNode,
  onForgetEdge,
}: {
  mobileVisible: boolean
  onCloseMobile: () => void
  graphView: "session" | "global"
  onGraphViewChange: (v: "session" | "global") => void
  isSyncingGraph: boolean
  onSync: (v: "session" | "global") => void
  triplets: TripletRow[]
  edges: EdgeRow[]
  onExploreNode: (concept: string) => void
  onForgetEdge: (edgeId: string) => void
}) {
  return (
    <aside
      aria-label="Context graph"
      className={`${mobileVisible ? "flex" : "hidden"} lg:flex
        absolute lg:relative inset-2 lg:inset-auto z-30 lg:z-auto
        w-auto lg:w-[340px] xl:w-[360px] lg:flex-shrink-0
        bg-[var(--surface)] border border-[var(--border)] rounded-2xl shadow-lg lg:shadow-sm
        flex-col overflow-hidden`}
    >
      <div className="p-4 border-b border-[var(--border)] flex items-center justify-between bg-[var(--surface)]">
        <div className="flex items-center gap-2 min-w-0">
          <button
            onClick={onCloseMobile}
            className="lg:hidden p-1.5 -ml-1 rounded-lg border border-[var(--border)] text-[var(--text-muted)] hover:bg-[var(--bg)]"
            aria-label="Close context graph"
          >
            <X className="w-4 h-4" />
          </button>
          <Network className="text-[var(--brand)] w-4 h-4 flex-shrink-0" />
          <h2 className="text-[14px] font-medium text-[var(--text)] truncate">
            Context Graph
          </h2>
        </div>

        <div className="flex items-center gap-2">
          <SlidingTabs
            size="sm"
            aria-label="Context graph scope"
            value={graphView}
            onValueChange={onGraphViewChange}
            options={[
              { value: "session", label: "This chat" },
              { value: "global", label: "All chats" },
            ]}
          />
          <button
            onClick={() => onSync(graphView)}
            disabled={isSyncingGraph}
            className="p-1.5 rounded-lg border border-[var(--border)] hover:bg-[var(--bg)] text-[var(--text-muted)] transition"
            title="Refresh the context graph"
            aria-label="Refresh the context graph"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isSyncingGraph ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      <div className="flex-1 relative h-full w-full">
        <KnowledgeGraphView
          triplets={triplets}
          edges={edges}
          isLoading={isSyncingGraph}
          width="100%"
          height="100%"
          onExploreNode={onExploreNode}
          onForgetEdge={onForgetEdge}
        />
      </div>
    </aside>
  )
}
