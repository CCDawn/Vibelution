import { describe, expect, it, vi } from "vitest";
import type { PersonalAssistantAttentionRow } from "./humanAttentionNotifications";
import {
  HUMAN_ATTENTION_FALLBACK_TITLES,
  HUMAN_ATTENTION_KINDS,
  buildHumanAttentionNotificationPayload,
  createHumanAttentionLedger,
  emitNewHumanAttentionNotifications,
  humanAttentionBridge,
  humanAttentionTargetFor,
  isHumanAttentionKind,
  localDayKey,
  parseHumanAttentionEvent,
  sanitizeHumanAttentionTargetUrl,
} from "./humanAttentionNotifications";

type MemoryStorage = Pick<Storage, "getItem" | "setItem">;

function memoryStorage(options?: { failWrite?: boolean }): MemoryStorage & { dump(): string | null } {
  let stored: string | null = null;
  return {
    getItem: () => stored,
    setItem: (_key: string, value: string) => {
      if (options?.failWrite) {
        throw new Error("storage blocked");
      }
      stored = value;
    },
    dump: () => stored,
  };
}

function attentionRow(patch: Partial<PersonalAssistantAttentionRow> & { id: string }): PersonalAssistantAttentionRow {
  return { kind: "knowledge_review", title: "待复核知识", ...patch } as PersonalAssistantAttentionRow;
}

describe("human attention bridge discovery", () => {
  it("exposes only the human-attention methods the launcher provides", () => {
    const notifyHumanAttention = vi.fn();
    const bridge = humanAttentionBridge({ vibelutionLauncher: { notifyHumanAttention, unrelated: true } });
    expect(bridge?.notifyHumanAttention).toBeTypeOf("function");
    expect(bridge?.onHumanAttentionOpened).toBeUndefined();
  });
  it("returns undefined without the launcher global (non-desktop environments)", () => {
    expect(humanAttentionBridge({})).toBeUndefined();
    expect(humanAttentionBridge({ vibelutionLauncher: {} })).toBeUndefined();
  });
});

describe("human attention payload building", () => {
  it("builds a payload only for human-attention kinds with valid ids", () => {
    expect(buildHumanAttentionNotificationPayload(attentionRow({ id: "kr-1", kind: "approval" }))).toBeNull();
    expect(buildHumanAttentionNotificationPayload(attentionRow({ id: "bad id!", kind: "anomaly" }))).toBeNull();
    expect(buildHumanAttentionNotificationPayload(undefined)).toBeNull();
  });
  it("normalizes severity, trims copy and falls back to a kind title", () => {
    const payload = buildHumanAttentionNotificationPayload(attentionRow({
      id: "kr-2",
      kind: "anomaly",
      title: "   ",
      severity: "severe!!!",
      body: "  批次   失败  ",
      targetUrl: "/teams?researchView=workflow",
    }));
    expect(payload).toEqual({
      id: "kr-2",
      kind: "anomaly",
      severity: "medium",
      title: "研究流程异常待处理",
      body: "批次 失败",
      targetUrl: "/teams?researchView=workflow",
    });
  });
  it("accepts human_gate rows and carries sanitized actions and meta", () => {
    // Unknown meta keys must not fail the type check while proving they are dropped.
    const noisyMeta = {
      teamId: "team-1",
      runId: "run-7",
      nodeId: "node-gate",
      taskId: "task-9",
      decisions: ["accept", "reject", "revise", ""],
      ignored: "dropped",
    } as unknown as PersonalAssistantAttentionRow["meta"];
    const payload = buildHumanAttentionNotificationPayload(attentionRow({
      id: "gate-1",
      kind: "human_gate",
      severity: "high",
      title: "研究结论等待审批",
      targetUrl: "/teams?researchView=workflow&runId=run-7",
      actions: [
        { label: "接受", decision: "accept" },
        { label: "驳回", decision: "reject" },
        // Malformed entries are dropped instead of poisoning the payload.
        { label: "", decision: "accept" },
        { label: "x", decision: 42 as unknown as string },
      ],
      meta: noisyMeta,
    }));
    expect(payload).toEqual({
      id: "gate-1",
      kind: "human_gate",
      severity: "high",
      title: "研究结论等待审批",
      targetUrl: "/teams?researchView=workflow&runId=run-7",
      actions: [
        { label: "接受", decision: "accept" },
        { label: "驳回", decision: "reject" },
      ],
      meta: {
        teamId: "team-1",
        runId: "run-7",
        nodeId: "node-gate",
        taskId: "task-9",
        decisions: ["accept", "reject", "revise"],
      },
    });
  });
  it("drops malformed actions/meta entirely instead of emitting empty husks", () => {
    const payload = buildHumanAttentionNotificationPayload(attentionRow({
      id: "gate-2",
      kind: "human_gate",
      actions: [{ label: "  ", decision: "accept" }],
      meta: { teamId: "   " },
    }));
    expect(payload?.actions).toBeUndefined();
    expect(payload?.meta).toBeUndefined();
  });
});

