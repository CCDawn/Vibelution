import { describe, expect, it } from "vitest";

import type { WorkflowNodeRunStatus } from "../../../product/workflow/workflowCanvasTypes";
import { nodeStatusLabel, resolveEdgeStroke, resolveNodeStatusVisual } from "./workflowCanvasState";
import { workflowNodeAriaLabel } from "./workflowCanvasAccessibility";

const ALL_STATUSES: WorkflowNodeRunStatus[] = [
  "pending",
  "ready",
  "running",
  "waiting_human",
  "succeeded",
  "failed",
  "blocked",
  "skipped",
  "stale",
  "cancelled",
];

describe("workflowCanvasState visuals", () => {
  it.each(ALL_STATUSES)("maps status %s to icon + label + classes", (status) => {
    const visual = resolveNodeStatusVisual(status);
    expect(visual.status).toBe(status);
    expect(visual.statusLabel).toBe(nodeStatusLabel(status));
    expect(visual.icon).toBeTruthy();
    expect(visual.borderClass).toBeTruthy();
    expect(visual.textClass).toBeTruthy();
    // Success must not use green success token as primary tone.
    if (status === "succeeded") {
      expect(visual.toneClass).not.toMatch(/state-success|green/);
      expect(visual.borderClass).not.toMatch(/state-success|green/);
    }
  });

  it("distinguishes blocked icon from failed icon", () => {
    expect(resolveNodeStatusVisual("blocked").icon).toBe("ban");
    expect(resolveNodeStatusVisual("failed").icon).toBe("x");
  });

  it("builds aria-label with type and status", () => {
    const label = workflowNodeAriaLabel({
      label: "协议冻结",
      visualKind: "human_gate",
      status: "waiting_human",
      isRuntimeCurrent: true,
      primaryAgentId: "agent-a",
      attempt: 2,
    });
    expect(label).toContain("协议冻结");
    expect(label).toContain("人工门禁");
    expect(label).toContain("等待人工");
    expect(label).toContain("运行当前");
  });

  it("uses system blue for active edges and warning for attention", () => {
    expect(resolveEdgeStroke("active", "main").stroke).toContain("accent-cool");
    expect(resolveEdgeStroke("attention", "human_gate").stroke).toContain("state-warning");
    expect(resolveEdgeStroke("danger", "main").stroke).toContain("state-error");
    expect(resolveEdgeStroke("idle", "rerun").dasharray).toBeTruthy();
  });
});
