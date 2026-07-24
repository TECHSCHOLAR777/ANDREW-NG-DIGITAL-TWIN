// components/KnowledgeGraphView.tsx
/* eslint-disable react-hooks/set-state-in-effect */
// The Context Graph.
// ─────────────────────────────────────────────────────────────────────────────
// A mostly-monochrome, actionable view of the context the twin has retained.
// Nodes and edges are graphite; orange is reserved for the selected node and
// its connected paths. Categories are told apart by their label, not colour.
// Every retained relationship is inspectable, has its evidence, and can be
// forgotten. A list view mirrors the same facts and controls for keyboard and
// screen-reader users, and an equivalent-information layout replaces the old
// rainbow legend and the 8-9px labels.
// ─────────────────────────────────────────────────────────────────────────────

"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Panel,
  useNodesState,
  useEdgesState,
  NodeProps,
  Handle,
  Position,
  BackgroundVariant,
  ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { List, Network, RotateCcw, Sparkles, Trash2, X } from "lucide-react";

import { mapTripletRowsToReactFlow, mergeGraphUpdate } from "../lib/graphMapper";
import type {
  TripletRow,
  EdgeRow,
  KnowledgeNode,
  KnowledgeEdge,
} from "../types/graph";
import { NODE_TYPE_COLORS } from "../types/graph";

// A signed-in user's self node arrives typed "Student"; the product shows it
// as a person, not a learner.
function displayCategory(nodeType: string): string {
  return nodeType === "Student" ? "Person" : nodeType;
}

// Confidence in plain language, never a percentage.
function confidenceLabel(score: number): string {
  if (score >= 0.66) return "Strong";
  if (score >= 0.33) return "Developing";
  return "Newly noted";
}

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(mq.matches);
    const on = () => setReduced(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return reduced;
}

// ─────────────────────────────────────────────────────────────────────────────
// CUSTOM NODE — monochrome, label-first, no score/hop clutter on the face
// ─────────────────────────────────────────────────────────────────────────────
const KnowledgeNodeComponent: React.FC<NodeProps<KnowledgeNode>> = ({ data, selected }) => {
  const isAnchor = data.hopDistance === 0;
  const typeColor = NODE_TYPE_COLORS[data.nodeType] ?? "var(--graph-paper)";

  return (
    <div
      style={{
        width: 168,
        minHeight: 68,
        borderRadius: 12,
        background: `color-mix(in srgb, ${typeColor} 8%, var(--surface))`,
        border: selected
          ? "1.5px solid var(--brand)"
          : isAnchor
            ? `1.5px solid ${typeColor}`
            : `1px solid color-mix(in srgb, ${typeColor} 42%, var(--border))`,
        boxShadow: selected
          ? "0 0 0 3px var(--brand-soft), 0 4px 12px rgba(0,0,0,0.10)"
          : `inset 3px 0 0 ${typeColor}, 0 5px 16px rgba(0,0,0,0.09)`,
        display: "flex",
        flexDirection: "column",
        gap: 4,
        padding: "10px 12px",
        cursor: "pointer",
        transition: "box-shadow 0.2s ease, border-color 0.2s ease",
        boxSizing: "border-box",
      }}
    >
      <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />

      <span
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          fontSize: 11,
          fontWeight: 650,
          color: selected ? "var(--brand)" : typeColor,
          letterSpacing: "0.045em",
        }}
      >
        <span
          aria-hidden="true"
          style={{
            width: 6,
            height: 6,
            borderRadius: "9999px",
            background: selected ? "var(--brand)" : typeColor,
            boxShadow: `0 0 0 3px color-mix(in srgb, ${typeColor} 14%, transparent)`,
          }}
        />
        {displayCategory(data.nodeType)}
      </span>
      <span
        style={{
          fontSize: 13,
          fontWeight: 600,
          color: "var(--text)",
          lineHeight: 1.3,
          overflow: "hidden",
          textOverflow: "ellipsis",
          display: "-webkit-box",
          WebkitLineClamp: 2,
          WebkitBoxOrient: "vertical",
        }}
      >
        {data.label}
      </span>
    </div>
  );
};

// ─────────────────────────────────────────────────────────────────────────────
// NODE INSPECTOR — plain confidence, evidence, ask, and forget
// ─────────────────────────────────────────────────────────────────────────────
interface InspectorProps {
  node: KnowledgeNode;
  allEdges: KnowledgeEdge[];
  allNodes: KnowledgeNode[];
  onClose: () => void;
  onExplore?: (label: string) => void;
  onForgetEdge?: (edgeId: string) => void;
}

