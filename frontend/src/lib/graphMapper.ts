// lib/graphMapper.ts
// ─────────────────────────────────────────────────────────────────────────────
// Converts raw SQL triplet rows from Supabase into React Flow Node + Edge
// schemas, and applies a force-directed layout using d3-force.
//
// Pipeline:
//   TripletRow[] + EdgeRow[]
//     → deduplicate nodes
//     → build React Flow nodes with visual metadata
//     → build React Flow edges with predicate styling
//     → apply d3-force layout (returns positioned nodes)
//
// Dependencies:
//   npm install @xyflow/react d3-force d3-hierarchy
// ─────────────────────────────────────────────────────────────────────────────

import * as d3 from "d3-force";

import type {
  TripletRow,
  EdgeRow,
  KnowledgeNode,
  KnowledgeEdge,
  KnowledgeGraph,
  KnowledgeNodeData,
} from "../types/graph";
import { NODE_TYPE_COLORS, PREDICATE_COLORS } from "../types/graph";

// ── Layout constants ──────────────────────────────────────────────────────────
const LAYOUT_WIDTH  = 800;
const LAYOUT_HEIGHT = 600;
const NODE_RADIUS   = 60;   // repulsion radius for force simulation

// ─────────────────────────────────────────────────────────────────────────────
// MAIN MAPPER FUNCTION
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Converts Supabase graph data into a positioned React Flow graph.
 *
 * @param triplets  - Node rows from vector_anchored_subgraph()
 * @param edges     - Edge rows from relation_edges join
 * @param width     - Canvas width for layout centering (default 800)
 * @param height    - Canvas height for layout centering (default 600)
 * @returns         - Positioned { nodes, edges } ready for <ReactFlow>
 */
export function mapTripletRowsToReactFlow(
  triplets: TripletRow[],
  edges:     EdgeRow[],
  width:     number = LAYOUT_WIDTH,
  height:    number = LAYOUT_HEIGHT,
): KnowledgeGraph {
  // ── Step 1: Deduplicate nodes by id ───────────────────────────────────────
  const nodeMap = new Map<string, TripletRow>();
  for (const row of triplets) {
    const existing = nodeMap.get(row.node_id);
    // Keep the entry with the highest combined_score for deduplication
    if (!existing || row.combined_score > existing.combined_score) {
      nodeMap.set(row.node_id, row);
    }
  }

  // ── Step 2: Build React Flow node objects ──────────────────────────────────
  const rfNodes: KnowledgeNode[] = Array.from(nodeMap.values()).map((row) =>
    buildNode(row)
  );

  // ── Step 3: Build React Flow edge objects ─────────────────────────────────
  // Filter to only include edges where both endpoints exist in our node set
  const nodeIds = new Set(nodeMap.keys());
  const rfEdges: KnowledgeEdge[] = edges
    .filter((e) => nodeIds.has(e.subject_id) && nodeIds.has(e.object_id))
    .map((e) => buildEdge(e));

  // ── Step 4: Apply d3-force layout ─────────────────────────────────────────
  const positionedNodes = applyForceLayout(rfNodes, rfEdges, width, height);

  return { nodes: positionedNodes, edges: rfEdges };
}

// ─────────────────────────────────────────────────────────────────────────────
// NODE BUILDER
// ─────────────────────────────────────────────────────────────────────────────

