import { describe, expect, it } from "vitest";

import type { TeamCanvasNode } from "../../api/types";
import {
  autoLayoutResearchCanvasNodes,
  canvasViewStyle,
  canvasStyleScale,
  CANVAS_MAX_ZOOM,
  CANVAS_MIN_ZOOM,
  panCanvasViewport,
  zoomCanvasViewport,
  edgeLine,
  isCommunicationEdge,
  nextNodeId,
  NODE_HEIGHT,
  NODE_WIDTH,
  resolveCanvasFrameSize,
  RESEARCH_CANVAS_AUTO_LAYOUT_ROW_GAP,
  researchCanvasRoleLayer,
} from "./canvasGeometry";
import { applyNodeDragDeltas } from "./teamCanvasNodeModel";

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
  it("pans in screen pixels and zooms around the same world point without changing its input", () => {
    const view = { "--canvas-offset-x": "-30px", "--canvas-offset-y": "80px", "--canvas-scale": "0.5" };
    const moved = panCanvasViewport(view, { x: 45, y: -25 });
    expect(moved).toEqual({ "--canvas-offset-x": "15px", "--canvas-offset-y": "55px", "--canvas-scale": "0.5" });
    const anchor = { x: 180, y: 120 };
    const zoomed = zoomCanvasViewport(moved, 0.75, anchor);
    for (const axis of ["x", "y"] as const) {
      expect((anchor[axis] - parseFloat(zoomed[`--canvas-offset-${axis}`])) / canvasStyleScale(zoomed))
        .toBeCloseTo((anchor[axis] - parseFloat(moved[`--canvas-offset-${axis}`])) / canvasStyleScale(moved));
    }
    expect(view).toEqual({ "--canvas-offset-x": "-30px", "--canvas-offset-y": "80px", "--canvas-scale": "0.5" });
  });

  it("bounds manual zoom while preserving fit-all scales below the manual floor", () => {
    const view = canvasViewStyle([node({ id: "a" })]);
    expect(canvasStyleScale(zoomCanvasViewport(view, 100, { x: 0, y: 0 }))).toBe(CANVAS_MAX_ZOOM);
    expect(canvasStyleScale(zoomCanvasViewport(view, 0, { x: 0, y: 0 }))).toBe(CANVAS_MIN_ZOOM);
    expect(canvasStyleScale(zoomCanvasViewport(view, Number.NaN, { x: 0, y: 0 }))).toBe(1);
    const tinyFit = { ...view, "--canvas-scale": "0.02" };
    expect(canvasStyleScale(zoomCanvasViewport(tinyFit, 0.01, { x: 0, y: 0 }))).toBe(0.02);
    expect(canvasStyleScale(zoomCanvasViewport(tinyFit, 0.024, { x: 0, y: 0 }))).toBe(0.024);
  });
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

  it("keeps the auto-layout row gap larger than the node card height", () => {
    expect(RESEARCH_CANVAS_AUTO_LAYOUT_ROW_GAP).toBeGreaterThan(NODE_HEIGHT);
  });

  it.each([
    { width: 280, height: 240 },
    { width: 390, height: 300 },
    { width: 1100, height: 650 },
  ])("fits distant and negative nodes inside a measured $width by $height frame", (frame) => {
    const nodes = [node({ id: "a", x: -200, y: -140 }), node({ id: "b", x: 2200, y: 1100 })];
    const before = structuredClone(nodes);
    const view = canvasViewStyle(nodes, frame);
    const scale = canvasStyleScale(view);
    const offsetX = parseFloat(view["--canvas-offset-x"]);
    const offsetY = parseFloat(view["--canvas-offset-y"]);
    expect(scale).toBeLessThan(0.58);
    for (const item of nodes) {
      expect(offsetX + item.x * scale).toBeGreaterThanOrEqual(24 - 0.001);
      expect(offsetX + (item.x + NODE_WIDTH) * scale).toBeLessThanOrEqual(frame.width - 24 + 0.001);
      expect(offsetY + item.y * scale).toBeGreaterThanOrEqual(24 - 0.001);
      expect(offsetY + (item.y + NODE_HEIGHT) * scale).toBeLessThanOrEqual(frame.height - 64 + 0.001);
    }
    expect(nodes).toEqual(before);
  });

  it("uses minimum frame dimensions only before a valid measurement", () => {
    expect(resolveCanvasFrameSize()).toEqual({ width: 420, height: 360 });
    expect(resolveCanvasFrameSize({ width: 0, height: Number.NaN })).toEqual({ width: 420, height: 360 });
    expect(resolveCanvasFrameSize({ width: 215, height: 190 })).toEqual({ width: 215, height: 190 });
  });

  it("does not enlarge a small graph and supports 100% and focusing without rewriting nodes", () => {
    const nodes = [node({ id: "a", x: 200, y: 400 }), node({ id: "b", x: 1600, y: 400 })];
    const frame = { width: 600, height: 400 };
    expect(canvasStyleScale(canvasViewStyle([nodes[0]], frame))).toBe(1);
    expect(canvasStyleScale(canvasViewStyle(nodes, frame, { scale: 1 }))).toBe(1);
    const view = canvasViewStyle(nodes, frame, { scale: 0.8, selectedNodeId: "b" });
    expect(parseFloat(view["--canvas-offset-x"]) + (nodes[1].x + NODE_WIDTH / 2) * 0.8).toBeCloseTo(frame.width / 2);
    expect(parseFloat(view["--canvas-offset-y"]) + (nodes[1].y + NODE_HEIGHT / 2) * 0.8).toBeCloseTo((frame.height - 40) / 2);
  });

  it("maps pointer movement back to saved coordinates at the fitted narrow-frame scale", () => {
    const nodes = [node({ id: "a", x: 100, y: 100 }), node({ id: "b", x: 1800, y: 900 })];
    const scale = canvasStyleScale(canvasViewStyle(nodes, { width: 280, height: 240 }));
    const delta = applyNodeDragDeltas({
      startX: 100, startY: 100, startClientX: 40, startClientY: 50,
      clientX: 40 + 120 * scale, clientY: 50 + 80 * scale, scale,
    });
    expect(delta).toEqual({ x: 220, y: 180, moved: true });
    expect(edgeLine({ source: "a", target: "b" }, nodes)?.x1).toBeGreaterThan(nodes[0].x);
  });
});
