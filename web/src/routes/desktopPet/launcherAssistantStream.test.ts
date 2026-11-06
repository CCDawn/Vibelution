import { describe, expect, it } from "vitest";
import { parseLauncherAssistantSessionEvent, type LauncherAssistantSessionEvent } from "../../api/launcherAssistant";
import type { ConversationMessage, SessionDetail, SessionStreamAppendEntry, SessionTurnItem } from "../../api/types";
import { projectAgentMessageTimelineMessages } from "../../components/conversation/useAgentMessageTimelineProjection";
import { activeTurnLayerToConversationMessage, createLauncherAssistantStream } from "./launcherAssistantStream";

function item(text = "hello", patch: Partial<SessionTurnItem> = {}): SessionTurnItem {
  return { version: 3, id: "answer-r1", itemId: "answer", sessionId: "session-1", turnId: "turn-1",
    type: "agent_message", phase: "final_answer", text, status: "running", revision: 1, sequence: 1,
    ...patch } as SessionTurnItem;
}
function event(patch: Partial<LauncherAssistantSessionEvent> = {}): LauncherAssistantSessionEvent {
  return { type: "assistant_delta", sessionId: "session-1", turnId: "turn-1", at: 1,
    ledgerSeq: 10, deltaSeq: 1, deltaSeqFrom: 1, stage: "responding", done: false,
    updatedAt: "2026-11-03T08:00:00Z", turnItems: [item()], ...patch };
}
function append(baseLength: number, appendedText: string, patch: Partial<SessionStreamAppendEntry> = {}): SessionStreamAppendEntry {
  return { kind: "append", itemId: "answer", itemType: "agent_message", baseLength,
    appendedLength: Array.from(appendedText).length, appendedText, ...patch };
}
function appendEvent(deltaSeq: number, baseLength: number, appendedText: string, patch: Partial<LauncherAssistantSessionEvent> = {}) {
  return event({ deltaSeq, deltaSeqFrom: deltaSeq, turnItems: [], streamEncoding: "append-v1",
    turnItemAppends: [append(baseLength, appendedText)], ...patch });
}
function message(items: SessionTurnItem[], patch: Partial<ConversationMessage> = {}): ConversationMessage {
  return { id: "native-message-1", role: "assistant", timestamp: "2026-11-03T08:00:00Z",
    turnId: "turn-1", status: "running", turnItems: items, ...patch };
}
function detail(items: SessionTurnItem[] = [], patch: Partial<SessionDetail> = {}): SessionDetail {
  return { id: "session-1", ledgerSeq: 10, activeTurnId: "turn-1", currentPhase: "responding",
    status: "running", messages: items.length ? [message(items)] : [], ...patch } as SessionDetail;
}