describe("human attention target resolution", () => {
  it("accepts only same-site absolute paths", () => {
    expect(sanitizeHumanAttentionTargetUrl("//evil.example/x")).toBe("");
    expect(sanitizeHumanAttentionTargetUrl("https://evil.example/x")).toBe("");
    expect(sanitizeHumanAttentionTargetUrl("javascript:alert(1)")).toBe("");
    expect(sanitizeHumanAttentionTargetUrl(" /memory/knowledge ")).toBe("/memory/knowledge");
  });
  it("prefers targetUrl and falls back to the kind default", () => {
    expect(humanAttentionTargetFor({ kind: "knowledge_review" })).toBe("/memory/knowledge");
    expect(humanAttentionTargetFor({ kind: "anomaly" })).toBe("/teams?researchView=workflow");
    expect(humanAttentionTargetFor({ kind: "anomaly", targetUrl: "/memory/knowledge" })).toBe("/memory/knowledge");
    expect(humanAttentionTargetFor({})).toBe("");
  });
  it("accepts affair_reminder rows with the assistant-page default target", () => {
    expect(isHumanAttentionKind("affair_reminder")).toBe(true);
    expect(isHumanAttentionKind("affair-reminder")).toBe(false);
    expect(humanAttentionTargetFor({ kind: "affair_reminder" })).toBe("/personal-assistant");
    expect(HUMAN_ATTENTION_FALLBACK_TITLES.affair_reminder).toContain("事务");
  });
  it("keeps human_gate in the whitelist with the research-workflow default target", () => {
    expect(isHumanAttentionKind("human_gate")).toBe(true);
    expect(isHumanAttentionKind("human-gate")).toBe(false);
    expect(humanAttentionTargetFor({ kind: "human_gate" })).toBe("/teams?researchView=workflow");
    expect(HUMAN_ATTENTION_FALLBACK_TITLES.human_gate).toContain("审批");
  });
  it("whitelists exactly the four dual-channel kinds (mirrored by the Electron shell)", () => {
    expect([...HUMAN_ATTENTION_KINDS].sort()).toEqual([
      "affair_reminder",
      "anomaly",
      "human_gate",
      "knowledge_review",
    ]);
  });
});

