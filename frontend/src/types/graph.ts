// types/graph.ts
// ─────────────────────────────────────────────────────────────────────────────
// Type definitions for the knowledge graph visualization layer.
// These types flow from: Supabase SQL → Python API → TypeScript → React Flow
// ─────────────────────────────────────────────────────────────────────────────

import type { Node, Edge } from "@xyflow/react";

// ── Raw API response types (from FastAPI) ────────────────────────────────────

/**
 * Node categories, kept in lockstep with backend migration 015 and
 * VALID_NODE_TYPES in triplet_extractor.py. Educational types remain a subset;
 * the general types carry professional and research context. "Student" is the
 * internal self-node type — the UI maps it to a neutral "Person"/"You" label.
 */
export type NodeType =
  | "Student"
  | "Concept"
  | "Project"
  | "Tool"
  | "Paper"
  | "Person"
  | "Organization"
  | "Industry"
  | "Goal"
  | "Preference"
  | "ResearchArea";

/** A triplet row returned by the vector_anchored_subgraph SQL function. */
export interface TripletRow {
  node_id:         string;
  canonical_name:  string;
  node_type:       NodeType;
  metadata:        Record<string, unknown>;
  hop_distance:    number;
  path_weight:     number;
  vector_score:    number;
  combined_score:  number;
  predicates_path: string[];
}

/** An edge row (for rendering relation_edges as React Flow edges). */
export interface EdgeRow {
  id:            string;
  subject_id:    string;
  predicate:     string;
  object_id:     string;
  weight:        number;
  evidence:      string;
}

/** Full graph payload returned by GET /api/v1/chat/graph/{session_id} */
export interface GraphPayload {
  nodes: TripletRow[];
  edges: EdgeRow[];
}

// ── React Flow custom node data ───────────────────────────────────────────────

/** Custom data attached to each React Flow node. */
export interface KnowledgeNodeData extends Record<string, unknown> {
  label:          string;           // canonical_name
  nodeType:       TripletRow["node_type"];
  hopDistance:    number;
  combinedScore:  number;
  metadata:       Record<string, unknown>;
  predicates:     string[];         // incoming predicates (for tooltip)
  isDimmed?:      boolean;
  isSelected?:    boolean;
  isNeighbor?:    boolean;
}

/** Custom data attached to each React Flow edge. */
export interface KnowledgeEdgeData extends Record<string, unknown> {
  predicate:  string;
  weight:     number;
  evidence:   string;
}

// ── Typed React Flow generics ─────────────────────────────────────────────────

export type KnowledgeNode = Node<KnowledgeNodeData>;
export type KnowledgeEdge = Edge<KnowledgeEdgeData>;

export interface KnowledgeGraph {
  nodes: KnowledgeNode[];
  edges: KnowledgeEdge[];
}

// ── Visual style config ───────────────────────────────────────────────────────

/**
 * The Context Graph is mostly monochrome: every node type resolves to the same
 * graphite token, and categories are told apart by their label and icon rather
 * than colour. Orange is reserved for the selected node and active paths, and
 * is applied in the view rather than baked in here. Token-driven so both themes
 * work. Kept exhaustive over NodeType.
 */
export const NODE_TYPE_COLORS: Record<NodeType, string> = {
  Student:      "var(--graph-node)",
  Concept:      "var(--graph-node)",
  Project:      "var(--graph-node)",
  Tool:         "var(--graph-node)",
  Paper:        "var(--graph-node)",
  Person:       "var(--graph-node)",
  Organization: "var(--graph-node)",
  Industry:     "var(--graph-node)",
  Goal:         "var(--graph-node)",
  Preference:   "var(--graph-node)",
  ResearchArea: "var(--graph-node)",
};

/**
 * Edges are monochrome as well. The predicate is carried by its label, not by a
 * rainbow of colours, so every edge uses the same graphite edge token.
 */
export const PREDICATE_COLORS: Record<string, string> = {
  struggles_with:   "var(--graph-edge)",
  mastered:         "var(--graph-edge)",
  curious_about:    "var(--graph-edge)",
  works_in:         "var(--graph-edge)",
  studied:          "var(--graph-edge)",
  applied:          "var(--graph-edge)",
  confused_about:   "var(--graph-edge)",
  wants_to_learn:   "var(--graph-edge)",
  has_prerequisite: "var(--graph-edge)",
  related_to:       "var(--graph-edge)",
  used_in:          "var(--graph-edge)",
  named:            "var(--graph-edge)",
  is:               "var(--graph-edge)",
};
