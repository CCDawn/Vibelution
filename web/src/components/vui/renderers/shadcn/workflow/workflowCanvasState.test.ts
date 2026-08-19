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
    // Done bucket uses the shared success token and must stay visually
    // distinct from pending across border, accent-bar, and badge channels.
    if (status === "succeeded") {
      expect(visual.toneClass).toContain("state-success");
      expect(visual.borderClass).toContain("state-success");
      expect(visual.badgeClass).toContain("state-success");
      expect(visual.accentBarClass).toContain("state-success");
      const pending = resolveNodeStatusVisual("pending");
      expect(visual.borderClass).not.toBe(pending.borderClass);
      expect(visual.accentBarClass).not.toBe(pending.accentBarClass);
      expect(visual.badgeClass).not.toBe(pending.badgeClass);
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
    expect(resolveEdgeStroke("idle", "rerun").dasharray).toBe("6 4");
  });

  it("colors idle decision branches by outcome and dims them", () => {
    const promote = resolveEdgeStroke("idle", "promote");
    const rollback = resolveEdgeStroke("idle", "rollback");
    const rerun = resolveEdgeStroke("idle", "rerun");
    const stop = resolveEdgeStroke("idle", "stop");
    expect(promote.dasharray).toBeUndefined();
    expect(promote.stroke).toContain("state-success");
    expect(rollback.dasharray).toBe("6 4");
    expect(rollback.stroke).toContain("state-warning");
    expect(rerun.stroke).toContain("accent-cool");
    expect(stop.dasharray).toBe("4 4");
    expect(stop.stroke).toContain("state-error");
    expect(promote.stroke).toContain("42%");
    expect(rerun.stroke).toContain("40%");
  });
});
