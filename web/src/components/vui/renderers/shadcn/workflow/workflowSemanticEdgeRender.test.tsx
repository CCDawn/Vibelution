/**
 * P1-3 edge-render contracts (M level, static markup).
 *
 * Renders WorkflowSemanticEdge via renderToStaticMarkup with a mocked
 * @xyflow/react (BaseEdge/EdgeLabelRenderer stubbed) — no DOM measurement.
 * Asserts the edge render contract:
 *  - engine-owned ORTHOGONAL section geometry becomes the exact SVG path;
 *  - path-state stroke color / dash / animation class;
 *  - labels render only for always-visible, active/attention edges;
 *  - markerEnd and interaction width reach BaseEdge.
 */
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { EdgeProps } from "@xyflow/react";

type BaseEdgeStub = {
  id?: string;
  path?: string;
  markerEnd?: unknown;
  style?: Record<string, unknown>;
  className?: string;
  interactionWidth?: number;
  "data-section-fault"?: string;
  "data-label-fault"?: string;
  "data-manual-route"?: string;
  "data-smart-route"?: string;
};

const baseEdgeCalls: BaseEdgeStub[] = vi.hoisted(() => []);
const useSmartEdgePathMock = vi.hoisted(() => vi.fn(() => ({
  route: null,
  isDragging: false,
  hasProvider: true,
})));

vi.mock("@tisoap/react-flow-smart-edge", () => ({
  useSmartEdgePath: useSmartEdgePathMock,
}));

vi.mock("@xyflow/react", async () => {
  const React = (await import("react")).default;
  return {
    BaseEdge: (props: BaseEdgeStub) => {
      baseEdgeCalls.push(props);
      return React.createElement("g", { "data-base-edge": "true" });
    },
    EdgeLabelRenderer: ({ children }: { children: React.ReactNode }) =>
      React.createElement("g", { "data-label-renderer": "true" }, children),
  };
});

import { WorkflowSemanticEdge, type WorkflowSemanticEdgeData } from "./WorkflowSemanticEdge";
import { resolveEdgeStroke } from "./workflowCanvasState";
import type { WorkflowEdgeSection } from "../../../product/workflow/workflowCanvasTypes";

const sections: WorkflowEdgeSection[] = [
  {
    id: "s1",
    start: { x: 10, y: 20 },
    end: { x: 60, y: 20 },
    bendPoints: [],
    incomingSectionIds: [],
    outgoingSectionIds: ["s2"],
  },
  {
    id: "s2",
    start: { x: 60, y: 20 },
    end: { x: 120, y: 90 },
    bendPoints: [{ x: 90, y: 90 }],
    incomingSectionIds: ["s1"],
    outgoingSectionIds: [],
  },
];

function renderEdge(
  data: Partial<WorkflowSemanticEdgeData>,
  extra: Partial<EdgeProps> = {},
): string {
  baseEdgeCalls.length = 0;
  const props = {
    id: "e1",
    source: "a",
    target: "b",
    sourceX: 0,
    sourceY: 0,
    targetX: 0,
    targetY: 50,
    sourcePosition: "left" as never,
    targetPosition: "right" as never,
    data,
    ...extra,
  } as EdgeProps & { data: WorkflowSemanticEdgeData };
  return renderToStaticMarkup(<WorkflowSemanticEdge {...props} />);
}

