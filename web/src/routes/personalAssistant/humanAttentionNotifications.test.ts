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
  normalizeHumanAttentionSeverity,
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
  it("whitelists exactly the eight dual-channel kinds (mirrored by the Electron shell)", () => {
    expect([...HUMAN_ATTENTION_KINDS].sort()).toEqual([
      "affair_reminder",
      "anomaly",
      "assistant_digest",
      "dispatch_receipt",
      "human_gate",
      "knowledge_review",
      "run_completed",
      "session_completed",
    ]);
  });
  it("accepts assistant_digest rows with the assistant-page default target", () => {
    expect(isHumanAttentionKind("assistant_digest")).toBe(true);
    expect(isHumanAttentionKind("assistant-digest")).toBe(false);
    expect(humanAttentionTargetFor({ kind: "assistant_digest" })).toBe("/personal-assistant");
    expect(HUMAN_ATTENTION_FALLBACK_TITLES.assistant_digest).toContain("派遣");
  });
  it("maps the three completion kinds to real pages with info severity", () => {
    // 完成类事件（好消息）：targetUrl 必须落到真实页面，不许是空状态页。
    expect(humanAttentionTargetFor({ kind: "dispatch_receipt" })).toBe("/personal-assistant?panel=dispatches");
    expect(humanAttentionTargetFor({ kind: "run_completed" })).toBe("/teams?researchView=workflow");
    expect(humanAttentionTargetFor({ kind: "session_completed" })).toBe("/chat");
    expect(isHumanAttentionKind("dispatch_receipt") && isHumanAttentionKind("run_completed") && isHumanAttentionKind("session_completed")).toBe(true);
    expect(normalizeHumanAttentionSeverity("info")).toBe("info");
    expect(normalizeHumanAttentionSeverity("urgent")).toBe("medium");
    expect(HUMAN_ATTENTION_FALLBACK_TITLES.dispatch_receipt).toContain("派遣");
    expect(HUMAN_ATTENTION_FALLBACK_TITLES.run_completed).toContain("完成");
    expect(HUMAN_ATTENTION_FALLBACK_TITLES.session_completed).toContain("完成");
  });
  it("builds completion payloads carrying the server targetUrl verbatim", () => {
    const payload = buildHumanAttentionNotificationPayload({
      id: "run-completed:team-r:run-1",
      kind: "run_completed",
      severity: "info",
      title: "研究运行完成：SCI-001",
      targetUrl: "/teams?teamId=team-r&researchView=workflow&workflowId=challenge-cup-research&runId=run-1&panel=progress",
      body: "攻坚一组 · SCI-001",
    } as PersonalAssistantAttentionRow);
    expect(payload).not.toBeNull();
    expect(payload?.severity).toBe("info");
    expect(payload?.targetUrl).toContain("runId=run-1");
    expect(payload?.targetUrl).toContain("panel=progress");
    const sessionPayload = buildHumanAttentionNotificationPayload({
      id: "session-completed:session-a:1800000000",
      kind: "session_completed",
      severity: "info",
      title: "会话已完成：量子调研",
      targetUrl: "/chat?session=session-a",
    } as PersonalAssistantAttentionRow);
    expect(sessionPayload?.targetUrl).toBe("/chat?session=session-a");
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
  it("never erases another window's successful ID after a negotiated source rejection", async () => {
    const storage = memoryStorage();
    const first = createHumanAttentionLedger(storage, "2026-10-18");
    const second = createHumanAttentionLedger(storage, "2026-10-18");
    let finish!: (result: unknown) => void;
    const notifyHumanAttention = vi.fn().mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }))
      .mockResolvedValueOnce({ delivered: "system_notification" });
    const rows = [attentionRow({ id: "shared-affair", kind: "affair_reminder" })];
    emitNewHumanAttentionNotifications({ rows, bridge: { notifyHumanAttention }, ledger: first, affairMode: "main_owned" });
    expect(emitNewHumanAttentionNotifications({ rows, bridge: { notifyHumanAttention }, ledger: first, affairMode: "main_owned" })).toEqual([]);
    emitNewHumanAttentionNotifications({ rows, bridge: { notifyHumanAttention }, ledger: second, affairMode: "main_owned" });
    await new Promise(resolve => setTimeout(resolve, 0));
    finish({ delivered: "source_retired" });
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(createHumanAttentionLedger(storage, "2026-10-18").has("shared-affair")).toBe(true);
    expect(notifyHumanAttention).toHaveBeenCalledTimes(2);
  });
  it.each(["source_retired", "invalid_payload"])("does not persist negotiated %s", async delivered => {
    const storage = memoryStorage();
    const ledger = createHumanAttentionLedger(storage, "2026-10-18");
    const rows = [attentionRow({ id: "rejected-affair", kind: "affair_reminder" })];
    const notifyHumanAttention = vi.fn().mockResolvedValue({ delivered });
    emitNewHumanAttentionNotifications({ rows, bridge: { notifyHumanAttention }, ledger, affairMode: "main_owned", reportFailure: vi.fn() });
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(ledger.has("rejected-affair")).toBe(false);
    expect(createHumanAttentionLedger(storage, "2026-10-18").has("rejected-affair")).toBe(false);
  });
  it("retains unknown negotiated outcomes without an automatic retry", async () => {
    const storage = memoryStorage();
    const ledger = createHumanAttentionLedger(storage, "2026-10-18");
    const rows = [attentionRow({ id: "unknown-affair", kind: "affair_reminder" })];
    const notifyHumanAttention = vi.fn().mockRejectedValue(new Error("reply lost"));
    emitNewHumanAttentionNotifications({ rows, bridge: { notifyHumanAttention }, ledger, affairMode: "main_owned", reportFailure: vi.fn() });
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(createHumanAttentionLedger(storage, "2026-10-18").has("unknown-affair")).toBe(true);
    expect(emitNewHumanAttentionNotifications({ rows, bridge: { notifyHumanAttention }, ledger, affairMode: "main_owned" })).toEqual([]);
    expect(notifyHumanAttention).toHaveBeenCalledTimes(1);
  });
  it.each(["source_busy", "source_unavailable", "source_recovery_required"])("reports %s and retries only a proven unsent affair", async delivered => {
    const storage = memoryStorage(), ledger = createHumanAttentionLedger(storage, "2026-10-18");
    const rows = [attentionRow({ id: "retryable-affair", kind: "affair_reminder" })];
    const reportFailure = vi.fn();
    const notifyHumanAttention = vi.fn().mockResolvedValueOnce({ delivered }).mockResolvedValueOnce({ delivered: "system_notification" });
    emitNewHumanAttentionNotifications({ rows, bridge: { notifyHumanAttention }, ledger, affairMode: "main_owned", reportFailure });
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(ledger.has("retryable-affair")).toBe(false);
    expect(reportFailure).toHaveBeenCalledOnce();
    emitNewHumanAttentionNotifications({ rows, bridge: { notifyHumanAttention }, ledger, affairMode: "main_owned", reportFailure });
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(notifyHumanAttention).toHaveBeenCalledTimes(2);
    expect(ledger.has("retryable-affair")).toBe(true);
  });
  it("keeps an earlier unknown attempt marked while a later recovery-blocked affair can retry after refresh", async () => {
    const storage = memoryStorage(), ledger = createHumanAttentionLedger(storage, "2026-10-18"), reportFailure = vi.fn();
    const rows = [attentionRow({ id: "prior-affair", kind: "affair_reminder" }),
      attentionRow({ id: "new-affair", kind: "affair_reminder" })];
    const notifyHumanAttention = vi.fn().mockResolvedValueOnce({ delivered: "attempt_pending" })
      .mockResolvedValueOnce({ delivered: "source_recovery_required" }).mockResolvedValueOnce({ delivered: "system_notification" });
    emitNewHumanAttentionNotifications({ rows, bridge: { notifyHumanAttention }, ledger, affairMode: "main_owned", reportFailure });
    await new Promise(resolve => setTimeout(resolve, 0));
    const restarted = createHumanAttentionLedger(storage, "2026-10-18");
    expect(restarted.has("prior-affair")).toBe(true);
    expect(restarted.has("new-affair")).toBe(false);
    expect(reportFailure).toHaveBeenCalledOnce();
    emitNewHumanAttentionNotifications({ rows, bridge: { notifyHumanAttention }, ledger: restarted, affairMode: "main_owned", reportFailure });
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(notifyHumanAttention).toHaveBeenCalledTimes(3);
    expect(notifyHumanAttention).toHaveBeenLastCalledWith(expect.objectContaining({ id: "new-affair" }));
    expect(restarted.has("new-affair")).toBe(true);
  });
  it("does not change the unnegotiated or non-affair notification path", async () => {
    const storage = memoryStorage();
    const ledger = createHumanAttentionLedger(storage, "2026-10-18");
    const notifyHumanAttention = vi.fn().mockResolvedValue({ delivered: "source_retired" });
    const rows = [attentionRow({ id: "legacy-affair", kind: "affair_reminder" }), attentionRow({ id: "other", kind: "session_completed" })];
    emitNewHumanAttentionNotifications({ rows, bridge: { notifyHumanAttention }, ledger });
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(createHumanAttentionLedger(storage, "2026-10-18").has("legacy-affair")).toBe(true);
    expect(createHumanAttentionLedger(storage, "2026-10-18").has("other")).toBe(true);
  });
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
