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
});
