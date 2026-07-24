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
 * A restrained semantic palette. Closely related categories intentionally
 * share a colour so the graph stays readable instead of becoming a rainbow.
 * The tokens provide separate light/dark values and this map remains exhaustive
 * over NodeType.
 */
export const NODE_TYPE_COLORS: Record<NodeType, string> = {
  Student:      "var(--graph-person)",
  Person:       "var(--graph-person)",
  Concept:      "var(--graph-concept)",
  ResearchArea: "var(--graph-concept)",
  Project:      "var(--graph-project)",
  Tool:         "var(--graph-project)",
  Organization: "var(--graph-organization)",
  Industry:     "var(--graph-organization)",
  Goal:         "var(--graph-intention)",
  Preference:   "var(--graph-intention)",
  Paper:        "var(--graph-paper)",
};

/**
 * Relationship colours describe the kind of connection: learning state,
 * curiosity, professional context, identity, or neutral structure.
 */
export const PREDICATE_COLORS: Record<string, string> = {
  struggles_with:   "var(--graph-edge-challenge)",
  confused_about:   "var(--graph-edge-challenge)",
  concerned_about:  "var(--graph-edge-challenge)",
  mastered:         "var(--graph-edge-progress)",
  curious_about:    "var(--graph-edge-curiosity)",
  wants_to_learn:   "var(--graph-edge-curiosity)",
  interested_in:    "var(--graph-edge-curiosity)",
  researches:       "var(--graph-edge-curiosity)",
  works_in:         "var(--graph-edge-work)",
  works_at:         "var(--graph-edge-work)",
  leads:            "var(--graph-edge-work)",
  building:         "var(--graph-edge-work)",
  collaborates_on:  "var(--graph-edge-work)",
  studied:          "var(--graph-edge-application)",
  applied:          "var(--graph-edge-application)",
  used_in:          "var(--graph-edge-application)",
  discussed:        "var(--graph-edge-application)",
  named:            "var(--graph-edge-identity)",
  is:               "var(--graph-edge-identity)",
  prefers:          "var(--graph-edge-intention)",
  decided:          "var(--graph-edge-intention)",
  has_prerequisite: "var(--graph-edge)",
  related_to:       "var(--graph-edge)",
};