const NodeInspector: React.FC<InspectorProps> = ({
  node,
  allEdges,
  allNodes,
  onClose,
  onExplore,
  onForgetEdge,
}) => {
  const connections = allEdges.filter(
    (e) => e.source === node.id || e.target === node.id
  );

  return (
    <div
      role="dialog"
      aria-label={`Details for ${node.data.label}`}
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: 14,
        padding: "16px 18px",
        minWidth: 250,
        maxWidth: 300,
        boxShadow: "0 8px 30px -12px rgba(0,0,0,0.35)",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12, gap: 8 }}>
        <div style={{ minWidth: 0 }}>
          <p style={{ color: "var(--text)", fontWeight: 600, fontSize: 15, lineHeight: 1.25, margin: 0 }}>
            {node.data.label}
          </p>
          <span style={{ color: "var(--text-muted)", fontSize: 12 }}>
            {displayCategory(node.data.nodeType)} · {confidenceLabel(node.data.combinedScore)}
          </span>
        </div>
        <button
          onClick={onClose}
          aria-label="Close details"
          style={{ background: "none", border: "none", color: "var(--text-subtle)", cursor: "pointer", padding: 2, lineHeight: 0 }}
        >
          <X size={16} />
        </button>
      </div>

      <p style={{ color: "var(--text-muted)", fontSize: 11, fontWeight: 500, letterSpacing: "0.05em", textTransform: "uppercase", margin: "0 0 6px" }}>
        Connections ({connections.length})
      </p>
      {connections.length > 0 ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: 220, overflowY: "auto" }}>
          {connections.map((edge) => {
            const isOutbound = edge.source === node.id;
            const partnerId = isOutbound ? edge.target : edge.source;
            const partner = allNodes.find((n) => n.id === partnerId);
            const partnerLabel = partner?.data?.label || partnerId;
            const predicate = String(edge.data?.predicate ?? "related_to").replace(/_/g, " ");
            const evidence = edge.data?.evidence as string | undefined;
            return (
              <div
                key={edge.id}
                style={{
                  background: "var(--surface-alt)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  padding: "8px 10px",
                  fontSize: 12,
                }}
              >
                <div style={{ color: "var(--text)", lineHeight: 1.4 }}>
                  <span style={{ color: "var(--text-muted)" }}>{isOutbound ? predicate : `${predicate} (from)`} </span>
                  <span style={{ fontWeight: 600 }}>{partnerLabel}</span>
                </div>
                {evidence && (
                  <p style={{ color: "var(--text-subtle)", fontStyle: "italic", margin: "4px 0 0", lineHeight: 1.4 }}>
                    &ldquo;{evidence.slice(0, 120)}{evidence.length > 120 ? "…" : ""}&rdquo;
                  </p>
                )}
                {onForgetEdge && (
                  <button
                    onClick={() => onForgetEdge(edge.id)}
                    style={{
                      marginTop: 6,
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 4,
                      background: "none",
                      border: "1px solid var(--border)",
                      borderRadius: 6,
                      color: "var(--text-muted)",
                      fontSize: 11,
                      padding: "3px 8px",
                      cursor: "pointer",
                    }}
                  >
                    <Trash2 size={12} /> Forget this
                  </button>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        <p style={{ color: "var(--text-subtle)", fontSize: 12, fontStyle: "italic", margin: 0 }}>
          No connections in view.
        </p>
      )}

      {onExplore && (
        <button
          onClick={() => {
            onExplore(node.data.label);
            onClose();
          }}
          style={{
            width: "100%",
            marginTop: 14,
            padding: "9px 12px",
            background: "var(--brand)",
            border: "none",
            borderRadius: 9,
            color: "var(--brand-text)",
            fontSize: 13,
            fontWeight: 500,
            cursor: "pointer",
          }}
        >
          Ask about this
        </button>
      )}
    </div>
  );
};

// ─────────────────────────────────────────────────────────────────────────────
// MAIN VIEW
// ─────────────────────────────────────────────────────────────────────────────
interface KnowledgeGraphViewProps {
  triplets: TripletRow[];
  edges: EdgeRow[];
  isLoading: boolean;
  width?: number | string;
  height?: number | string;
  onExploreNode?: (label: string) => void;
  onForgetEdge?: (edgeId: string) => void;
}

const NODE_TYPES = { knowledgeNode: KnowledgeNodeComponent };

export const KnowledgeGraphView: React.FC<KnowledgeGraphViewProps> = ({
  triplets,
  edges,
  isLoading,
  width = 800,
  height = 600,
  onExploreNode,
  onForgetEdge,
}) => {
  const reducedMotion = usePrefersReducedMotion();
  const [nodes, setNodes, onNodesChange] = useNodesState<KnowledgeNode>([]);
  const [rfEdges, setEdges, onEdgesChange] = useEdgesState<KnowledgeEdge>([]);
  const [selectedNode, setSelectedNode] = useState<KnowledgeNode | null>(null);
  const [listView, setListView] = useState(false);
  const [layoutVersion, setLayoutVersion] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const reactFlowRef = useRef<ReactFlowInstance<KnowledgeNode, KnowledgeEdge> | null>(null);
  const fitFrameRef = useRef<number | null>(null);
  const prevGraphRef = useRef<{ nodes: KnowledgeNode[]; edges: KnowledgeEdge[] }>({
    nodes: [],
    edges: [],
  });

  const scheduleFitView = useCallback(() => {
    if (fitFrameRef.current !== null) {
      window.cancelAnimationFrame(fitFrameRef.current);
    }
    fitFrameRef.current = window.requestAnimationFrame(() => {
      fitFrameRef.current = null;
      void reactFlowRef.current?.fitView({
        padding: 0.18,
        minZoom: 0.25,
        maxZoom: 1.15,
        duration: reducedMotion ? 0 : 320,
        interpolate: "smooth",
      });
    });
  }, [reducedMotion]);

  useEffect(
    () => () => {
      if (fitFrameRef.current !== null) {
        window.cancelAnimationFrame(fitFrameRef.current);
      }
    },
    []
  );

  useEffect(() => {
    if (triplets.length === 0) {
      setNodes([]);
      setEdges([]);
      setSelectedNode(null);
      prevGraphRef.current = { nodes: [], edges: [] };
      return;
    }
    const measuredWidth = containerRef.current?.clientWidth ?? 0;
    const measuredHeight = containerRef.current?.clientHeight ?? 0;
    const numWidth =
      typeof width === "number" ? width : Math.max(measuredWidth, 640);
    const numHeight =
      typeof height === "number" ? height : Math.max(measuredHeight, 560);
    const newGraph = mapTripletRowsToReactFlow(triplets, edges, numWidth, numHeight);
    // Reduced motion: no travelling edge animation.
    if (reducedMotion) {
      newGraph.edges = newGraph.edges.map((e) => ({ ...e, animated: false }));
    }
    const merged = mergeGraphUpdate(prevGraphRef.current, newGraph);
    setNodes(merged.nodes);
    setEdges(merged.edges);
    prevGraphRef.current = merged;
    setLayoutVersion((version) => version + 1);
  }, [triplets, edges, width, height, reducedMotion, setNodes, setEdges]);

  useEffect(() => {
    if (layoutVersion > 0 && !listView) {
      scheduleFitView();
    }
  }, [layoutVersion, listView, scheduleFitView]);

  useEffect(() => {
    const element = containerRef.current;
    if (!element || typeof ResizeObserver === "undefined") return;

    let previousWidth = element.clientWidth;
    let previousHeight = element.clientHeight;
    const observer = new ResizeObserver(([entry]) => {
      const { width: nextWidth, height: nextHeight } = entry.contentRect;
      const changed =
        Math.abs(nextWidth - previousWidth) > 3 ||
        Math.abs(nextHeight - previousHeight) > 3;
      previousWidth = nextWidth;
      previousHeight = nextHeight;
      if (changed && !listView && prevGraphRef.current.nodes.length > 0) {
        scheduleFitView();
      }
    });

    observer.observe(element);
    return () => observer.disconnect();
  }, [listView, scheduleFitView]);

  const onNodeClick = useCallback((_: React.MouseEvent, node: KnowledgeNode) => {
    setSelectedNode((prev) => (prev?.id === node.id ? null : node));
  }, []);

  const empty = !isLoading && nodes.length === 0;

  const listItems = useMemo(
    () =>
      rfEdges.map((e) => {
        const s = nodes.find((n) => n.id === e.source)?.data.label ?? e.source;
        const t = nodes.find((n) => n.id === e.target)?.data.label ?? e.target;
        const pred = String(e.data?.predicate ?? "related to").replace(/_/g, " ");
        return { id: e.id, s, t, pred, evidence: e.data?.evidence as string | undefined };
      }),
    [rfEdges, nodes]
  );

  return (
    <div
      ref={containerRef}
      style={{ width: width ?? "100%", height: height ?? "100%", background: "var(--surface)", overflow: "hidden", position: "relative" }}
    >
      {/* Loading — theme-aware, never a white overlay */}
      {isLoading && (
        <div
          style={{
            position: "absolute",
            inset: 0,
            zIndex: 100,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background: "var(--surface-glass)",
            backdropFilter: "blur(4px)",
            color: "var(--text-muted)",
            fontSize: 13,
            fontWeight: 500,
          }}
        >
          Updating the context graph…
        </div>
      )}

      {/* Empty */}
      {empty && !listView && (
        <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: 24, textAlign: "center" }}>
          <div style={{ display: "grid", placeItems: "center", width: 44, height: 44, borderRadius: "9999px", background: "var(--surface-alt)", color: "var(--text-muted)", marginBottom: 12 }}>
            <Network size={20} />
          </div>
          <p style={{ fontSize: 15, fontWeight: 500, color: "var(--text)", margin: 0 }}>
            Nothing here yet
          </p>
          <p style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 6, maxWidth: "30ch" }}>
            As you talk, the details and connections worth remembering will
            appear here. You can inspect or remove any of them.
          </p>
        </div>
      )}

      {/* View toggle: graph vs accessible list */}
      {!empty && (
        <div style={{ position: "absolute", top: 10, right: 10, zIndex: 20 }}>
          <button
            onClick={() => setListView((v) => !v)}
            aria-pressed={listView}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              background: "var(--surface)",
              border: "1px solid var(--border)",
              borderRadius: 8,
              color: "var(--text-muted)",
              fontSize: 12,
              padding: "5px 10px",
              cursor: "pointer",
            }}
          >
            {listView ? <Network size={14} /> : <List size={14} />}
            {listView ? "Graph" : "List"}
          </button>
        </div>
      )}

      {/* Accessible list alternative — same facts and controls */}
      {listView && !empty && (
        <div style={{ position: "absolute", inset: 0, overflowY: "auto", padding: "48px 14px 14px", background: "var(--surface)" }}>
          {listItems.length === 0 ? (
            <p style={{ color: "var(--text-muted)", fontSize: 13 }}>No connections yet.</p>
          ) : (
            <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 8 }}>
              {listItems.map((it) => (
                <li key={it.id} style={{ border: "1px solid var(--border)", borderRadius: 10, padding: "10px 12px", background: "var(--surface-alt)" }}>
                  <div style={{ fontSize: 13, color: "var(--text)" }}>
                    <strong>{it.s}</strong>{" "}
                    <span style={{ color: "var(--text-muted)" }}>{it.pred}</span>{" "}
                    <strong>{it.t}</strong>
                  </div>
                  {it.evidence && (
                    <p style={{ fontSize: 12, color: "var(--text-subtle)", fontStyle: "italic", margin: "4px 0 0" }}>
                      &ldquo;{it.evidence.slice(0, 140)}&rdquo;
                    </p>
                  )}
                  <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                    {onExploreNode && (
                      <button onClick={() => onExploreNode(it.t)} style={listBtn}>
                        <Sparkles size={12} /> Ask
                      </button>
                    )}
                    {onForgetEdge && (
                      <button onClick={() => onForgetEdge(it.id)} style={listBtn}>
                        <RotateCcw size={12} /> Forget
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {!listView && (
        <ReactFlow
          nodes={nodes}
          edges={rfEdges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={onNodeClick}
          onInit={(instance) => {
            reactFlowRef.current = instance;
            scheduleFitView();
          }}
          nodeTypes={NODE_TYPES}
          fitViewOptions={{ padding: 0.18, minZoom: 0.25, maxZoom: 1.15 }}
          minZoom={0.3}
          maxZoom={2.5}
          proOptions={{ hideAttribution: true }}
          style={{ background: "transparent" }}
        >
          <Background variant={BackgroundVariant.Dots} gap={24} size={1} color="var(--border)" />
          <Controls style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8 }} />
          {nodes.length > 8 && (
            <MiniMap
              style={{ background: "var(--surface)", border: "1px solid var(--border)" }}
              nodeColor={(node) =>
                NODE_TYPE_COLORS[
                  (node.data as KnowledgeNode["data"]).nodeType
                ] ?? "var(--graph-paper)"
              }
              nodeStrokeColor="var(--surface)"
              nodeStrokeWidth={2}
              maskColor="var(--surface-glass)"
            />
          )}

          {selectedNode && (
            <Panel position="top-right">
              <NodeInspector
                node={selectedNode}
                allEdges={rfEdges}
                allNodes={nodes}
                onClose={() => setSelectedNode(null)}
                onExplore={onExploreNode}
                onForgetEdge={onForgetEdge}
              />
            </Panel>
          )}

          <Panel position="bottom-left">
            <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 8, padding: "4px 12px", color: "var(--text-muted)", fontSize: 11 }}>
              {nodes.length} items · {rfEdges.length} connections
            </div>
          </Panel>
        </ReactFlow>
      )}
    </div>
  );
};

const listBtn: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 4,
  background: "none",
  border: "1px solid var(--border)",
  borderRadius: 6,
  color: "var(--text-muted)",
  fontSize: 11,
  padding: "3px 8px",
  cursor: "pointer",
};

export default KnowledgeGraphView;
