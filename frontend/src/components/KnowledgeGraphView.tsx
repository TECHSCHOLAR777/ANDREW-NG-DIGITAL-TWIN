// components/KnowledgeGraphView.tsx
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
  useReactFlow,
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
  KnowledgeNodeData,
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
  const size  = Math.round(40 + data.combinedScore * 40);

  return (
    <div
      style={{
        width:           size,
        height:          size,
        borderRadius:    "50%",
        background:      `radial-gradient(circle at 35% 35%, ${lighten(color, 0.4)}, ${color})`,
        border:          `3px solid ${selected ? "#fff" : lighten(color, 0.5)}`,
        boxShadow:       data.hopDistance === 0
          ? `0 0 24px ${color}99, 0 0 8px ${color}55`
          : selected
          ? `0 0 16px ${color}66`
          : "0 2px 8px rgba(0,0,0,0.3)",
        display:         "flex",
        flexDirection:   "column",
        alignItems:      "center",
        justifyContent:  "center",
        padding:         "4px",
        cursor:          "pointer",
        transition:      "box-shadow 0.2s ease",
        position:        "relative",
      }}
    >
      {/* React Flow handles (invisible, for edge routing) */}
      <Handle type="target" position={Position.Top}    style={{ opacity: 0 }} />
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />

      {/* Node label */}
      <span
        style={{
          fontSize:    Math.max(8, Math.min(11, size / 7)),
          fontWeight:  700,
          color:       "#ffffff",
          textAlign:   "center",
          lineHeight:  1.2,
          maxWidth:    size - 12,
          overflow:    "hidden",
          textOverflow: "ellipsis",
          display:     "-webkit-box",
          WebkitLineClamp: 2,
          WebkitBoxOrient: "vertical",
        }}
      >
        {data.label}
      </span>

      {/* Node type badge */}
      <span
        style={{
          fontSize:       7,
          color:          "rgba(255,255,255,0.7)",
          textTransform:  "uppercase",
          letterSpacing:  "0.05em",
          marginTop:      2,
        }}
      >
        {data.nodeType}
      </span>

      {/* Hop distance indicator (ring for anchor nodes) */}
      {data.hopDistance === 0 && (
        <div
          style={{
            position:     "absolute",
            inset:        -6,
            borderRadius: "50%",
            border:       `2px dashed ${color}`,
            animation:    "spin 8s linear infinite",
            opacity:      0.5,
          }}
        />
      )}
    </div>
  );
};

// ─────────────────────────────────────────────────────────────────────────────
// LEGEND COMPONENT
// ─────────────────────────────────────────────────────────────────────────────

