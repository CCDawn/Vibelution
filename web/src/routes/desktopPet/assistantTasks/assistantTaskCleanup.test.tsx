// @vitest-environment happy-dom
import React, { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AssistantTask } from "./assistantTeamRunTasks";
import type { LauncherTaskCleanupScope } from "../../../api/launcherAssistantTaskCleanup";
import { useAssistantTaskCleanup } from "./assistantTaskCleanup";

const { cleanupLauncherTasks } = vi.hoisted(() => ({ cleanupLauncherTasks: vi.fn() }));
vi.mock("../../../api/launcherAssistantTaskCleanup", () => ({ cleanupLauncherTasks }));

type CleanupApi = ReturnType<typeof useAssistantTaskCleanup>;
let api: CleanupApi | null = null;
let host: HTMLDivElement, root: Root;

function Probe(options: { agentId: string; sessionId: string; identity: string; canAct: boolean; lang: "zh"; onChanged: () => Promise<unknown> }) {
  api = useAssistantTaskCleanup(options);
  return null;
}

function mount(): CleanupApi {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  act(() => {
    root.render(createElement(Probe, { agentId: "assistant-1", sessionId: "session-1", identity: "assistant-1",
      canAct: true, lang: "zh", onChanged: async () => {} }));
  });
  if (!api) throw new Error("cleanup api not captured");
  return api;
}

function dispatchTask(state: string, index = 0): AssistantTask {
  return { kind: "dispatch", id: `d-${index}`, dispatchId: `dispatch-${index}`, projectId: "project-1",
    agentId: null, nativeTaskId: null, nativeStatus: null, title: "整理资料", resultSummary: "", errorCode: "",
    state, shouldPoll: false, sourceAvailable: true, receiptBound: false, conflictingObservations: false,
    pendingApprovalCount: 0, businessAcceptance: "not_evaluated" } as unknown as AssistantTask;
}

function teamTask(state: string, index = 0): AssistantTask {
  return { kind: "team_run", id: `t-${index}`, projectId: "project-1", requestId: `request-${index}`,
    originAction: "team_run", sourceRefs: [{ requestId: `request-${index}`, originAction: "team_run" as const }],
    teamId: null, flowId: null, runId: null, nativeStatus: null, revision: null, observedAt: null,
    title: "团队运行", lastKnown: null, state, shouldPoll: false, sourceAvailable: true,
    receiptBound: false, conflictingObservations: false, businessAcceptance: "not_evaluated" } as unknown as AssistantTask;
}

function deleted(scope: LauncherTaskCleanupScope) {
  return { schemaVersion: 1 as const, releasedBytes: 0, storageDeltaBytes: 0,
    items: scope.targets.map(target => ({ key: JSON.stringify([target.kind, target.projectId,
      target.kind === "dispatch" ? target.dispatchId : target.originAction,
      target.kind === "team_run" ? target.requestId : null]),
      status: "deleted" as const, releasedBytes: 0, retained: [], failures: [] })) };
}

beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  cleanupLauncherTasks.mockReset();
  cleanupLauncherTasks.mockImplementation(async (scope: LauncherTaskCleanupScope) => deleted(scope));
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

describe("assistant task cleanup scope selection", () => {
  it("degrades an unknown-state task to a record-only removal for a single item", async () => {
    const hook = mount();
    await act(async () => { await hook.open([dispatchTask("unknown")]); });
    expect(cleanupLauncherTasks.mock.calls[0][0].targets).toEqual([
      { kind: "dispatch", projectId: "project-1", dispatchId: "dispatch-0", localOnly: true }]);
  });

  it("applies the same record-only degradation in a bulk run for unknown-state targets", async () => {
    const hook = mount();
    const collect = async () => ({ tasks: [dispatchTask("unknown"), teamTask("unknown")], sourceErrors: [] });
    await act(async () => { await hook.open(collect, true); });
    expect(cleanupLauncherTasks.mock.calls[0][0].targets).toEqual([
      { kind: "dispatch", projectId: "project-1", dispatchId: "dispatch-0", localOnly: true },
      { kind: "team_run", projectId: "project-1", requestId: "request-0", originAction: "team_run", localOnly: true }]);
  });

  it("keeps the strict verified path for ended states in a bulk run", async () => {
    const hook = mount();
    const collect = async () => ({ tasks: [dispatchTask("failed"), teamTask("stopped")], sourceErrors: [] });
    await act(async () => { await hook.open(collect, true); });
    expect(cleanupLauncherTasks.mock.calls[0][0].targets).toEqual([
      { kind: "dispatch", projectId: "project-1", dispatchId: "dispatch-0" },
      { kind: "team_run", projectId: "project-1", requestId: "request-0", originAction: "team_run" }]);
  });
});
