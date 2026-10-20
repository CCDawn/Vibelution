import { describe, expect, it, vi } from "vitest";
import type { CommandOffer } from "../../api/types/research-workflow/commands";
import { findHumanGateOffer, humanGateScopeFor, submitHumanGateDecision } from "./humanGateDecision";
import type { HumanAttentionNotificationPayload } from "./humanAttentionNotifications";

function payload(patch: Partial<HumanAttentionNotificationPayload>): HumanAttentionNotificationPayload {
  return {
    id: "gate-1",
    kind: "human_gate",
    severity: "high",
    title: "等待人工审批",
    meta: { teamId: "team-1", runId: "run-7", nodeId: "node-gate", taskId: "task-9" },
    ...patch,
  };
}

function offer(patch: Partial<CommandOffer> & { expectedRunVersion: number; idempotencyKey: string }): CommandOffer {
  return {
    command: "resolve_human_task",
    nodeId: "node-gate",
    available: true,
    label: "接受",
    reasonCode: "",
    blockerIds: [],
    payload: { taskId: "task-9", decision: "accept" },
    ...patch,
  };
}

describe("humanGateScopeFor", () => {
  it("requires teamId, runId and taskId before inline buttons are allowed", () => {
    expect(humanGateScopeFor(payload({}))).toEqual({ teamId: "team-1", runId: "run-7", taskId: "task-9" });
    expect(humanGateScopeFor(payload({ meta: { teamId: "team-1", runId: "run-7" } }))).toBeNull();
    expect(humanGateScopeFor(payload({ meta: undefined }))).toBeNull();
    expect(humanGateScopeFor(payload({ meta: { runId: "run-7", taskId: "task-9" } }))).toBeNull();
  });
});

describe("findHumanGateOffer", () => {
  const accept = offer({ expectedRunVersion: 3, idempotencyKey: "key-a" });
  const reject = offer({
    expectedRunVersion: 3,
    idempotencyKey: "key-r",
    payload: { taskId: "task-9", decision: "reject" },
  });

  it("matches resolve_human_task offers by payload taskId + decision", () => {
    expect(findHumanGateOffer([accept, reject], "task-9", "accept")).toBe(accept);
    expect(findHumanGateOffer([accept, reject], "task-9", "reject")).toBe(reject);
    expect(findHumanGateOffer([accept], "task-9", "reject")).toBeNull();
    expect(findHumanGateOffer([{ ...accept, command: "retry_node" }], "task-9", "accept")).toBeNull();
    expect(findHumanGateOffer([{ ...accept, payload: { taskId: "task-other", decision: "accept" } }], "task-9", "accept")).toBeNull();
  });

  it("falls back to the offer id suffix when the payload omits the facts", () => {
    const byIdOnly = offer({
      expectedRunVersion: 4,
      idempotencyKey: "key-id",
      payload: {},
      ...({ id: "offer:run-7:node-gate:resolve_human_task:task-9:reject" } as Partial<CommandOffer>),
    });
    expect(findHumanGateOffer([byIdOnly], "task-9", "reject")).toBe(byIdOnly);
    expect(findHumanGateOffer([byIdOnly], "task-9", "accept")).toBeNull();
  });
});

describe("submitHumanGateDecision", () => {
  it("submits the matching offer through the shared command client", async () => {
    const accept = offer({ expectedRunVersion: 3, idempotencyKey: "key-a" });
    const fetchSnapshot = vi.fn().mockResolvedValue({ commandOffers: [accept] });
    const submitOffer = vi.fn().mockResolvedValue({ commandId: "c-1" });
    const result = await submitHumanGateDecision({
      teamId: "team-1",
      runId: "run-7",
      taskId: "task-9",
      decision: "accept",
      fetchSnapshot,
      submitOffer,
    });
    expect(result).toEqual({ outcome: "submitted", receipt: { commandId: "c-1" } });
    expect(fetchSnapshot).toHaveBeenCalledTimes(1);
    expect(fetchSnapshot).toHaveBeenCalledWith({ teamId: "team-1", runId: "run-7", signal: undefined });
    expect(submitOffer).toHaveBeenCalledTimes(1);
    expect(submitOffer).toHaveBeenCalledWith({
      teamId: "team-1",
      runId: "run-7",
      offer: accept,
      signal: undefined,
    });
  });

  it("silently refetches the snapshot once before declaring the offer unavailable", async () => {
    const accept = offer({ expectedRunVersion: 9, idempotencyKey: "key-v2" });
    const fetchSnapshot = vi
      .fn()
      .mockResolvedValueOnce({ commandOffers: [] })
      .mockResolvedValueOnce({ commandOffers: [accept] });
    const submitOffer = vi.fn().mockResolvedValue({ commandId: "c-2" });
    const result = await submitHumanGateDecision({
      teamId: "team-1",
      runId: "run-7",
      taskId: "task-9",
      decision: "accept",
      fetchSnapshot,
      submitOffer,
    });
    expect(fetchSnapshot).toHaveBeenCalledTimes(2);
    expect(result).toEqual({ outcome: "submitted", receipt: { commandId: "c-2" } });
  });

  it("reports unavailable after the refetch still finds no matching offer", async () => {
    const fetchSnapshot = vi.fn().mockResolvedValue({ commandOffers: [] });
    const submitOffer = vi.fn();
    const result = await submitHumanGateDecision({
      teamId: "team-1",
      runId: "run-7",
      taskId: "task-9",
      decision: "reject",
      fetchSnapshot,
      submitOffer,
    });
    expect(fetchSnapshot).toHaveBeenCalledTimes(2);
    expect(submitOffer).not.toHaveBeenCalled();
    expect(result).toEqual({ outcome: "unavailable" });
  });

  it("treats a snapshot failure as unavailable so the caller can navigate", async () => {
    const fetchSnapshot = vi.fn().mockRejectedValue(new Error("run archived"));
    const result = await submitHumanGateDecision({
      teamId: "team-1",
      runId: "run-7",
      taskId: "task-9",
      decision: "accept",
      fetchSnapshot,
      submitOffer: vi.fn(),
    });
    expect(result).toEqual({ outcome: "unavailable" });
  });

  it("propagates submit failures to the card for inline error handling", async () => {
    const accept = offer({ expectedRunVersion: 3, idempotencyKey: "key-a" });
    const fetchSnapshot = vi.fn().mockResolvedValue({ commandOffers: [accept] });
    const submitOffer = vi.fn().mockRejectedValue(new Error("version_conflict"));
    await expect(submitHumanGateDecision({
      teamId: "team-1",
      runId: "run-7",
      taskId: "task-9",
      decision: "accept",
      fetchSnapshot,
      submitOffer,
    })).rejects.toThrow("version_conflict");
  });
});
