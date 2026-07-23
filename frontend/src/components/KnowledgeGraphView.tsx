// components/KnowledgeGraphView.tsx
/* eslint-disable react-hooks/set-state-in-effect */
// This mirrors app/page.tsx: several effects here synchronise React state from
// changing props (triplets/edges → derived React Flow graph). That is a
// legitimate props-to-derived-state sync, and the file is slated for a full
// rebuild in the Context Graph redesign phase.
// ─────────────────────────────────────────────────────────────────────────────
// React Flow knowledge graph visualizer.
//
// Features:
//   • Custom circular nodes with color coding by type
//   • Animated "struggles_with" edges
//   • Live update support (merges new data without full re-layout)
//   • Minimap, controls, and pan/zoom
//   • Node click → shows evidence tooltip
//   • Legend panel
//
// Usage:
//   <KnowledgeGraphView
//     triplets={tripletRows}
//     edges={edgeRows}
//     isLoading={false}
//   />
// ─────────────────────────────────────────────────────────────────────────────

"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
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
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import {
  mapTripletRowsToReactFlow,
  mergeGraphUpdate,
} from "../lib/graphMapper";
import type {
  TripletRow,
  EdgeRow,
  KnowledgeNode,
  KnowledgeEdge,
} from "../types/graph";
import { NODE_TYPE_COLORS, PREDICATE_COLORS } from "../types/graph";

// ─────────────────────────────────────────────────────────────────────────────
// CUSTOM NODE COMPONENT
// ─────────────────────────────────────────────────────────────────────────────

