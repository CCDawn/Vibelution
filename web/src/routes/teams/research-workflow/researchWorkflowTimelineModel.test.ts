import { describe, expect, it } from "vitest";

import type { WorkflowEventEnvelope } from "../../../api/types/research-workflow/events";
import { buildResearchTimelineGroups } from "./researchWorkflowTimelineModel";

function event(
  partial: Partial<WorkflowEventEnvelope> & Pick<WorkflowEventEnvelope, "eventId" | "sequence" | "type">,
): WorkflowEventEnvelope {
  return {
    runId: "run-a",
    teamId: "research-team",
    runVersion: 1,
    correlationId: "corr",
    occurredAt: "2026-08-12T14:00:00.000Z",
    payload: {},
    ...partial,
  };
}

describe("researchWorkflowTimelineModel", () => {
  it("groups formal node events by payload.nodeId and uses Chinese labels", () => {
    const groups = buildResearchTimelineGroups([
      event({ eventId: "e1", sequence: 1, type: "run_created" }),
      event({
        eventId: "e2",
        sequence: 2,
        type: "node_starting",
        payload: { nodeId: "source_finding", attempt: 1 },
      }),
    ]);
    expect(groups.map((group) => group.title)).toEqual(["资料寻找 · 第 1 次尝试", "运行治理"]);
    expect(groups[0].items[0].label).toBe("节点启动中");
    expect(groups[1].items[0].label).toBe("运行已创建");
  });

  it("surfaces node_blocked reason in the timeline label", () => {
    const groups = buildResearchTimelineGroups([
      event({
        eventId: "e-block",
        sequence: 3,
        type: "node_blocked",
        payload: {
          nodeId: "source_extraction",
          attempt: 2,
          reason: "检查点仍停留在前驱节点，无法从当前节点恢复。",
        },
      }),
    ]);
    expect(groups[0].title).toBe("资料提炼 · 第 2 次尝试");
    expect(groups[0].items[0].label).toContain("节点已阻塞");
    expect(groups[0].items[0].label).toContain("检查点仍停留在前驱节点");
  });

  it("projects a blocked node into the timeline when events omitted the failure", () => {
    const groups = buildResearchTimelineGroups(
      [
        event({
          eventId: "e-start",
          sequence: 2,
          type: "node_starting",
          payload: { nodeId: "source_extraction", attempt: 2 },
        }),
      ],
      {
        nodeRuns: {
          source_extraction: {
            nodeId: "source_extraction",
            status: "blocked",
            attempt: 2,
          },
        },
        blockedReason: "检查点仍停留在前驱节点，无法从当前节点恢复。",
      },
    );
    const labels = groups.flatMap((group) => group.items.map((item) => item.label));
    expect(labels.some((label) => label.includes("节点已阻塞"))).toBe(true);
    expect(labels.some((label) => label.includes("检查点仍停留在前驱节点"))).toBe(true);
  });

  it("labels revision fork and hypothesis aggregation events with Chinese terms", () => {
    const groups = buildResearchTimelineGroups([
      event({ eventId: "e-fork", sequence: 4, type: "revision_forked" }),
      event({
        eventId: "e-agg",
        sequence: 5,
        type: "workflow.hypothesis_aggregation.completed",
        payload: { nodeId: "hypothesis_integration", attempt: 1 },
      }),
    ]);
    const labels = groups.flatMap((group) => group.items.map((item) => item.label));
    expect(labels).toContain("修订分支已创建");
    expect(labels).toContain("假说聚合已完成");
  });

  it("falls back to the generic label for unknown event types", () => {
    const groups = buildResearchTimelineGroups([
      event({ eventId: "e-future", sequence: 9, type: "workflow.brand_new.future_event" }),
    ]);
    expect(groups).toHaveLength(1);
    expect(groups[0].items[0].label).toBe("运行状态已更新");
  });
});
