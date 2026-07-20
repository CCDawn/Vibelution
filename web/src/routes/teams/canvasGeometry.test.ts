import { describe, expect, it } from "vitest";

import type { TeamCanvasNode } from "../../api/types";
import {
  autoLayoutResearchCanvasNodes,
  canvasViewStyle,
  edgeLine,
  isCommunicationEdge,
  nextNodeId,
  researchCanvasRoleLayer,
} from "./canvasGeometry";

function node(partial: Partial<TeamCanvasNode> & Pick<TeamCanvasNode, "id">): TeamCanvasNode {
  return {
    id: partial.id,
    label: partial.label || partial.id,
    role: partial.role || "",
    purpose: partial.purpose || "",
    agentId: partial.agentId || "",
    x: partial.x ?? 0,
    y: partial.y ?? 0,
    status: partial.status || "ready",
  } as TeamCanvasNode;
}

describe("canvasGeometry", () => {
  it("ranks research canvas roles into stable layers", () => {
    expect(researchCanvasRoleLayer(node({ id: "a", role: "source_finder" }))).toBe(2);
    expect(researchCanvasRoleLayer(node({ id: "b", role: "source_ingestor" }))).toBe(5);
  });

  it("auto-layouts multi-node research canvases without dropping nodes", () => {
    const nodes = [
      node({ id: "lead", role: "research_coordination", x: 10, y: 10 }),
      node({ id: "finder", role: "source_finder", x: 10, y: 10 }),
      node({ id: "extract", role: "source_extractor", x: 10, y: 10 }),
    ];
    const laidOut = autoLayoutResearchCanvasNodes(nodes, [
      { source: "lead", target: "finder", type: "reports_to" },
      { source: "finder", target: "extract", type: "reports_to" },
    ]);
    expect(laidOut).toHaveLength(3);
    expect(new Set(laidOut.map((item) => item.id)).size).toBe(3);
    expect(laidOut.some((item) => item.x !== 10 || item.y !== 10)).toBe(true);
  });

  it("builds viewport CSS variables and edge geometry", () => {
    const nodes = [node({ id: "a", x: 0, y: 0 }), node({ id: "b", x: 240, y: 120 })];
    const style = canvasViewStyle(nodes, { width: 800, height: 600 });
    expect(style["--canvas-scale"]).toBeTruthy();
    expect(isCommunicationEdge({ type: "communication" })).toBe(true);
    const line = edgeLine({ id: "e1", source: "a", target: "b", type: "reports_to" }, nodes);
    expect(line).not.toBeNull();
    expect(nextNodeId(nodes)).toMatch(/^node-/);
  });
});