function buildNode(row: TripletRow): KnowledgeNode {
  const baseColor = NODE_TYPE_COLORS[row.node_type] ?? "#64748b";

  return {
    id:       row.node_id,
    type:     "knowledgeNode",   // maps to our custom React Flow node component
    position: { x: 0, y: 0 },   // placeholder; overwritten by force layout
    data: {
      label:         row.canonical_name,
      nodeType:      row.node_type,
      hopDistance:   row.hop_distance,
      combinedScore: row.combined_score,
      metadata:      row.metadata ?? {},
      predicates:    row.predicates_path ?? [],
    } satisfies KnowledgeNodeData,

    // React Flow node style — overridden by custom node component, but
    // provides sensible defaults for the built-in node renderer fallback.
    style: {
      background:   baseColor,
      color:        "#ffffff",
      borderRadius: "50%",
      border:       `3px solid ${lighten(baseColor, 0.3)}`,
      width:        nodeSize(row.combined_score),
      height:       nodeSize(row.combined_score),
      fontSize:     "11px",
      fontWeight:   "600",
      display:      "flex",
      alignItems:   "center",
      justifyContent: "center",
      textAlign:    "center",
      padding:      "4px",
      boxShadow:    row.hop_distance === 0
        ? `0 0 20px ${baseColor}88`   // anchor nodes glow
        : "0 2px 6px rgba(0,0,0,0.2)",
    },
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// EDGE BUILDER
// ─────────────────────────────────────────────────────────────────────────────

function buildEdge(row: EdgeRow): KnowledgeEdge {
  const edgeColor = PREDICATE_COLORS[row.predicate] ?? "#94a3b8";
  const strokeWidth = Math.max(1, Math.min(row.weight * 2.5, 6));

  return {
    id:     row.id,
    source: row.subject_id,
    target: row.object_id,
    type:   "smoothstep",
    animated: row.predicate === "struggles_with",  // animate "struggles" edges
    label:  formatPredicate(row.predicate),
    labelStyle: {
      fontSize:   "9px",
      fontWeight: "500",
      fill:       edgeColor,
    },
    labelBgStyle: {
      fill:    "#0f172a",
      fillOpacity: 0.7,
    },
    style: {
      stroke:      edgeColor,
      strokeWidth,
      opacity:     0.8,
    },
    markerEnd: {
      type:  "arrowclosed",
      color: edgeColor,
      width: 12,
      height: 12,
    },
    data: {
      predicate: row.predicate,
      weight:    row.weight,
      evidence:  row.evidence,
    },
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// D3-FORCE LAYOUT
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Runs a synchronous d3-force simulation and writes (x, y) positions
 * back onto the React Flow node objects.
 *
 * Force configuration:
 *   - forceLink:   pulls connected nodes together (strength ∝ edge weight)
 *   - forceManyBody: repels all nodes (barnes-hut approximation)
 *   - forceCenter:  centers the graph on (width/2, height/2)
 *   - forceCollide: prevents node overlap based on node size
 *   - forceRadial:  concentric rings by hop distance (0-hop = center)
 */
function applyForceLayout(
  nodes:  KnowledgeNode[],
  edges:  KnowledgeEdge[],
  width:  number,
  height: number,
): KnowledgeNode[] {
  if (nodes.length === 0) return nodes;

  // d3 mutates objects in-place; clone positions to avoid React Flow conflicts
  type SimNode = d3.SimulationNodeDatum & {
    id:          string;
    hopDistance: number;
    size:        number;
  };

  const simNodes: SimNode[] = nodes.map((n) => ({
    id:          n.id,
    hopDistance: n.data.hopDistance,
    size:        parseFloat(String(n.style?.width ?? 50)),
    x:           width / 2 + (Math.random() - 0.5) * 100,
    y:           height / 2 + (Math.random() - 0.5) * 100,
  }));

  const nodeById = new Map(simNodes.map((n) => [n.id, n]));

  type SimLink = d3.SimulationLinkDatum<SimNode> & { weight: number };
  const simLinks: SimLink[] = edges
    .map((e) => ({
      source: nodeById.get(e.source)!,
      target: nodeById.get(e.target)!,
      weight: e.data?.weight ?? 1.0,
    }))
    .filter((l) => l.source && l.target);

  const simulation = d3
    .forceSimulation<SimNode>(simNodes)
    // Pull connected nodes together; strength ∝ edge weight
    .force(
      "link",
      d3
        .forceLink<SimNode, SimLink>(simLinks)
        .id((d) => d.id)
        .distance(140)
        .strength((l) => 0.3 + l.weight * 0.4),
    )
    // Repulsion between all nodes (Barnes-Hut)
    .force("charge", d3.forceManyBody<SimNode>().strength(-500).theta(0.9))
    // Center gravity
    .force("center", d3.forceCenter(width / 2, height / 2).strength(0.08))
    // Prevent overlap based on node size
    .force(
      "collide",
      d3.forceCollide<SimNode>().radius((d) => d.size / 2 + 12).strength(0.9),
    )
    // Concentric radial force: anchor nodes (hop=0) go to center
    .force(
      "radial",
      d3
        .forceRadial<SimNode>(
          (d) => d.hopDistance * (Math.min(width, height) * 0.25),
          width / 2,
          height / 2,
        )
        .strength(0.4),
    )
    // Run synchronously for SSR compatibility and determinism
    .stop();

  // Warm-up iterations (200 = good balance of quality vs speed)
  for (let i = 0; i < 200; i++) simulation.tick();

  // Write positions back into React Flow nodes
  return nodes.map((n) => {
    const simNode = nodeById.get(n.id);
    return simNode
      ? { ...n, position: { x: simNode.x ?? 0, y: simNode.y ?? 0 } }
      : n;
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// UTILITY HELPERS
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Map combined_score (0-1) to a node diameter in pixels (40–80px).
 */
function nodeSize(score: number): number {
  return Math.round(40 + score * 40);
}

/**
 * Convert predicate snake_case to readable label.
 * e.g. "struggles_with" → "struggles with"
 */
function formatPredicate(predicate: string): string {
  return predicate.replace(/_/g, " ");
}

/**
 * Lighten a hex color by a factor (0-1) — used for node border glow.
 * Quick implementation without a full color library.
 */
function lighten(hex: string, factor: number): string {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  const lerp = (v: number) => Math.min(255, Math.round(v + (255 - v) * factor));
  return `#${lerp(r).toString(16).padStart(2, "0")}${
    lerp(g).toString(16).padStart(2, "0")
  }${lerp(b).toString(16).padStart(2, "0")}`;
}

// ─────────────────────────────────────────────────────────────────────────────
// INCREMENTAL UPDATE HELPER
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Merges a new graph snapshot into an existing React Flow graph, preserving
 * the positions of nodes that haven't moved. Used for live updates without
 * a full re-layout jolt.
 *
 * @param existing   - Current graph in React Flow state
 * @param incoming   - New graph from the API
 */
export function mergeGraphUpdate(
  existing: KnowledgeGraph,
  incoming: KnowledgeGraph,
): KnowledgeGraph {
  const existingPositions = new Map(
    existing.nodes.map((n) => [n.id, n.position])
  );

  const mergedNodes = incoming.nodes.map((n) => ({
    ...n,
    // Preserve existing position; only use new layout position for new nodes
    position: existingPositions.get(n.id) ?? n.position,
  }));

  return { nodes: mergedNodes, edges: incoming.edges };
}