describe("human attention event parsing", () => {
  it("parses full payloads as window deliveries", () => {
    const event = parseHumanAttentionEvent({ id: "kr-3", kind: "knowledge_review", severity: "critical", title: "T", body: "B", targetUrl: "/memory/knowledge" });
    expect(event).toEqual({
      type: "delivered",
      payload: { id: "kr-3", kind: "knowledge_review", severity: "critical", title: "T", body: "B", targetUrl: "/memory/knowledge" },
    });
  });
  it("keeps human-gate actions and meta on window deliveries from the shell", () => {
    const event = parseHumanAttentionEvent({
      id: "gate-3",
      kind: "human_gate",
      severity: "high",
      title: "等待人工审批",
      actions: [{ label: "接受", decision: "accept" }, { label: "驳回", decision: "reject" }],
      meta: { teamId: "team-1", runId: "run-7", nodeId: "n-1", taskId: "task-9", decisions: ["accept", "reject", "revise"] },
    });
    expect(event).toEqual({
      type: "delivered",
      payload: {
        id: "gate-3",
        kind: "human_gate",
        severity: "high",
        title: "等待人工审批",
        actions: [{ label: "接受", decision: "accept" }, { label: "驳回", decision: "reject" }],
        meta: { teamId: "team-1", runId: "run-7", nodeId: "n-1", taskId: "task-9", decisions: ["accept", "reject", "revise"] },
      },
    });
  });
  it("strips malformed actions instead of delivering them to the card", () => {
    const event = parseHumanAttentionEvent({
      id: "gate-4",
      kind: "human_gate",
      title: "等待人工审批",
      actions: "accept",
      meta: [],
    });
    expect(event?.type).toBe("delivered");
    expect(event && event.type === "delivered" ? event.payload.actions : undefined).toBeUndefined();
    expect(event && event.type === "delivered" ? event.payload.meta : undefined).toBeUndefined();
  });
  it("parses bare ids as opened clicks and rejects invalid ids", () => {
    expect(parseHumanAttentionEvent({ id: "kr-4", targetUrl: "/memory/knowledge" })).toEqual({
      type: "opened",
      payload: { id: "kr-4", targetUrl: "/memory/knowledge" },
    });
    expect(parseHumanAttentionEvent({ id: "kr-5" })).toEqual({ type: "opened", payload: { id: "kr-5" } });
    expect(parseHumanAttentionEvent({ targetUrl: "/memory/knowledge" })).toBeNull();
    expect(parseHumanAttentionEvent(null)).toBeNull();
  });
});

describe("human attention notification ledger", () => {
  it("marks ids for the current local day only", () => {
    const storage = memoryStorage();
    const ledger = createHumanAttentionLedger(storage, "2026-10-18");
    ledger.add("kr-1");
    expect(ledger.has("kr-1")).toBe(true);
    expect(createHumanAttentionLedger(storage, "2026-10-18").has("kr-1")).toBe(true);
    // A different day discards the previous ledger (notifications are valid for the day).
    expect(createHumanAttentionLedger(storage, "2026-10-19").has("kr-1")).toBe(false);
  });
  it("caps the persisted ledger and tolerates blocked storage writes", () => {
    const storage = memoryStorage();
    const ledger = createHumanAttentionLedger(storage, "2026-10-18");
    for (let index = 0; index < 401; index += 1) {
      ledger.add(`kr-${index}`);
    }
    const persisted = JSON.parse(storage.dump()!) as { day: string; ids: string[] };
    expect(persisted.ids).toHaveLength(400);
    expect(persisted.ids[0]).toBe("kr-1");
    const blocked = createHumanAttentionLedger(memoryStorage({ failWrite: true }), "2026-10-18");
    expect(() => blocked.add("kr-x")).not.toThrow();
    expect(blocked.has("kr-x")).toBe(true);
    expect(localDayKey(new Date(2026, 9, 8))).toBe("2026-10-08");
  });
});

