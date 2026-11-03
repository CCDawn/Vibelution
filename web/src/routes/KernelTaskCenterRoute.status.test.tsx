import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { queryKeys } from "../api/queryKeys";
import type { KernelTask, KernelTaskTimelinePayload } from "../api/types";
import { KernelTaskCenterRoute } from "./KernelTaskCenterRoute";

vi.mock("../i18n/useShellI18n", () => ({ useShellI18n: () => ({ lang: "zh" }) }));

function renderTask(status: string) {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
  const task: KernelTask = {
    taskId: "task-1", creatorEventId: "event-1", idempotencyKey: "fixture", goal: "核验任务状态",
    assignedAgentIds: [], status, workRunId: "run-1", outcomeId: "outcome-1", evidenceRefs: [], createdAt: "", updatedAt: "",
  };
  const timeline: KernelTaskTimelinePayload = {
    taskId: task.taskId, task,
    event: { eventId: "event-1", sender: {}, senderAgentId: "", recipients: [], status, correlationId: "", causationId: "", idempotencyKey: "", semanticPayload: { semanticType: "", payload: {} }, deliveryPolicy: { wakeTarget: false }, metadata: {}, createdAt: "", updatedAt: "" },
    execution: { workRunId: "run-1", taskId: task.taskId, agentId: "", status, startedAt: "", endedAt: "", evidenceRefs: [], deliveryRefs: [], createdAt: "", updatedAt: "" },
    outcome: { outcomeId: "outcome-1", taskId: task.taskId, workRunId: "run-1", agentId: "", status, visibleReply: "", resultSummary: "", proposalRefs: [], evidenceRefs: [], deliveries: [], createdAt: "" },
    deliveries: [], proposals: [], runtimeEvidenceRefs: [], projectionRefs: [],
    timeline: [{ kind: "Task", status, at: "", summary: "状态变化", refs: [] }],
    readModel: { projection: false, factAuthority: true, truthSource: "TaskLedger", generatedAt: "" },
  };
  client.setQueryData(queryKeys.agentSummary(true), []);
  client.setQueryData(queryKeys.kernelTasks("", 120), { tasks: [task], status: "", limit: 120, updatedAt: "" });
  client.setQueryData(queryKeys.kernelTaskTimeline(task.taskId), timeline);
  const markup = renderToStaticMarkup(
    <QueryClientProvider client={client}><MemoryRouter><KernelTaskCenterRoute /></MemoryRouter></QueryClientProvider>,
  );
  client.clear();
  return markup;
}

describe("Kernel task status labels", () => {
  it("keeps blocked distinct from failed in the list, detail and lifecycle", () => {
    const markup = renderTask("blocked");
    expect(markup.match(/>已阻塞</g)?.length ?? 0).toBeGreaterThanOrEqual(3);
    expect(markup).not.toContain(">失败<");
  });

  it("continues to label failed tasks as failed", () => {
    const markup = renderTask("failed");
    expect(markup.match(/>失败</g)?.length ?? 0).toBeGreaterThanOrEqual(3);
    expect(markup).not.toContain(">已阻塞<");
  });
});