const GraphLegend: React.FC = () => (
  <div
    style={{
      background:   "#FFFFFF",
      border:       "1px solid #E5E7EB",
      borderRadius: 12,
      padding:      "12px 16px",
      boxShadow:    "0 1px 3px rgba(0,0,0,0.05)",
    }}
  >
    <p style={{ color: "#6B7280", fontSize: 11, fontWeight: 500,
                letterSpacing: "0.07em", textTransform: "none",
                marginBottom: 8 }}>
      Node types
    </p>
    {Object.entries(NODE_TYPE_COLORS).map(([type, color]) => (
      <div key={type} style={{ display: "flex", alignItems: "center",
                               gap: 8, marginBottom: 4 }}>
        <div style={{ width: 12, height: 12, borderRadius: "50%",
                      background: color, flexShrink: 0 }} />
        <span style={{ color: "#111827", fontSize: 10 }}>{type}</span>
      </div>
    ))}
    <p style={{ color: "#6B7280", fontSize: 11, fontWeight: 500,
                letterSpacing: "0.07em", textTransform: "none",
                margin: "12px 0 8px" }}>
      Edge types
    </p>
    {Object.entries(PREDICATE_COLORS).slice(0, 5).map(([pred, color]) => (
      <div key={pred} style={{ display: "flex", alignItems: "center",
                               gap: 8, marginBottom: 4 }}>
        <div style={{ width: 20, height: 2, background: color, flexShrink: 0 }} />
        <span style={{ color: "#111827", fontSize: 10 }}>
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
  node:     KnowledgeNode | null;
  onClose:  () => void;
  onExplore?: (label: string) => void;
}

const NodeDetailPanel: React.FC<NodeDetailProps> = ({ node, onClose, onExplore }) => {
  if (!node) return null;
  const color = NODE_TYPE_COLORS[node.data.nodeType];

  return (
    <div
      style={{
        background:    "#FFFFFF",
        border:        `1px solid #E5E7EB`,
        borderRadius:  12,
        padding:       "16px 20px",
        minWidth:      220,
        boxShadow:     `0 4px 12px rgba(0,0,0,0.05)`,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between",
                    alignItems: "flex-start", marginBottom: 12 }}>
        <div>
          <p style={{ color: "#111827", fontWeight: 500, fontSize: 14,
                      marginBottom: 2 }}>
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
          style={{ background: "none", border: "none", color: "#64748b",
                   cursor: "pointer", fontSize: 16, padding: 0 }}
        >
          ×
        </button>
      </div>

      <div style={{ marginBottom: 8 }}>
        <p style={{ color: "#6B7280", fontSize: 11, fontWeight: 500,
                    letterSpacing: "0.07em", textTransform: "none", marginBottom: 4 }}>
          Relevance score
        </p>
        <div style={{ background: "#F3F4F6", borderRadius: 4, height: 6 }}>
          <div style={{
            width:        `${Math.round(node.data.combinedScore * 100)}%`,
            height:       "100%",
            background:   color,
            borderRadius: 4,
            transition:   "width 0.5s ease",
          }} />
        </div>
        <p style={{ color: "#9CA3AF", fontSize: 11, marginTop: 2 }}>
          {(node.data.combinedScore * 100).toFixed(0)}% · Hop {node.data.hopDistance}
        </p>
      </div>

      {node.data.predicates.length > 0 && (
        <div style={{ marginBottom: 4 }}>
          <p style={{ color: "#6B7280", fontSize: 11, fontWeight: 500,
                      letterSpacing: "0.07em", textTransform: "none", marginBottom: 4 }}>
            Relationships
          </p>
          {node.data.predicates.map((p, i) => (
            <span
              key={i}
              style={{
                display:      "inline-block",
                background:   (PREDICATE_COLORS[p] ?? "#64748b") + "15",
                color:        PREDICATE_COLORS[p] ?? "#6B7280",
                borderRadius: 4,
                padding:      "2px 8px",
                fontSize:     10,
                margin:       "2px",
                border:       `1px solid ${(PREDICATE_COLORS[p] ?? "#64748b")}25`,
              }}
            >
              {p.replace(/_/g, " ")}
            </span>
          ))}
        </div>
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
            padding: "8px 12px",
            background: "#1A56DB",
            border: "1px solid #1A56DB",
            borderRadius: 8,
            color: "#FFFFFF",
            fontSize: 12,
            fontWeight: 500,
            cursor: "pointer",
            transition: "all 0.2s ease",
            textAlign: "center",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = "#1A56DBE0";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = "#1A56DB";
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
    if (triplets.length === 0) return;

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
        background: "#FFFFFF",
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
          <div style={{ color: "#1A56DB", fontSize: 14, fontWeight: 500 }}>
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
            color:     "#6B7280",
          }}
        >
          <svg className="w-12 h-12 text-slate-300 mb-3" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
            <circle cx="32" cy="18" r="4" fill="#9CA3AF" />
            <circle cx="16" cy="42" r="4" fill="#E5E7EB" stroke="#9CA3AF" strokeWidth="2" />
            <circle cx="48" cy="42" r="4" fill="#E5E7EB" stroke="#9CA3AF" strokeWidth="2" />
            <line x1="29.5" y1="21.5" x2="18.5" y2="38.5" stroke="#9CA3AF" strokeWidth="2" strokeDasharray="3 3" />
            <line x1="34.5" y1="21.5" x2="45.5" y2="38.5" stroke="#9CA3AF" strokeWidth="2" strokeDasharray="3 3" />
            <line x1="20" y1="42" x2="44" y2="42" stroke="#E5E7EB" strokeWidth="2" />
          </svg>
          <p style={{ fontSize: 13, fontWeight: 500, color: "#111827" }}>
            Start a conversation to build your learning map
          </p>
          <p style={{ fontSize: 11, color: "#9CA3AF", marginTop: 4 }}>
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
          color="#E5E7EB"
        />
        <Controls
          style={{
            background: "#FFFFFF",
            border:     "1px solid #E5E7EB",
            borderRadius: 8,
          }}
        />
        {nodes.length > 0 && (
          <MiniMap
            style={{
              background: "#FFFFFF",
              border:     "1px solid #E5E7EB",
            }}
            nodeColor={(n: KnowledgeNode) =>
              NODE_TYPE_COLORS[n.data?.nodeType] ?? "#9CA3AF"
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
              onClose={() => setSelectedNode(null)}
              onExplore={onExploreNode}
            />
          </Panel>
        )}


        {/* Node count badge */}
        <Panel position="bottom-left">
          <div
            style={{
              background:   "#FFFFFF",
              border:       "1px solid #E5E7EB",
              borderRadius: 8,
              padding:      "4px 12px",
              color:        "#6B7280",
              fontSize:     11,
            }}
          >
            {nodes.length} concepts · {rfEdges.length} relations
          </div>
        </Panel>
      </ReactFlow>

      {/* Spinning animation keyframe (injected once) */}
      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to   { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
};

export default KnowledgeGraphView;

// ─────────────────────────────────────────────────────────────────────────────
// UTILITY (duplicated from graphMapper to avoid a circular dep)
// ─────────────────────────────────────────────────────────────────────────────
function lighten(hex: string, factor: number): string {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  const lerp = (v: number) => Math.min(255, Math.round(v + (255 - v) * factor));
  return `#${lerp(r).toString(16).padStart(2, "0")}${
    lerp(g).toString(16).padStart(2, "0")
  }${lerp(b).toString(16).padStart(2, "0")}`;
}