describe("WorkflowSemanticEdge render (P1-3)", () => {
  beforeEach(() => {
    useSmartEdgePathMock.mockReturnValue({ route: null, isDragging: false, hasProvider: true });
  });
  it("emits the engine-owned orthogonal path exactly, with marker and hit width", () => {
    renderEdge({ sections });
    const call = baseEdgeCalls[0];
    expect(call).toBeDefined();
    expect(call.path).toBe("M 10 20 L 60 20 L 90 90 L 120 90");
    expect(call.id).toBe("e1");
    expect(call.interactionWidth).toBe(20);
  });

  it("switches to a live orthogonal route and midpoint label after a manual move", () => {
    const markup = renderEdge(
      {
        sections,
        label: "人工确认",
        labelAlwaysVisible: true,
        semanticKind: "human_gate",
        gateKind: "knowledge_package",
        pathState: "idle",
        manualRouteActive: true,
      },
      { sourceX: 10, sourceY: 20, targetX: 130, targetY: 80 },
    );
    expect(baseEdgeCalls[0]?.path).toBe("M 10 20 L -22 20 L 70 20 L 70 80 L 162 80 L 130 80");
    expect(baseEdgeCalls[0]?.["data-manual-route"]).toBe("true");
    expect(baseEdgeCalls[0]?.["data-label-fault"]).toBeUndefined();
    expect(markup).toContain('translate(70px,50px)');
  });

  it("uses the settled smart route but keeps the local route while dragging", () => {
    useSmartEdgePathMock.mockReturnValue({
      route: {
        kind: "routed",
        wasRouted: true,
        svgPathString: "M 10 20 L 42 20 L 42 120 L 98 120 L 98 80 L 130 80",
        edgeCenterX: 70,
        edgeCenterY: 120,
        points: [],
      },
      isDragging: false,
      hasProvider: true,
    });
    renderEdge({ sections, manualRouteActive: true });
    expect(baseEdgeCalls[0]?.path).toContain("L 42 120");
    expect(baseEdgeCalls[0]?.["data-smart-route"]).toBe("true");

    renderEdge({ sections, manualRouteActive: true, manualDragging: true });
    expect(baseEdgeCalls[0]?.path).not.toContain("L 42 120");
    expect(baseEdgeCalls[0]?.["data-smart-route"]).toBeUndefined();
  });

  it("uses dashed semantic colors for idle rerun/revise/rollback instead of a shared grey", () => {
    renderEdge({ sections, semanticKind: "rerun", pathState: "idle" });
    const { stroke, dasharray } = resolveEdgeStroke("idle", "rerun");
    expect(baseEdgeCalls[0]?.style?.stroke).toBe(stroke);
    expect(baseEdgeCalls[0]?.style?.strokeDasharray).toBe(dasharray);
    expect(dasharray).toBe("6 4");
    expect(stroke).toContain("accent-cool");
    expect(stroke).toContain("40%");
  });

  it("renders Knowledge Package as a short Chinese pill on an opaque workspace halo", () => {
    const markup = renderEdge({
      sections,
      label: "Knowledge Package",
      labelAlwaysVisible: true,
      labelBounds: { x: 40, y: 10, width: 45, height: 20 },
      pathState: "idle",
      semanticKind: "human_gate",
      gateKind: "knowledge_package",
    });
    expect(markup).toContain('data-vui="workflow-edge-label"');
    expect(markup).toContain("知识包");
    expect(markup).toContain('title="Knowledge Package"');
    expect(markup).not.toContain("Knowledge Pa…");
    expect(markup).toContain("var(--vui-surface-panel)");
    expect(markup).toContain("var(--vui-surface-workspace)");
  });

  it("marks active edges animated and colored with accent-cool", () => {
    renderEdge({ sections, pathState: "active", semanticKind: "main" });
    const { stroke } = resolveEdgeStroke("active", "main");
    expect(baseEdgeCalls[0]?.style?.stroke).toBe(stroke);
    expect(baseEdgeCalls[0]?.className).toBe("workflow-edge-active");
  });

  it("does not render a label for idle auto edges without always-visible", () => {
    const markup = renderEdge({ sections, label: "交接", pathState: "idle", semanticKind: "main" });
    expect(markup).not.toContain('data-vui="workflow-edge-label"');
  });

  it("renders the label for active edges even when always-visible is off", () => {
    const markup = renderEdge({
      sections,
      label: "交接",
      labelBounds: { x: 40, y: 10, width: 40, height: 12 },
      pathState: "active",
      semanticKind: "main",
    });
    expect(markup).toContain('data-vui="workflow-edge-label"');
    expect(markup).toContain("交接");
    expect(markup).toContain('data-path-state="active"');
    expect(markup).toContain("width:34px");
    expect(markup).toContain("height:20px");
  });

  it("always renders a semantic handoff label", () => {
    const markup = renderEdge({
      sections,
      label: "人工确认",
      labelAlwaysVisible: true,
      labelBounds: { x: 40, y: 10, width: 40, height: 12 },
      pathState: "idle",
      semanticKind: "human_gate",
      gateKind: "knowledge_package",
    });
    expect(markup).toContain('data-vui="workflow-edge-label"');
    expect(markup).toContain("人工确认");
  });

  it("hides routine human-edge labels until hover or attention", () => {
    const markup = renderEdge({
      sections,
      label: "评审通过",
      labelAlwaysVisible: true,
      labelBounds: { x: 40, y: 10, width: 40, height: 12 },
      pathState: "idle",
      semanticKind: "human_gate",
      gateKind: "human",
    });
    expect(markup).not.toContain('data-vui="workflow-edge-label"');
    expect(markup).not.toContain("评审通过");
  });

  it("never renders a label when the engine did not place labelBounds (P1-2)", () => {
    const markup = renderEdge({
      sections,
      label: "无锚点",
      labelBounds: undefined,
      labelAlwaysVisible: true,
      pathState: "active",
      semanticKind: "main",
    });
    expect(markup).not.toContain('data-vui="workflow-edge-label"');
    expect(markup).not.toContain("无锚点");
  });

  it("flags a missing engine label bounds on the DOM (P1-5)", () => {
    renderEdge({
      sections,
      label: "无锚点",
      labelBounds: undefined,
      labelAlwaysVisible: true,
      pathState: "active",
      semanticKind: "main",
    });
    expect(baseEdgeCalls[0]?.["data-label-fault"]).toBe("true");
  });

  it("flags a broken section chain on the DOM (P1-3)", () => {
    const broken: WorkflowEdgeSection[] = [
      { id: "s1", start: { x: 0, y: 0 }, end: { x: 30, y: 0 }, bendPoints: [], incomingSectionIds: [], outgoingSectionIds: ["s2"] },
      { id: "s2", start: { x: 31, y: 5 }, end: { x: 60, y: 5 }, bendPoints: [], incomingSectionIds: ["s1"], outgoingSectionIds: [] },
    ];
    renderEdge({ sections: broken, label: "", semanticKind: "main", pathState: "idle" });
    expect(baseEdgeCalls[0]?.["data-section-fault"]).toBe("true");
  });

  it("stays clean on well-formed engine sections (P1-3)", () => {
    renderEdge({ sections, label: "", semanticKind: "main", pathState: "idle" });
    expect(baseEdgeCalls[0]?.["data-section-fault"]).toBeUndefined();
    expect(baseEdgeCalls[0]?.["data-label-fault"]).toBeUndefined();
  });
});