describe("human attention emission", () => {
  it("notifies each unseen id exactly once and persists the dedup", () => {
    const storage = memoryStorage();
    const ledger = createHumanAttentionLedger(storage, "2026-10-18");
    const notifyHumanAttention = vi.fn().mockResolvedValue({ delivered: "assistant_window" });
    const rows = [attentionRow({ id: "kr-1", severity: "critical" }), attentionRow({ id: "an-1", kind: "anomaly", severity: "high" })];
    const emitted = emitNewHumanAttentionNotifications({ rows, bridge: { notifyHumanAttention }, ledger });
    expect(emitted.map(payload => payload.id)).toEqual(["kr-1", "an-1"]);
    expect(notifyHumanAttention).toHaveBeenCalledTimes(2);
    expect(emitNewHumanAttentionNotifications({ rows, bridge: { notifyHumanAttention }, ledger })).toEqual([]);
    expect(notifyHumanAttention).toHaveBeenCalledTimes(2);
    // A fresh ledger over the same storage (page refresh) keeps the dedup.
    expect(emitNewHumanAttentionNotifications({
      rows,
      bridge: { notifyHumanAttention },
      ledger: createHumanAttentionLedger(storage, "2026-10-18"),
    })).toEqual([]);
    expect(notifyHumanAttention).toHaveBeenCalledTimes(2);
  });
  it("skips silently without a bridge and marks nothing", () => {
    const ledger = createHumanAttentionLedger(memoryStorage(), "2026-10-18");
    const rows = [attentionRow({ id: "kr-9" })];
    expect(emitNewHumanAttentionNotifications({ rows, bridge: undefined, ledger })).toEqual([]);
    expect(ledger.has("kr-9")).toBe(false);
  });
  it("survives a rejecting bridge call without unhandled rejections", async () => {
    const ledger = createHumanAttentionLedger(memoryStorage(), "2026-10-18");
    const notifyHumanAttention = vi.fn().mockRejectedValue(new Error("shell gone"));
    const emitted = emitNewHumanAttentionNotifications({ rows: [attentionRow({ id: "kr-10" })], bridge: { notifyHumanAttention }, ledger });
    expect(emitted).toHaveLength(1);
    // The emitter swallows the rejection; flush the microtask queue to prove it.
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(notifyHumanAttention).toHaveBeenCalledTimes(1);
  });
});

describe("human attention emission failure reporting", () => {
  it("reports a rejected bridge call once with the failure context", async () => {
    const ledger = createHumanAttentionLedger(memoryStorage(), "2026-10-18");
    const reportFailure = vi.fn();
    const notifyHumanAttention = vi.fn().mockRejectedValue(new Error("ipc rejected"));
    emitNewHumanAttentionNotifications({
      rows: [attentionRow({ id: "kr-11", kind: "anomaly", severity: "critical" })],
      bridge: { notifyHumanAttention },
      ledger,
      reportFailure,
    });
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(reportFailure).toHaveBeenCalledTimes(1);
    expect(reportFailure).toHaveBeenCalledWith({
      id: "kr-11",
      kind: "anomaly",
      severity: "critical",
      reason: "notify rejected: ipc rejected",
      title: "待复核知识",
    });
  });
  it("reports an invalid_payload resolve value but not healthy deliveries", async () => {
    const ledger = createHumanAttentionLedger(memoryStorage(), "2026-10-18");
    const reportFailure = vi.fn();
    const invalid = vi.fn().mockResolvedValue({ delivered: "invalid_payload", error: "bad kind" });
    const healthy = vi.fn().mockResolvedValue({ delivered: "system_notification" });
    const opaqueResult = vi.fn().mockResolvedValue(undefined);
    emitNewHumanAttentionNotifications({
      rows: [attentionRow({ id: "kr-12", kind: "anomaly" })],
      bridge: { notifyHumanAttention: invalid },
      ledger,
      reportFailure,
    });
    emitNewHumanAttentionNotifications({
      rows: [attentionRow({ id: "kr-13", kind: "anomaly" })],
      bridge: { notifyHumanAttention: healthy },
      ledger,
      reportFailure,
    });
    emitNewHumanAttentionNotifications({
      rows: [attentionRow({ id: "kr-14", kind: "anomaly" })],
      bridge: { notifyHumanAttention: opaqueResult },
      ledger,
      reportFailure,
    });
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(reportFailure).toHaveBeenCalledTimes(1);
    expect(reportFailure).toHaveBeenCalledWith(expect.objectContaining({
      id: "kr-12",
      reason: "notify resolved with delivered=invalid_payload",
    }));
  });
  it("never reports when the bridge is missing (plain browser)", () => {
    const reportFailure = vi.fn();
    emitNewHumanAttentionNotifications({
      rows: [attentionRow({ id: "kr-15" })],
      bridge: undefined,
      ledger: createHumanAttentionLedger(memoryStorage(), "2026-10-18"),
      reportFailure,
    });
    expect(reportFailure).not.toHaveBeenCalled();
  });
});