const KnowledgeNodeComponent: React.FC<NodeProps<KnowledgeNode>> = ({
  data,
  selected,
}) => {
  const color = NODE_TYPE_COLORS[data.nodeType] ?? "#64748b";

  return (
    <div
      style={{
        width:           160,
        height:          80,
        borderRadius:    "8px",
        background:      "var(--surface)",
        borderTop:       selected ? "1.5px solid var(--brand)" : "1px solid var(--border)",
        borderRight:     selected ? "1.5px solid var(--brand)" : "1px solid var(--border)",
        borderBottom:    selected ? "1.5px solid var(--brand)" : "1px solid var(--border)",
        borderLeft:      `6px solid ${color}`,
        boxShadow:       data.hopDistance === 0
          ? `0 4px 12px rgba(0,0,0,0.06), 0 0 10px ${color}22`
          : selected
          ? `0 0 0 2px ${color}22, 0 4px 10px rgba(0,0,0,0.08)`
          : "0 2px 6px rgba(0,0,0,0.04)",
        display:         "flex",
        flexDirection:   "column",
        justifyContent:  "space-between",
        padding:         "8px 10px",
        cursor:          "pointer",
        transition:      "box-shadow 0.2s ease, border-color 0.2s ease",
        position:        "relative",
        boxSizing:       "border-box",
      }}
    >
      {/* React Flow handles (invisible, for edge routing) */}
      <Handle type="target" position={Position.Top}    style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />

      {/* Top Header Row */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%" }}>
        <span
          style={{
            fontSize:       8,
            fontWeight:     600,
            color:          "var(--text-subtle)",
            textTransform:  "uppercase",
            letterSpacing:  "0.05em",
          }}
        >
          {data.nodeType}
        </span>
        <span
          style={{
            fontSize:       9,
            fontWeight:     700,
            color:          color,
            background:     `${color}12`,
            padding:        "1px 4px",
            borderRadius:   "4px",
          }}
        >
          {(data.combinedScore * 100).toFixed(0)}%
        </span>
      </div>

      {/* Node label */}
      <div
        style={{
          fontSize:    12,
          fontWeight:  600,
          color:       "var(--text)",
          textAlign:   "left",
          lineHeight:  1.25,
          width:       "100%",
          overflow:    "hidden",
          textOverflow: "ellipsis",
          display:     "-webkit-box",
          WebkitLineClamp: 2,
          WebkitBoxOrient: "vertical",
        }}
      >
        {data.label}
      </div>

      {/* Bottom Footer Row */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%" }}>
        <span style={{ fontSize: 9, color: "var(--text-subtle)" }}>
          Hop {data.hopDistance}
        </span>

        {/* Hop distance indicator (ring/dot for anchor nodes) */}
        {data.hopDistance === 0 && (
          <div style={{ display: "flex", alignItems: "center", gap: "3px" }}>
            <span style={{ fontSize: 8, fontWeight: 700, color: "#10B981", textTransform: "uppercase" }}>
              Anchor
            </span>
            <span style={{ position: "relative", display: "flex", height: "6px", width: "6px" }}>
              <span style={{
                position: "absolute",
                display: "inline-flex",
                height: "100%",
                width: "100%",
                borderRadius: "50%",
                backgroundColor: "#10B981",
                opacity: 0.75,
                animation: "ping 1.5s cubic-bezier(0, 0, 0.2, 1) infinite"
              }} />
              <span style={{
                position: "relative",
                display: "inline-flex",
                borderRadius: "50%",
                height: "6px",
                width: "6px",
                backgroundColor: "#10B981"
              }} />
            </span>
          </div>
        )}
      </div>
    </div>
  );
};

// ─────────────────────────────────────────────────────────────────────────────
// LEGEND COMPONENT
// ─────────────────────────────────────────────────────────────────────────────

const GraphLegend: React.FC = () => (
  <div
    style={{
      background:   "var(--surface)",
      border:       "1px solid var(--border)",
      borderRadius: 12,
      padding:      "12px 16px",
      boxShadow:    "0 1px 3px rgba(0,0,0,0.05)",
    }}
  >
    <p style={{ color: "var(--text-muted)", fontSize: 11, fontWeight: 500,
                letterSpacing: "0.07em", textTransform: "none",
                marginBottom: 8 }}>
      Node types
    </p>
    {Object.entries(NODE_TYPE_COLORS).map(([type, color]) => (
      <div key={type} style={{ display: "flex", alignItems: "center",
                               gap: 8, marginBottom: 4 }}>
        <div style={{ width: 12, height: 12, borderRadius: "50%",
                      background: color, flexShrink: 0 }} />
        <span style={{ color: "var(--text)", fontSize: 10 }}>{type}</span>
      </div>
    ))}
    <p style={{ color: "var(--text-muted)", fontSize: 11, fontWeight: 500,
                letterSpacing: "0.07em", textTransform: "none",
                margin: "12px 0 8px" }}>
      Edge types
    </p>
    {Object.entries(PREDICATE_COLORS).slice(0, 5).map(([pred, color]) => (
      <div key={pred} style={{ display: "flex", alignItems: "center",
                               gap: 8, marginBottom: 4 }}>
        <div style={{ width: 20, height: 2, background: color, flexShrink: 0 }} />
        <span style={{ color: "var(--text)", fontSize: 10 }}>
          {pred.replace(/_/g, " ")}
        </span>
      </div>
    ))}
  </div>
);

// ─────────────────────────────────────────────────────────────────────────────
// NODE DETAIL PANEL
// ─────────────────────────────────────────────────────────────────────────────

interface NodeDetailProps {
  node:      KnowledgeNode | null;
  allEdges:  KnowledgeEdge[];
  allNodes:  KnowledgeNode[];
  onClose:   () => void;
  onExplore?:(label: string) => void;
}

const NodeDetailPanel: React.FC<NodeDetailProps> = ({ node, allEdges, allNodes, onClose, onExplore }) => {
  if (!node) return null;
  const color = NODE_TYPE_COLORS[node.data.nodeType] ?? "#64748b";

  const metadataEntries = Object.entries(node.data.metadata || {}).filter((entry) => {
    const val = entry[1];
    return val !== null && val !== undefined && val !== "" && (typeof val !== "object" || Object.keys(val).length > 0);
  });

  const connections = allEdges.filter(
    (edge) => edge.source === node.id || edge.target === node.id
  );

  return (
    <div
      style={{
        background:    "var(--surface)",
        border:        `1px solid var(--border)`,
        borderRadius:  12,
        padding:       "16px 20px",
        minWidth:      240,
        maxWidth:      300,
        boxShadow:     `0 4px 16px rgba(0,0,0,0.06)`,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "flex-start", marginBottom: 12 }}>
        <div>
          <p style={{ color: "var(--text)", fontWeight: 600, fontSize: 14,
                      marginBottom: 4, lineHeight: 1.2 }}>
            {node.data.label}
          </p>
          <span style={{ background: color, color: "#fff", borderRadius: 4,
                         padding: "1px 6px", fontSize: 9, fontWeight: 500,
                         textTransform: "uppercase" }}>
            {node.data.nodeType}
          </span>
        </div>
        <button
          onClick={onClose}
          style={{ background: "none", border: "none", color: "var(--text-subtle)",
                   cursor: "pointer", fontSize: 20, padding: 0, lineHeight: 1 }}
        >
          ×
        </button>
      </div>

      {/* Relevance Score */}
      <div style={{ marginBottom: 12 }}>
        <p style={{ color: "var(--text-muted)", fontSize: 10, fontWeight: 500,
                    letterSpacing: "0.05em", textTransform: "uppercase", marginBottom: 4 }}>
          Relevance score
        </p>
        <div style={{ background: "var(--surface-alt)", borderRadius: 4, height: 6 }}>
          <div style={{
            width:        `${Math.round(node.data.combinedScore * 100)}%`,
            height:       "100%",
            background:   color,
            borderRadius: 4,
            transition:   "width 0.5s ease",
          }} />
        </div>
        <p style={{ color: "var(--text-subtle)", fontSize: 10, marginTop: 4 }}>
          {(node.data.combinedScore * 100).toFixed(0)}% · Hop {node.data.hopDistance}
        </p>
      </div>

      {/* Dynamic Metadata / Properties */}
      {metadataEntries.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <p style={{ color: "var(--text-muted)", fontSize: 10, fontWeight: 500,
                      letterSpacing: "0.05em", textTransform: "uppercase", marginBottom: 6 }}>
            Properties
          </p>
          <div style={{ background: "var(--surface-alt)", borderRadius: 8, border: "1px solid var(--border)", padding: "6px 8px" }}>
            {metadataEntries.map(([key, val]) => (
              <div key={key} style={{ display: "flex", justifyContent: "space-between", fontSize: 10, margin: "4px 0" }}>
                <span style={{ color: "var(--text-muted)", fontWeight: 500, textTransform: "capitalize" }}>{key.replace(/_/g, " ")}</span>
                <span style={{ color: "var(--text)", textAlign: "right", fontWeight: 500 }}>
                  {typeof val === "object" ? JSON.stringify(val) : String(val)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* True Connections Section */}
      <div style={{ marginBottom: 4 }}>
        <p style={{ color: "var(--text-muted)", fontSize: 10, fontWeight: 500,
                    letterSpacing: "0.05em", textTransform: "uppercase", marginBottom: 6 }}>
          Connections ({connections.length})
        </p>
        {connections.length > 0 ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 6, maxHeight: 180, overflowY: "auto" }}>
            {connections.map((edge) => {
              const isOutbound = edge.source === node.id;
              const partnerId = isOutbound ? edge.target : edge.source;
              const partnerNode = allNodes.find((n) => n.id === partnerId);
              const partnerLabel = partnerNode?.data?.label || partnerId;
              const partnerColor = partnerNode ? (NODE_TYPE_COLORS[partnerNode.data.nodeType] ?? "#64748b") : "#64748b";
              const predicate = edge.data?.predicate ?? "related_to";
              const predicateColor = PREDICATE_COLORS[predicate] ?? "var(--text-muted)";

              return (
                <div
                  key={edge.id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    background: "var(--surface-alt)",
                    border: "1px solid var(--border)",
                    borderRadius: 6,
                    padding: "6px 8px",
                    fontSize: 10,
                    lineHeight: 1.3,
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 4, flexWrap: "wrap", width: "100%" }}>
                    {isOutbound ? (
                      <>
                        <span style={{ color: "var(--text-subtle)" }}>→</span>
                        <span style={{ fontWeight: 600, color: predicateColor }}>
                          {String(edge.label || predicate).replace(/_/g, " ")}
                        </span>
                        <span style={{ color: partnerColor, fontWeight: 600 }}>{partnerLabel}</span>
                      </>
                    ) : (
                      <>
                        <span style={{ color: partnerColor, fontWeight: 600 }}>{partnerLabel}</span>
                        <span style={{ fontWeight: 600, color: predicateColor }}>
                          {String(edge.label || predicate).replace(/_/g, " ")}
                        </span>
                        <span style={{ color: "var(--text-subtle)" }}>→</span>
                      </>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <p style={{ color: "var(--text-subtle)", fontSize: 10, fontStyle: "italic" }}>No active connections in graph view.</p>
        )}
      </div>

      {onExplore && (
        <button
          onClick={() => {
            onExplore(node.data.label);
            onClose();
          }}
          style={{
            width: "100%",
            marginTop: 14,
            padding: "8px 12px",
            background: "var(--brand)",
            border: "1px solid var(--brand)",
            borderRadius: 8,
            color: "var(--surface)",
            fontSize: 12,
            fontWeight: 500,
            cursor: "pointer",
            transition: "all 0.2s ease",
            textAlign: "center",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = "var(--brand)E0";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = "var(--brand)";
          }}
        >
          Ask Andrew about this concept
        </button>
      )}
    </div>
  );
};


// ─────────────────────────────────────────────────────────────────────────────
// MAIN KNOWLEDGE GRAPH VIEW
// ─────────────────────────────────────────────────────────────────────────────

interface KnowledgeGraphViewProps {
  triplets:  TripletRow[];
  edges:     EdgeRow[];
  isLoading: boolean;
  width?:    number | string;
  height?:   number | string;
  onExploreNode?: (label: string) => void;
}

const NODE_TYPES = { knowledgeNode: KnowledgeNodeComponent };

export const KnowledgeGraphView: React.FC<KnowledgeGraphViewProps> = ({
  triplets,
  edges,
  isLoading,
  width  = 800,
  height = 600,
  onExploreNode,
}) => {

  const [nodes, setNodes, onNodesChange] = useNodesState<KnowledgeNode>([]);
  const [rfEdges, setEdges, onEdgesChange] = useEdgesState<KnowledgeEdge>([]);
  const [selectedNode, setSelectedNode] = useState<KnowledgeNode | null>(null);
  const prevGraphRef = useRef<{ nodes: KnowledgeNode[]; edges: KnowledgeEdge[] }>({
    nodes: [], edges: [],
  });

  // Re-map when triplets or edges change
  useEffect(() => {
    if (triplets.length === 0) {
      // Explicitly clear on empty input. The old early-return left the
      // previous session's graph on screen when switching to a fresh
      // session, and left prevGraphRef pinning new layouts to stale
      // coordinates.
      setNodes([]);
      setEdges([]);
      setSelectedNode(null);
      prevGraphRef.current = { nodes: [], edges: [] };
      return;
    }

    const numWidth = typeof width === "number" ? width : 800;
    const numHeight = typeof height === "number" ? height : 600;
    const newGraph = mapTripletRowsToReactFlow(triplets, edges, numWidth, numHeight);

    // Incremental merge: preserve existing node positions
    const merged = mergeGraphUpdate(
      prevGraphRef.current,
      newGraph,
    );

    setNodes(merged.nodes);
    setEdges(merged.edges);
    prevGraphRef.current = merged;
  }, [triplets, edges, width, height, setNodes, setEdges]);

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: KnowledgeNode) => {
      setSelectedNode((prev) => (prev?.id === node.id ? null : node));
    },
    []
  );

  return (
    <div
      style={{
        width: width ?? "100%",
        height: height ?? "100%",
        background: "var(--surface)",
        overflow: "hidden",
        position: "relative",
      }}
    >
      {/* Loading overlay */}
      {isLoading && (
        <div
          style={{
            position:  "absolute",
            inset:     0,
            zIndex:    100,
            display:   "flex",
            alignItems:"center",
            justifyContent: "center",
            background: "rgba(255,255,255,0.75)",
            backdropFilter: "blur(4px)",
          }}
        >
          <div style={{ color: "var(--brand)", fontSize: 14, fontWeight: 500 }}>
            Updating knowledge graph…
          </div>
        </div>
      )}

      {/* Empty state */}
      {!isLoading && nodes.length === 0 && (
        <div
          style={{
            position:  "absolute",
            inset:     0,
            display:   "flex",
            flexDirection: "column",
            alignItems:"center",
            justifyContent: "center",
            color:     "var(--text-muted)",
          }}
        >
          <svg className="w-12 h-12 text-slate-300 mb-3" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
            <circle cx="32" cy="18" r="4" fill="var(--text-subtle)" />
            <circle cx="16" cy="42" r="4" fill="var(--border)" stroke="var(--text-subtle)" strokeWidth="2" />
            <circle cx="48" cy="42" r="4" fill="var(--border)" stroke="var(--text-subtle)" strokeWidth="2" />
            <line x1="29.5" y1="21.5" x2="18.5" y2="38.5" stroke="var(--text-subtle)" strokeWidth="2" strokeDasharray="3 3" />
            <line x1="34.5" y1="21.5" x2="45.5" y2="38.5" stroke="var(--text-subtle)" strokeWidth="2" strokeDasharray="3 3" />
            <line x1="20" y1="42" x2="44" y2="42" stroke="var(--border)" strokeWidth="2" />
          </svg>
          <p style={{ fontSize: 13, fontWeight: 500, color: "var(--text)" }}>
            Start a conversation to build your learning map
          </p>
          <p style={{ fontSize: 11, color: "var(--text-subtle)", marginTop: 4 }}>
            Andrew will map details to the Memory Matrix in real-time
          </p>
        </div>
      )}

      <ReactFlow
        nodes={nodes}
        edges={rfEdges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        nodeTypes={NODE_TYPES}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.3}
        maxZoom={2.5}
        proOptions={{ hideAttribution: true }}
        style={{ background: "transparent" }}
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={24}
          size={1}
          color="var(--border)"
        />
        <Controls
          style={{
            background: "var(--surface)",
            border:     "1px solid var(--border)",
            borderRadius: 8,
          }}
        />
        {nodes.length > 0 && (
          <MiniMap
            style={{
              background: "var(--surface)",
              border:     "1px solid var(--border)",
            }}
            nodeColor={(n: KnowledgeNode) =>
              NODE_TYPE_COLORS[n.data?.nodeType] ?? "var(--text-subtle)"
            }
            maskColor="rgba(247,248,250,0.5)"
          />
        )}

        {/* Legend */}
        <Panel position="top-left">
          <GraphLegend />
        </Panel>

        {/* Node detail panel */}
        {selectedNode && (
          <Panel position="top-right">
            <NodeDetailPanel
              node={selectedNode}
              allEdges={rfEdges}
              allNodes={nodes}
              onClose={() => setSelectedNode(null)}
              onExplore={onExploreNode}
            />
          </Panel>
        )}


        {/* Node count badge */}
        <Panel position="bottom-left">
          <div
            style={{
              background:   "var(--surface)",
              border:       "1px solid var(--border)",
              borderRadius: 8,
              padding:      "4px 12px",
              color:        "var(--text-muted)",
              fontSize:     11,
            }}
          >
            {nodes.length} concepts · {rfEdges.length} relations
          </div>
        </Panel>
      </ReactFlow>

      {/* Spinning and ping animation keyframes (injected once) */}
      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to   { transform: rotate(360deg); }
        }
        @keyframes ping {
          0% { transform: scale(1); opacity: 1; }
          70%, 100% { transform: scale(2.2); opacity: 0; }
        }
      `}</style>
    </div>
  );
};

export default KnowledgeGraphView;

// ─────────────────────────────────────────────────────────────────────────────
// UTILITY (duplicated from graphMapper to avoid a circular dep)
// ─────────────────────────────────────────────────────────────────────────────
