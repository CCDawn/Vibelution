import { describe, expect, it } from "vitest";
import type { LauncherAssistantDispatch } from "../../../api/launcherAssistant";
import { projectAssistantDispatchTasks } from "./assistantDispatchTasks";

function dispatch(overrides: Partial<LauncherAssistantDispatch> = {}): LauncherAssistantDispatch {
  return { dispatchId: "dispatch-1", projectId: "project-1", agentId: "agent-1", nativeTaskId: "native-1",
    receipt: { taskId: "native-1", status: "running", shouldPoll: true }, ...overrides };
}

describe("assistant task projection from native dispatch receipts", () => {
  it("does not treat native success or a result summary as acceptance of the user's goal", () => {
    const result = projectAssistantDispatchTasks([dispatch({ receipt: {
      taskId: "native-1", status: "succeeded", shouldPoll: false, resultSummary: "所有目标已完成",
    } })]);
    expect(result.tasks[0]).toMatchObject({ state: "awaiting_verification", businessAcceptance: "not_evaluated" });
    expect(result.counts).toMatchObject({ awaitingVerification: 1, inProgress: 0 });
  });

  it("retains a cached task as unknown when the source becomes unavailable", () => {
    const result = projectAssistantDispatchTasks([dispatch()], { sourceAvailable: false });
    expect(result.tasks[0]).toMatchObject({ state: "unknown", nativeStatus: "running", sourceAvailable: false });
    expect(result.counts.inProgress).toBe(0);
  });

  it("does not read a last-known success as current after a receipt query failed", () => {
    const result = projectAssistantDispatchTasks([dispatch({ receipt: { taskId: "native-1", status: "succeeded" },
      lastError: { code: "BACKEND_UNAVAILABLE", message: "暂不可用" } })]);
    expect(result.tasks[0].state).toBe("unknown");
  });

  it("keeps a coded lastError as display evidence only: the task stays unknown, never failed", () => {
    const result = projectAssistantDispatchTasks([dispatch({
      receipt: { taskId: "native-1", status: "failed", error: { code: "TASK_NOT_FOUND", message: "stale receipt" } },
      lastError: { code: "BACKEND_UNAVAILABLE", message: "暂不可用" } })]);
    expect(result.tasks[0]).toMatchObject({ state: "unknown", errorCode: "BACKEND_UNAVAILABLE", sourceAvailable: false, shouldPoll: false });
    expect(result.counts).toMatchObject({ unknown: 1, failed: 0 });
  });

  it("preserves the bound receipt error code on a genuinely failed task", () => {
    const task = projectAssistantDispatchTasks([dispatch({
      receipt: { taskId: "native-1", status: "failed", error: { code: "TURN_FAILED", message: "agent turn failed" } } })]).tasks[0];
    expect(task).toMatchObject({ state: "failed", error: "agent turn failed", errorCode: "TURN_FAILED" });
  });

  it("falls back to an empty code when a legacy receipt error is a plain string", () => {
    const task = projectAssistantDispatchTasks([dispatch({
      receipt: { taskId: "native-1", status: "failed", error: "旧版纯文本失败原因" } })]).tasks[0];
    expect(task).toMatchObject({ state: "failed", error: "旧版纯文本失败原因", errorCode: "" });
  });

  it("ignores empty or oversized error codes without losing the failure message", () => {
    const blank = projectAssistantDispatchTasks([dispatch({
      receipt: { taskId: "native-1", status: "failed", error: { code: "   ", message: "blank code" } } })]).tasks[0];
    const oversized = projectAssistantDispatchTasks([dispatch({
      receipt: { taskId: "native-1", status: "failed", error: { code: "X".repeat(121), message: "huge code" } } })]).tasks[0];
    expect(blank).toMatchObject({ errorCode: "", error: "blank code" });
    expect(oversized).toMatchObject({ errorCode: "", error: "huge code" });
  });

  it.each(["running", "awaiting_approval"])("requires an exact native task binding for approvals in %s", status => {
    const approval = { approvalId: "approval-1", revision: "r1", toolName: "write", risk: "write",
      targetSummary: {}, availableDecisions: ["accept", "decline"] };
    const bound = dispatch({ receipt: { taskId: "native-1", status, pendingApprovals: [approval] } });
    expect(projectAssistantDispatchTasks([bound]).tasks[0]).toMatchObject({ state: "waiting_user", pendingApprovalCount: 1 });
    const mismatched = { ...bound, receipt: { ...bound.receipt, taskId: "another-task" } };
    expect(projectAssistantDispatchTasks([mismatched]).tasks[0]).toMatchObject({ state: "unknown", pendingApprovalCount: 0 });
  });

  it("does not surface cached approvals after the native task has ended", () => {
    const row = dispatch({ receipt: { taskId: "native-1", status: "succeeded", pendingApprovals: [{
      approvalId: "approval-1", revision: "r1", toolName: "write", risk: "write", targetSummary: {}, availableDecisions: ["accept"],
    }] } });
    expect(projectAssistantDispatchTasks([row]).tasks[0]).toMatchObject({ state: "awaiting_verification", pendingApprovalCount: 0 });
  });

  it("keeps the card identity stable while waiting for native admission", () => {
    const pending = dispatch({ nativeTaskId: undefined, receipt: null });
    const before = projectAssistantDispatchTasks([pending]).tasks[0];
    const after = projectAssistantDispatchTasks([dispatch()]).tasks[0];
    expect(before.id).toBe(after.id);
    expect(before).toMatchObject({ state: "unknown", sourceAvailable: true, receiptBound: false });
    expect(after.state).toBe("running");
  });

  it("does not merge tasks from different projects or separator-shaped identities", () => {
    const result = projectAssistantDispatchTasks([
      dispatch(), dispatch({ projectId: "project-2" }),
      dispatch({ projectId: "a:b", dispatchId: "c" }), dispatch({ projectId: "a", dispatchId: "b:c" }),
    ]);
    expect(new Set(result.tasks.map(task => task.id)).size).toBe(4);
  });

  it("deduplicates repeated observations but refuses conflicting observations without ordering evidence", () => {
    const row = dispatch();
    expect(projectAssistantDispatchTasks([row, structuredClone(row)]).tasks).toHaveLength(1);
    const failed = dispatch({ receipt: { taskId: "native-1", status: "failed" } });
    const result = projectAssistantDispatchTasks([row, failed]);
    expect(result.tasks).toHaveLength(1);
    expect(result.tasks[0]).toMatchObject({ state: "unknown", conflictingObservations: true });
  });

  it("preserves unfamiliar owner states as unknown instead of guessing a terminal outcome", () => {
    expect(projectAssistantDispatchTasks([dispatch({ receipt: { taskId: "native-1", status: "new_owner_state" } })])
      .tasks[0]).toMatchObject({ state: "unknown", nativeStatus: "new_owner_state" });
  });

  it("exposes failure and cancellation without inventing replay permission or a successful closure", () => {
    const failed = projectAssistantDispatchTasks([dispatch({ receipt: { taskId: "native-1", status: "failed" } })]).tasks[0];
    const cancelled = projectAssistantDispatchTasks([dispatch({ receipt: { taskId: "native-1", status: "cancelled" } })]).tasks[0];
    expect(failed).toMatchObject({ state: "failed", businessAcceptance: "not_evaluated" });
    expect(cancelled).toMatchObject({ state: "stopped", businessAcceptance: "not_evaluated" });
    expect(failed).not.toHaveProperty("canRetry");
  });

  it("shows a native approval wait without inventing an approvable payload", () => {
    const result = projectAssistantDispatchTasks([dispatch({ receipt: { taskId: "native-1", status: "awaiting_approval" } })]);
    expect(result.tasks[0]).toMatchObject({ state: "waiting_user", pendingApprovalCount: 0 });
  });

  it("distinguishes cancellation in flight from an unconfirmed stop and a cancelled terminal", () => {
    const cancelling = projectAssistantDispatchTasks([dispatch({ receipt: { taskId: "native-1", status: "cancelling" } })]);
    const uncertain = projectAssistantDispatchTasks([dispatch({ receipt: { taskId: "native-1", status: "stop_unconfirmed" } })]);
    expect(cancelling.tasks[0].state).toBe("stopping");
    expect(cancelling.counts.inProgress).toBe(1);
    expect(uncertain.tasks[0].state).toBe("unknown");
  });

  it("does not present a bounded dispatch feed as a complete platform task inventory", () => {
    const result = projectAssistantDispatchTasks([]);
    expect(result).toMatchObject({ coverage: "bounded_dispatches", complete: false, tasks: [] });
  });

  it("distinguishes an unavailable initial feed from an available empty observation", () => {
    expect(projectAssistantDispatchTasks([]).sourceAvailable).toBe(true);
    expect(projectAssistantDispatchTasks([], { sourceAvailable: false }).sourceAvailable).toBe(false);
  });

  it("reports invalid source identities without making an empty scan look complete", () => {
    const result = projectAssistantDispatchTasks([dispatch({ dispatchId: "" }), dispatch({ projectId: undefined })]);
    expect(result.invalidRecords).toBe(1);
    expect(result.tasks[0]).toMatchObject({ state: "unknown", receiptBound: false });
    expect(result.complete).toBe(false);
  });

  it("does not mutate the input or expose the mutable receipt as the task record", () => {
    const row = dispatch();
    const before = structuredClone(row);
    const task = projectAssistantDispatchTasks([row]).tasks[0];
    expect(row).toEqual(before);
    expect(task).not.toHaveProperty("receipt");
    expect(task).not.toHaveProperty("pendingApprovals");
  });

  it("bounds plain-text presentation fields and does not copy an unbound receipt summary", () => {
    const task = projectAssistantDispatchTasks([dispatch({ title: `任务\u202e${"长".repeat(150)}`,
      receipt: { taskId: "native-1", status: "running", resultSummary: `摘要\n${"长".repeat(700)}` } })]).tasks[0];
    expect(Array.from(task.title)).toHaveLength(100);
    expect(task.title).not.toContain("\u202e");
    expect(Array.from(task.resultSummary)).toHaveLength(600);
    expect(task.resultSummary).not.toContain("\n");
    const unbound = projectAssistantDispatchTasks([dispatch({ receipt: { taskId: "another", resultSummary: "wrong task" } })]).tasks[0];
    expect(unbound.resultSummary).toBe("");
  });

  it("only polls explicitly requested known active and bound receipts", () => {
    expect(projectAssistantDispatchTasks([dispatch()]).tasks[0].shouldPoll).toBe(true);
    for (const row of [dispatch({ receipt: { taskId: "native-1", status: "succeeded", shouldPoll: true } }),
      dispatch({ receipt: { taskId: "other", status: "running", shouldPoll: true } }),
      dispatch({ receipt: { taskId: "native-1", status: "new_state", shouldPoll: true } }),
      dispatch({ lastError: { message: "offline" } })]) {
      expect(projectAssistantDispatchTasks([row]).tasks[0].shouldPoll).toBe(false);
    }
    expect(projectAssistantDispatchTasks([dispatch()], { sourceAvailable: false }).tasks[0].shouldPoll).toBe(false);
  });
});
