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
 * Fallback node colours for the built-in React Flow renderer.
 *
 * The general-context types added in migration 015 default to neutral grey so
 * a new backend type never renders untyped. The Context Graph redesign moves
 * the whole graph to a mostly-monochrome graphite/white language with orange
 * reserved for active/selected paths; the original five keep their current
 * colours only until that redesign lands. Kept exhaustive over NodeType.
 */
export const NODE_TYPE_COLORS: Record<NodeType, string> = {
  Student:      "#1A56DB",   // Royal Blue
  Concept:      "#F59E0B",   // Amber
  Project:      "#8B5CF6",   // Purple
  Tool:         "#10B981",   // Green
  Paper:        "#6366F1",   // Indigo
  Person:       "#6B7280",   // Neutral grey (general context)
  Organization: "#6B7280",
  Industry:     "#6B7280",
  Goal:         "#6B7280",
  Preference:   "#6B7280",
  ResearchArea: "#6B7280",
};

/** Edge color per predicate type. */
export const PREDICATE_COLORS: Record<string, string> = {
  struggles_with:   "#EF4444",   // Red
  mastered:         "#10B981",   // Green
  curious_about:    "#F59E0B",   // Amber
  works_in:         "#8B5CF6",   // Purple
  studied:          "#6366F1",   // Indigo
  applied:          "#3B82F6",   // Blue
  confused_about:   "#F97316",   // Orange
  wants_to_learn:   "#06B6D4",   // Cyan
  has_prerequisite: "#9CA3AF",   // Muted Gray
  related_to:       "#D1D5DB",   // Gray
  used_in:          "#A78BFA",   // Violet
  named:            "#14B8A6",   // Teal
  is:               "#64748B",   // Slate
};