describe("launcher assistant native stream", () => {
  it("shares the native optimistic and accepted layer handoff without losing an early stream", () => {
    const stream = createLauncherAssistantStream("session-1");
    expect(stream.beginSubmission("request-1")).toMatchObject({ clientSubmissionId: "request-1", status: "pending", turnItems: [] });
    const early = stream.apply(event()).layer;
    expect(early?.turnItems).toEqual([item()]);
    expect(stream.acceptSubmission("request-1", "turn-1")?.turnItems).toEqual([item()]);
    expect(stream.rejectSubmission("request-1")?.turnItems).toEqual([item()]);
  });

  it("withdraws a rejected waiting shell and leaves another turn alone for queued acceptance", () => {
    const stream = createLauncherAssistantStream("session-1");
    stream.beginSubmission("request-1");
    expect(stream.rejectSubmission("request-1")).toBeUndefined();
    stream.beginSubmission("accepted-request");
    expect(stream.acceptSubmission("accepted-request", "turn-1")?.processStage).toBe("user_submit");
    stream.rejectSubmission("accepted-request");
    const running = stream.apply(event()).layer;
    expect(stream.beginSubmission("queued-request")).toBe(running);
    expect(stream.acceptSubmission("queued-request", "", true)).toBe(running);
  });
  it.each(["你好🐳", "🧑🏽‍💻一起工作", "𠮷野家"])("continues native codepoint appends after %s", seed => {
    const stream = createLauncherAssistantStream("session-1");
    stream.apply(event({ turnItems: [item(seed)] }));
    const next = stream.apply(appendEvent(2, Array.from(seed).length, "继续🚀"));
    expect(next.needsRefresh).toBe(false);
    expect(next.layer?.turnItems[0]).toMatchObject({ text: seed + "继续🚀" });
    const last = stream.apply(appendEvent(3, Array.from(seed + "继续🚀").length, "完成"));
    expect(last.needsRefresh).toBe(false);
    expect(last.layer?.turnItems[0]).toMatchObject({ text: seed + "继续🚀完成" });
  });

  it("handles an emoji appended before the next fragment, including two fragments in one frame", () => {
    const stream = createLauncherAssistantStream("session-1");
    stream.apply(event({ turnItems: [item("你好")] }));
    const next = stream.apply(appendEvent(2, 2, "🐳", { turnItemAppends: [append(2, "🐳"), append(3, "继续")] }));
    expect(next.needsRefresh).toBe(false);
    expect(next.layer?.turnItems[0]).toMatchObject({ text: "你好🐳继续" });
  });

  it("continues an append from an emoji-bearing canonical detail baseline", () => {
    const stream = createLauncherAssistantStream("session-1");
    stream.reconcile(detail([item("你好🐳")]));
    const next = stream.apply(appendEvent(1, 3, "继续"));
    expect(next.needsRefresh).toBe(false);
    expect(next.layer?.turnItems[0]).toMatchObject({ text: "你好🐳继续" });
  });

  it("lets a full row supersede redundant appends and preserves Unicode progress across lagging detail", () => {
    const stream = createLauncherAssistantStream("session-1");
    const initial = detail([item("你好🐳")]);
    stream.reconcile(initial);
    const full = stream.apply(event({ turnItems: [item("你好🐳")], streamEncoding: "append-v1",
      turnItemAppends: [append(99, "redundant", { appendedLength: 0 })] }));
    expect(full.needsRefresh).toBe(false);
    expect(stream.apply(appendEvent(2, 3, "继续")).needsRefresh).toBe(false);
    stream.reconcile(initial);
    const next = stream.apply(appendEvent(3, 5, "🚀"));
    expect(next.needsRefresh).toBe(false);
    expect(next.layer?.turnItems[0]).toMatchObject({ text: "你好🐳继续🚀" });
  });

  it("normalizes reasoning independently from answer items after canonical coverage", () => {
    const stream = createLauncherAssistantStream("session-1");
    const reasoning = item("想🐳", { type: "reasoning", itemId: "reason", id: "reason-r1" });
    stream.apply(event({ turnItems: [item("答🚀"), reasoning] }));
    stream.reconcile(detail([reasoning]));
    const next = stream.apply(appendEvent(2, 2, "案", { turnItemAppends: [append(2, "案"),
      append(2, "好", { itemId: "reason", itemType: "reasoning" })] }));
    expect(next.needsRefresh).toBe(false);
    expect(next.layer?.turnItems).toEqual(expect.arrayContaining([
      expect.objectContaining({ itemId: "answer", text: "答🚀案" }),
      expect.objectContaining({ itemId: "reason", text: "想🐳好" }),
    ]));
  });

  it("rejects real length gaps and incorrect native appended lengths", () => {
    for (const entry of [append(4, "继续"), append(3, "继续", { appendedLength: 3 })]) {
      const stream = createLauncherAssistantStream("session-1");
      const initial = stream.apply(event({ turnItems: [item("你好🐳")] })).layer;
      expect(stream.apply(appendEvent(2, entry.baseLength, entry.appendedText, { turnItemAppends: [entry] })))
        .toEqual({ layer: initial, needsRefresh: true });
    }
  });

  it("renders a complete same-turn terminal snapshot after a gap while detail recovery is pending", () => {
    const stream = createLauncherAssistantStream("session-1");
    stream.apply(event());
    expect(stream.apply(appendEvent(3, 5, " lost", { ledgerSeq: 12 })).needsRefresh).toBe(true);
    const final = stream.apply(event({ deltaSeq: 4, deltaSeqFrom: 4, ledgerSeq: 13, done: true,
      turnItems: [item("hello recovered", { status: "completed", terminal: true, revision: 2 })] }));
    expect(final.needsRefresh).toBe(true);
    expect(final.layer?.status).toBe("completed");
    expect(final.layer?.turnItems[0]).toMatchObject({ text: "hello recovered" });
  });

  it("does not release recovery with a terminal snapshot behind a held newer-turn watermark", () => {
    const stream = createLauncherAssistantStream("session-1");
    const initial = stream.apply(event()).layer;
    stream.apply(appendEvent(3, 5, " lost", { ledgerSeq: 12 }));
    stream.apply(event({ turnId: "turn-2", deltaSeq: 4, deltaSeqFrom: 4, ledgerSeq: 20,
      turnItems: [item("new turn", { turnId: "turn-2" })] }));
    expect(stream.apply(event({ deltaSeq: 5, deltaSeqFrom: 5, ledgerSeq: 13, done: true,
      turnItems: [item("obsolete terminal", { status: "completed", terminal: true })] })))
      .toEqual({ layer: initial, needsRefresh: true });
  });

  it("requires a terminal snapshot to cover the highest observed same-turn sequence", () => {
    const stream = createLauncherAssistantStream("session-1");
    const initial = stream.apply(event()).layer;
    stream.apply(appendEvent(3, 5, " lost"));
    stream.apply(appendEvent(5, 10, " newer"));
    for (const deltaSeq of [undefined, 0, 4]) {
      expect(stream.apply(event({ deltaSeq, deltaSeqFrom: deltaSeq, done: true,
        turnItems: [item("obsolete", { terminal: true, status: "completed" })] })))
        .toEqual({ layer: initial, needsRefresh: true });
    }
    const covered = stream.apply(event({ deltaSeq: 6, deltaSeqFrom: 6, done: true,
      turnItems: [item("complete", { terminal: true, status: "completed" })] }));
    expect(covered.layer?.turnItems[0]).toMatchObject({ text: "complete" });
    expect(covered.layer?.status).toBe("completed");
  });

  it("does not treat terminal reasoning or tool rows as a completed answer", () => {
    for (const type of ["reasoning", "tool_call"] as const) {
      const stream = createLauncherAssistantStream("session-1");
      const extra = item("process", { type, itemId: "process", id: "process-r1",
        ...(type === "tool_call" ? { callId: "call-1", toolName: "read_file", input: "path" } : {}) });
      const initial = stream.apply(event({ turnItems: [item(), extra] })).layer;
      stream.apply(appendEvent(3, 5, " lost"));
      expect(stream.apply(event({ deltaSeq: 4, deltaSeqFrom: 4, done: true,
        turnItems: [item(), { ...extra, terminal: true, status: "completed" }] })))
        .toEqual({ layer: initial, needsRefresh: true });
    }
  });

  it("does not let a rejected stale-ledger frame poison terminal recovery sequence coverage", () => {
    const stream = createLauncherAssistantStream("session-1");
    const initial = stream.apply(event()).layer;
    expect(stream.apply(event({ deltaSeq: 100, deltaSeqFrom: 100, ledgerSeq: 9 })))
      .toEqual({ layer: initial, needsRefresh: false });
    stream.apply(appendEvent(3, 5, " lost"));
    expect(stream.apply(event({ deltaSeq: 4, deltaSeqFrom: 4, done: true,
      turnItems: [item("complete", { terminal: true, status: "completed" })] })).layer?.status)
      .toBe("completed");
  });

  it("requires canonical detail after a capped frame with unknown sequence coverage", () => {
    const stream = createLauncherAssistantStream("session-1");
    const initial = stream.apply(event()).layer;
    stream.apply({ type: "assistant_delta", sessionId: "session-1", turnId: "turn-1", at: 2,
      ledgerSeq: 10, needsRefresh: true });
    expect(stream.apply(event({ deltaSeq: 4, deltaSeqFrom: 4, done: true,
      turnItems: [item("complete", { terminal: true, status: "completed" })] })))
      .toEqual({ layer: initial, needsRefresh: true });
  });

  it("keeps epoch recovery and incomplete terminal frames behind a fresh detail read", () => {
    const stream = createLauncherAssistantStream("session-1");
    const reasoning = item("think", { type: "reasoning", itemId: "reason", id: "reason-r1" });
    const initial = stream.apply(event({ turnItems: [item(), reasoning] })).layer;
    stream.apply(appendEvent(3, 5, " lost", { ledgerSeq: 12 }));
    expect(stream.apply(event({ deltaSeq: 4, deltaSeqFrom: 4, ledgerSeq: 13, done: true,
      turnItems: [item("partial", { terminal: true, status: "completed" })] })))
      .toEqual({ layer: initial, needsRefresh: true });
    stream.apply({ type: "heartbeat", sessionId: "session-1", at: 1, connectionEpoch: 1 });
    expect(stream.apply(event({ connectionEpoch: 1, deltaSeq: 1, ledgerSeq: 14, done: true,
      turnItems: [item("new epoch", { terminal: true, status: "completed" }), reasoning] })))
      .toEqual({ layer: initial, needsRefresh: true });
  });

  it("reuses native full → append → append → done with reasoning and tool rows intact", () => {
    const stream = createLauncherAssistantStream("session-1");
    const reasoning = item("think", { type: "reasoning", id: "reason-r1", itemId: "reason", sequence: 2, status: "pending" });
    const tool = item("", { type: "tool_call", id: "tool-r1", itemId: "tool", sequence: 3,
      callId: "call-1", toolName: "read_file", input: "path", output: "result" });
    const first = stream.apply(event({ turnItems: [item(), reasoning, tool] }));
    expect(first.needsRefresh).toBe(false);
    expect(first.layer?.turnItems).toEqual([item(), reasoning, tool]);
    const second = stream.apply(appendEvent(2, 5, " world", { turnItemAppends: [append(5, " world"),
      append(5, " more", { itemId: "reason", itemType: "reasoning" })] }));
    expect(second.layer?.turnItems).toContainEqual({ ...reasoning, text: "think more" });
    const third = stream.apply(appendEvent(3, 11, "!"));
    expect(third.layer?.turnItems[0]).toEqual(item("hello world!"));
    expect(third.layer?.turnItems).toHaveLength(3);
    const doneReasoning = { ...reasoning, status: "completed" as const, revision: 2, text: "think more", terminal: true };
    const doneTool = { ...tool, status: "failed" as const, revision: 2, terminal: true,
      durationMs: 250, error: { code: "FILE_NOT_FOUND", message: "Missing file" } };
    const final = stream.apply(event({ deltaSeq: 4, deltaSeqFrom: 4, done: true, ledgerSeq: 12,
      turnItems: [item("hello world!", { status: "completed", terminal: true, revision: 2 }), doneReasoning, doneTool] }));
    expect(final.needsRefresh).toBe(true);
    expect(final.layer?.status).toBe("completed");
    expect(activeTurnLayerToConversationMessage(final.layer)?.turnItems).toHaveLength(3);
    expect(final.layer?.turnItems.map(row => row.itemId)).toEqual(["answer", "reason", "tool"]);
    expect(final.layer?.turnItems).toContainEqual(doneReasoning);
    expect(final.layer?.turnItems).toContainEqual(doneTool);
  });

  it("drops foreign sessions, duplicate append delivery, and out-of-order deltas", () => {
    const stream = createLauncherAssistantStream("session-1");
    expect(stream.apply(event({ sessionId: "other" })).layer).toBeUndefined();
    stream.apply(event());
    const advanced = stream.apply(appendEvent(2, 5, " world")).layer;
    expect(stream.apply(appendEvent(2, 5, " world"))).toEqual({ layer: advanced, needsRefresh: false });
    expect(stream.apply(event())).toEqual({ layer: advanced, needsRefresh: false });
    expect(stream.apply(event({ ledgerSeq: 9, deltaSeq: 3, deltaSeqFrom: 3 }))).toEqual({ layer: advanced, needsRefresh: false });
  });

  it("resets seq100 on a new connection only after fresh detail and rejects delayed retired-epoch frames", () => {
    const stream = createLauncherAssistantStream("session-1");
    const heartbeat = (connectionEpoch: number): LauncherAssistantSessionEvent => ({ type: "heartbeat", sessionId: "session-1", at: 1, connectionEpoch });
    expect(stream.apply(heartbeat(1)).needsRefresh).toBe(true);
    const previousDetail = detail([item()]);
    stream.reconcile(previousDetail);
    const old = stream.apply(event({ connectionEpoch: 1, deltaSeq: 100, deltaSeqFrom: 100, turnItems: [item("hello old")] })).layer;
    expect(old?.turnItems[0]).toMatchObject({ text: "hello old" });
    expect(stream.apply(heartbeat(2), previousDetail)).toEqual({ layer: old, needsRefresh: true });
    expect(stream.apply(event({ connectionEpoch: 2 }), previousDetail).needsRefresh).toBe(true);
    // React Query may structurally share an unchanged successful GET. Explicit
    // reconcile still marks that fresh read, unlike apply's cached detail hint.
    stream.reconcile(previousDetail);
    const fresh = stream.apply(event({ connectionEpoch: 2, deltaSeq: 1, deltaSeqFrom: 1, turnItems: [item("hello new")] }));
    expect(fresh.needsRefresh).toBe(false);
    expect(fresh.layer?.turnItems[0]).toMatchObject({ text: "hello new" });
    const grown = stream.apply(appendEvent(2, 9, "!", { connectionEpoch: 2 }));
    expect(grown.needsRefresh).toBe(false);
    expect(grown.layer?.turnItems[0]).toMatchObject({ text: "hello new!" });
    expect(stream.apply(event({ connectionEpoch: 1, deltaSeq: 101, deltaSeqFrom: 101, ledgerSeq: 100,
      turnItems: [item("obsolete")] }))).toEqual({ layer: grown.layer, needsRefresh: false });
    expect(stream.apply(event())).toEqual({ layer: grown.layer, needsRefresh: false });
    expect(stream.apply(appendEvent(4, 10, " lost", { connectionEpoch: 2, ledgerSeq: 11 })).needsRefresh).toBe(true);
    stream.reconcile(detail([item("hello new! lost")], { ledgerSeq: 11 }));
    const recovered = stream.apply(appendEvent(5, 15, "!", { connectionEpoch: 2, ledgerSeq: 11 }));
    expect(recovered.needsRefresh).toBe(false);
    expect(recovered.layer?.turnItems[0]).toMatchObject({ text: "hello new! lost!" });
  });

  it("recovers when the first frame after native restart is the reset full delta itself", () => {
    const stream = createLauncherAssistantStream("session-1");
    stream.apply({ type: "heartbeat", sessionId: "session-1", at: 1, connectionEpoch: 1 });
    stream.reconcile(detail());
    stream.apply(event({ connectionEpoch: 1, deltaSeq: 100, deltaSeqFrom: 100 }));
    expect(stream.apply(event({ connectionEpoch: 2, turnItems: [item("hello restart")] })).needsRefresh).toBe(true);
    stream.reconcile(detail([item("hello restart")]));
    const grown = stream.apply(appendEvent(2, 13, "!", { connectionEpoch: 2 }));
    expect(grown.needsRefresh).toBe(false);
    expect(grown.layer?.turnItems[0]).toMatchObject({ text: "hello restart!" });
  });

  it("normalizes the first new-epoch append against fresh authority rather than the retired decoder layer", () => {
    const stream = createLauncherAssistantStream("session-1");
    stream.apply({ type: "heartbeat", sessionId: "session-1", at: 1, connectionEpoch: 1 });
    stream.reconcile(detail());
    stream.apply(event({ connectionEpoch: 1, turnItems: [item("seed")] }));
    stream.apply({ type: "heartbeat", sessionId: "session-1", at: 2, connectionEpoch: 2 });
    stream.reconcile(detail([item("🐳abc")]));
    const next = stream.apply(appendEvent(1, 4, "继续", { connectionEpoch: 2 }));
    expect(next.needsRefresh).toBe(false);
    expect(next.layer?.turnItems[0]).toMatchObject({ text: "🐳abc继续" });
  });

  it.each([false, true])("keeps retired-epoch text out of the baseline after a non-answer delta (reasoning=%s)", reasoning => {
    const stream = createLauncherAssistantStream("session-1");
    stream.apply({ type: "heartbeat", sessionId: "session-1", at: 1, connectionEpoch: 1 });
    stream.reconcile(detail());
    stream.apply(event({ connectionEpoch: 1, turnItems: [item("seed")] }));
    stream.apply({ type: "heartbeat", sessionId: "session-1", at: 2, connectionEpoch: 2 });
    stream.reconcile(detail([item("🐳abc")]));
    stream.apply(event({ connectionEpoch: 2, turnItems: reasoning
      ? [item("think", { type: "reasoning", itemId: "reason", id: "reason-r1" })] : [] }));
    const next = stream.apply(appendEvent(2, 4, "继续", { connectionEpoch: 2 }));
    expect(next.needsRefresh).toBe(false);
    expect(next.layer?.turnItems).toContainEqual(expect.objectContaining({ itemId: "answer", text: "🐳abc继续" }));
  });

  it("validates and preserves only positive bounded connection epochs at the IPC boundary", () => {
    expect(parseLauncherAssistantSessionEvent(event({ connectionEpoch: 2 }))).toMatchObject({ connectionEpoch: 2 });
    for (const connectionEpoch of [0, -1, 1.5, Number.MAX_SAFE_INTEGER + 1, "2", Number.NaN]) {
      expect(parseLauncherAssistantSessionEvent({ ...event(), connectionEpoch })).toBeNull();
    }
  });

  it("holds a deltaSeq gap, rebases from detail, then accepts the next real append", () => {
    const stream = createLauncherAssistantStream("session-1");
    const initial = detail();
    const first = stream.apply(event(), initial).layer;
    expect(stream.apply(appendEvent(3, 11, "!", { ledgerSeq: 12 }), initial)).toEqual({ layer: first, needsRefresh: true });
    stream.reconcile(detail([item("hello world!")], { ledgerSeq: 12 }));
    const next = stream.apply(appendEvent(4, 12, " Again", { ledgerSeq: 13 }));
    expect(next.needsRefresh).toBe(false);
    expect(next.layer?.turnItems).toEqual([item("hello world! Again")]);
  });

  it("recovers an append baseline gap through canonical rows without creating a new item", () => {
    const stream = createLauncherAssistantStream("session-1");
    expect(stream.apply(appendEvent(1, 5, " world")).needsRefresh).toBe(true);
    stream.reconcile(detail([item("hello world")]));
    const next = stream.apply(appendEvent(2, 11, "!"));
    expect(next.needsRefresh).toBe(false);
    expect(next.layer?.turnItems).toEqual([item("hello world!")]);
  });

  it("keeps a growing same-turn decoder through older and equal-ledger detail snapshots", () => {
    const stream = createLauncherAssistantStream("session-1");
    const snapshot = detail([item("hello")]);
    stream.reconcile(snapshot);
    stream.apply(event());
    stream.apply(appendEvent(2, 5, " world"));
    stream.reconcile({ ...snapshot });
    stream.reconcile(detail([item("he")], { ledgerSeq: 9 }));
    expect(stream.apply(appendEvent(3, 11, "!")).layer?.turnItems).toEqual([item("hello world!")]);
  });

  it("removes only canonical-covered items and keeps their full native append baseline", () => {
    const stream = createLauncherAssistantStream("session-1");
    const reason = item("think", { type: "reasoning", id: "reason-r1", itemId: "reason", sequence: 2 });
    stream.apply(event({ turnItems: [item(), reason] }));
    const snapshot = detail([item()]);
    const residual = stream.reconcile(snapshot);
    expect(residual?.turnItems).toEqual([reason]);
    const painted = [...snapshot.messages.flatMap(row => row.turnItems ?? []), ...(residual?.turnItems ?? [])];
    expect(painted.map(row => row.itemId)).toEqual(["answer", "reason"]);
    const next = stream.apply(appendEvent(2, 5, " world"), snapshot);
    expect(next.needsRefresh).toBe(false);
    expect(next.layer?.turnItems.map(row => row.itemId)).toEqual(["answer", "reason"]);
    expect(next.layer?.turnItems[0]).toEqual(item("hello world"));
  });

  it("shares actual native overlay item IDs so the ConversationView projection paints each item once", () => {
    const stream = createLauncherAssistantStream("session-1");
    const reason = item("think", { type: "reasoning", id: "reason-r1", itemId: "reason", sequence: 2 });
    const live = message([item(), reason], { id: "session-1-message-live-turn-1",
      metadata: { kind: "session_live_overlay", turnId: "turn-1" } });
    const snapshot = detail([], { messages: [live] });
    stream.reconcile(snapshot);
    stream.apply(event({ turnItems: [item(), reason] }));
    const next = stream.apply(appendEvent(2, 5, " world"));
    const projection = projectAgentMessageTimelineMessages({ timelineMessages: snapshot.messages,
      activeTurnMessage: activeTurnLayerToConversationMessage(next.layer) });
    const painted = projection.messages.flatMap(row => row.turnItems ?? []);
    expect(painted.map(row => row.itemId)).toEqual(["answer", "reason"]);
    expect(painted[0]).toMatchObject({ text: "hello world" });
  });

  it("seeds append decoding from the ordinary metadata turn identity, including live: aliases", () => {
    const stream = createLauncherAssistantStream("session-1");
    stream.reconcile(detail([], { messages: [message([item()], { turnId: undefined,
      metadata: { turnId: "live:turn-1", kind: "session_live_overlay" } })] }));
    expect(stream.apply(appendEvent(1, 5, " world")).layer?.turnItems).toEqual([item("hello world")]);
  });

  it("retires the layer only when the durable terminal transcript replaces it", () => {
    const stream = createLauncherAssistantStream("session-1");
    const terminal = item("done", { status: "completed", terminal: true, revision: 2 });
    stream.apply(event({ turnItems: [terminal], done: true, ledgerSeq: 12 }));
    expect(stream.reconcile(detail([terminal], { ledgerSeq: 11,
      messages: [message([terminal], { status: "completed" })] }))).toBeDefined();
    expect(stream.reconcile(detail([terminal], { ledgerSeq: 12, activeTurnId: "", currentPhase: "ready", status: "ready",
      messages: [message([terminal], { status: "completed" })] }))).toBeUndefined();
    expect(stream.apply(event({ deltaSeq: 2, deltaSeqFrom: 2, ledgerSeq: 13 })).layer).toBeUndefined();
  });

  it("rejects a retired different turn even when its delayed frame has a newer sequence", () => {
    const stream = createLauncherAssistantStream("session-1");
    stream.apply(event());
    const next = stream.apply(event({ turnId: "turn-2", ledgerSeq: 20, deltaSeq: 2, deltaSeqFrom: 2,
      turnItems: [item("new", { turnId: "turn-2", id: "new-r1", itemId: "new" })] })).layer;
    expect(stream.apply(event({ ledgerSeq: 21, deltaSeq: 3, deltaSeqFrom: 3 }))).toEqual({ layer: next, needsRefresh: false });
  });

  it("requires explicit detail recovery for identity-only/capped frames and never uses textPreview", () => {
    const stream = createLauncherAssistantStream("session-1");
    const previous = stream.apply(event()).layer;
    expect(stream.apply({ type: "assistant_delta", sessionId: "session-1", turnId: "turn-1", at: 2,
      ledgerSeq: 11, needsRefresh: true })).toEqual({ layer: previous, needsRefresh: true });
    expect(stream.apply(appendEvent(2, 5, " world")).needsRefresh).toBe(true);
    stream.reconcile(detail([item("hello world")], { ledgerSeq: 11 }));
    expect(stream.apply(appendEvent(3, 11, "!", { ledgerSeq: 11 })).layer?.turnItems).toEqual([item("hello world!")]);
    const parsed = parseLauncherAssistantSessionEvent({ ...event(), textPreview: "fabricated", token: "secret", origin: "http://host" });
    expect(parsed).not.toHaveProperty("textPreview");
    expect(parsed).not.toHaveProperty("token");
    expect(parsed).not.toHaveProperty("origin");
    expect(parseLauncherAssistantSessionEvent(event({ turnItems: [item("中".repeat(100_000))] }))).toMatchObject({ needsRefresh: true });
  });
});
