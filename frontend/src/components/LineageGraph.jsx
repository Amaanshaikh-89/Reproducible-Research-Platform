import React from "react";

const NODE_TYPES = [
  { type: "dataset", label: "DATASET" },
  { type: "code", label: "CODE" },
  { type: "experiment", label: "EXPERIMENT" },
  { type: "run", label: "RUN" },
  { type: "artifact", label: "ARTIFACT" },
];

const NODE_WIDTH = 184;
const NODE_HEIGHT = 72;
const COLUMN_GAP = 76;
const ROW_GAP = 104;
const PADDING = 28;
const LABEL_LENGTH = 24;

function wrapLabel(value) {
  const words = String(value || "Untitled").split(/\s+/);
  const lines = [];
  let line = "";
  words.forEach((word) => {
    const candidate = line ? `${line} ${word}` : word;
    if (candidate.length > LABEL_LENGTH && line) {
      lines.push(line);
      line = word;
    } else {
      line = candidate;
    }
  });
  if (line) lines.push(line);
  if (lines.length > 2) {
    lines.length = 2;
    lines[1] = `${lines[1].slice(0, LABEL_LENGTH - 1)}…`;
  }
  return lines;
}

function runLabel(node) {
  const match = String(node.label || "").match(/^(.*)\s+\((succeeded|failed|running)\)$/i);
  return match
    ? { title: match[1], status: match[2] }
    : { title: node.label || node.id, status: node.status || "" };
}

export default function LineageGraph({
  lineage,
  loading = false,
  error = "",
  onSelectNode,
  onPreviewArtifact,
}) {
  if (error) {
    return <div className="empty error-text" role="alert">Could not load lineage: {error}</div>;
  }
  if (loading) return <div className="empty" role="status">Loading lineage graph…</div>;
  if (!lineage?.nodes?.length) {
    return <div className="empty">No lineage nodes are available for this experiment yet.</div>;
  }

  const nodesByType = Object.fromEntries(
    NODE_TYPES.map(({ type }) => [type, lineage.nodes.filter((node) => node.type === type)])
  );
  const positions = new Map();
  NODE_TYPES.forEach(({ type }, column) => {
    nodesByType[type].forEach((node, row) => {
      positions.set(node.id, {
        x: PADDING + column * (NODE_WIDTH + COLUMN_GAP),
        y: PADDING + row * ROW_GAP,
      });
    });
  });
  const maxRows = Math.max(1, ...NODE_TYPES.map(({ type }) => nodesByType[type].length));
  const graphWidth = PADDING * 2 + NODE_TYPES.length * NODE_WIDTH + (NODE_TYPES.length - 1) * COLUMN_GAP;
  const graphHeight = PADDING * 2 + (maxRows - 1) * ROW_GAP + NODE_HEIGHT;
  const edges = (lineage.edges || []).filter((edge) => positions.has(edge.source) && positions.has(edge.target));

  function activateNode(node) {
    if (node.type === "artifact") onPreviewArtifact?.(node);
    else onSelectNode?.(node);
  }

  return (
    <div className="lineage-visualization">
      <div className="lineage-scroll" role="region" aria-label="Experiment lineage graph" tabIndex="0">
        <svg
          className="lineage-svg"
          width={graphWidth}
          height={graphHeight}
          viewBox={`0 0 ${graphWidth} ${graphHeight}`}
          role="group"
          aria-label={`${lineage.nodes.length} lineage nodes and ${edges.length} directed relationships`}
        >
          <defs>
            <marker id="lineage-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="strokeWidth">
              <path d="M 0 0 L 8 4 L 0 8 z" className="lineage-arrowhead" />
            </marker>
          </defs>
          {NODE_TYPES.map(({ type, label }, index) => (
            <text key={type} x={PADDING + index * (NODE_WIDTH + COLUMN_GAP)} y={17} className="lineage-lane-label">
              {label}
            </text>
          ))}
          <g aria-label="Lineage relationships">
            {edges.map((edge, index) => {
              const source = positions.get(edge.source);
              const target = positions.get(edge.target);
              const x1 = source.x + NODE_WIDTH;
              const y1 = source.y + NODE_HEIGHT / 2;
              const x2 = target.x;
              const y2 = target.y + NODE_HEIGHT / 2;
              const bend = Math.max(24, (x2 - x1) * 0.45);
              return (
                <path
                  key={`${edge.source}-${edge.target}-${index}`}
                  d={`M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`}
                  className="lineage-edge"
                  markerEnd="url(#lineage-arrow)"
                />
              );
            })}
          </g>
          <g aria-label="Lineage nodes">
            {NODE_TYPES.flatMap(({ type }) => nodesByType[type].map((node) => {
              const position = positions.get(node.id);
              const run = type === "run" ? runLabel(node) : null;
              const lines = wrapLabel(run?.title ?? node.label ?? node.id);
              const isArtifact = type === "artifact";
              const relationId = node.run_id ?? node.experiment_id ?? node.artifact_id ?? "unavailable";
              return (
                <g
                  key={node.id}
                  className={`lineage-node node-${type} lineage-node-clickable`}
                  transform={`translate(${position.x} ${position.y})`}
                  role="button"
                  tabIndex={0}
                  aria-label={`${type}: ${node.label || node.id}; related ID ${relationId}`}
                  onClick={() => activateNode(node)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      activateNode(node);
                    }
                  }}
                >
                  <rect width={NODE_WIDTH} height={NODE_HEIGHT} rx="9" />
                  <text x="13" y={lines.length > 1 ? "27" : "34"} className="lineage-node-title">
                    {lines.map((line, index) => <tspan key={index} x="13" dy={index === 0 ? 0 : 16}>{line}</tspan>)}
                  </text>
                  {type === "run" && run?.status && (
                    <text x="13" y="60" className={`lineage-run-status status-${run.status.toLowerCase()}`}>
                      {run.status.toUpperCase()}
                    </text>
                  )}
                  {type !== "run" && (
                    <text x="13" y="57" className="lineage-node-kind">
                      {type === "experiment" ? "RESEARCH EXPERIMENT" : `${type.toUpperCase()} INPUT / OUTPUT`}
                    </text>
                  )}
                </g>
              );
            }))}
          </g>
        </svg>
      </div>
      <div className="lineage-footnote">
        {lineage.nodes.length} nodes · {edges.length} directed relationships · arrows show data flow
      </div>
    </div>
  );
}
