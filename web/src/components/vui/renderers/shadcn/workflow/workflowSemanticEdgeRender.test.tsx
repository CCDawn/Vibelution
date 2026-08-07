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
import { describe, expect, it, vi } from "vitest";
import type { EdgeProps } from "@xyflow/react";

type BaseEdgeStub = {
  id?: string;
  path?: string;
  markerEnd?: unknown;
  style?: Record<string, unknown>;
  className?: string;
  interactionWidth?: number;
};

const baseEdgeCalls: BaseEdgeStub[] = vi.hoisted(() => []);

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
    incomingSections: [],
    outgoingSections: [],
  },
  {
    id: "s2",
    start: { x: 60, y: 20 },
    end: { x: 120, y: 90 },
    bendPoints: [{ x: 90, y: 90 }],
    incomingSections: [],
    outgoingSections: [],
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
  it("emits the engine-owned orthogonal path exactly, with marker and hit width", () => {
    renderEdge({ sections });
    const call = baseEdgeCalls[0];
    expect(call).toBeDefined();
    expect(call.path).toBe("M 10 20 L 60 20 M 60 20 L 90 90 L 120 90");
    expect(call.id).toBe("e1");
    expect(call.interactionWidth).toBe(20);
  });

  it("uses dashed muted stroke for rerun/revise/rollback semantic kinds", () => {
    renderEdge({ sections, semanticKind: "rerun", pathState: "idle" });
    const { stroke, dasharray } = resolveEdgeStroke("idle", "rerun");
    expect(baseEdgeCalls[0]?.style?.stroke).toBe(stroke);
    expect(baseEdgeCalls[0]?.style?.strokeDasharray).toBe(dasharray);
    expect(dasharray).toBe("6 4");
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
      pathState: "active",
      semanticKind: "main",
    });
    expect(markup).toContain('data-vui="workflow-edge-label"');
    expect(markup).toContain("交接");
    expect(markup).toContain('data-path-state="active"');
  });

  it("always renders the label when labelAlwaysVisible is set", () => {
    const markup = renderEdge({
      sections,
      label: "人工确认",
      labelAlwaysVisible: true,
      pathState: "idle",
      semanticKind: "human_gate",
    });
    expect(markup).toContain('data-vui="workflow-edge-label"');
    expect(markup).toContain("人工确认");
  });
});
