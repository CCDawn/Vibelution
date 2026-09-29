import { describe, expect, it } from "vitest";
import { QueryClient } from "@tanstack/react-query";
import type { ConversationMessage, SessionDetail } from "../../api/types";
import { applyOptimisticEditResubmit, mergeSessionDetailMessageWindow } from "../chatSessionState";
import { mergeStickySessionDetailPaint } from "./chatSessionPaintCache";
import { rollbackEditResubmit, supersededEditDelta } from "./chatEditResubmitState";

const msg = (index: number, role: "user" | "assistant", content: string, turnId = "old"): ConversationMessage => ({
  id: `s-message-${index}`, role, content, metadata: { messageIndex: index, turnId },
});
const original = (): SessionDetail => ({
  id: "s", ledgerSeq: 10, status: "ready", currentPhase: "ready",
  messages: [msg(101, "user", "earlier", "earlier"), msg(102, "assistant", "kept", "earlier"),
    msg(103, "user", "original"), msg(104, "assistant", "stopped")],
  messageWindow: { totalMessages: 104, returnedMessages: 4, oldestMessageIndex: 101,
    newestMessageIndex: 104, hasEarlier: true, hasLater: false, nextBeforeMessageIndex: 101 },
} as SessionDetail);
const edit = (detail = original(), id = "edit") => applyOptimisticEditResubmit(detail, {
  messageId: "s-message-103", content: "edited", clientSubmissionId: id,
})!;
const ack = (): SessionDetail => ({ ...original(), ledgerSeq: 20, currentPhase: "running", status: "running",
  messages: [msg(101, "user", "earlier", "earlier"), msg(102, "assistant", "kept", "earlier"),
    { ...msg(103, "user", "edited", "new"), metadata: { messageIndex: 103, turnId: "new", clientSubmissionId: "edit" } },
    msg(104, "assistant", "new reply", "new")],
});

describe("edit generation in query and paint caches", () => {
  it("immediately paints the rewritten user and preserves absolute paged indices", () => {
    const client = new QueryClient({ defaultOptions: { queries: {
      structuralSharing: (before, next) => mergeSessionDetailMessageWindow(before as SessionDetail, next as SessionDetail),
    } } });
    client.setQueryData(["s"], original());
    client.setQueryData(["s"], edit());
    const cached = client.getQueryData<SessionDetail>(["s"])!;
    const painted = mergeStickySessionDetailPaint(original(), cached);
    expect(painted.messages.map((item) => item.content)).toEqual(["earlier", "kept", "edited"]);
    expect(painted.messageWindow).toMatchObject({ totalMessages: 103, newestMessageIndex: 103,
      returnedMessages: 3, oldestMessageIndex: 101, hasEarlier: true });
    client.clear();
  });

  it("does not resurrect the tail through a non-windowed sticky cache or late page without the target", () => {
    const stale = { ...original(), messageWindow: undefined };
    const painted = mergeStickySessionDetailPaint(stale, edit());
    const latePage = { ...stale, messages: [msg(104, "assistant", "stopped")] };
    expect(mergeStickySessionDetailPaint(painted, latePage).messages.map((item) => item.content))
      .toEqual(["earlier", "kept", "edited"]);
  });

  it("accepts the new reply and rejects old snapshots and deltas after acknowledgement", () => {
    const accepted = mergeStickySessionDetailPaint(edit(), { ...ack(), messageWindow: undefined });
    expect(accepted.messages.at(-1)?.content).toBe("new reply");
    for (const stale of [original(), { ...original(), ledgerSeq: undefined }, { ...original(), ledgerSeq: 20 }]) {
      expect(mergeSessionDetailMessageWindow(accepted, stale).messages.at(-1)?.content).toBe("new reply");
    }
    expect(supersededEditDelta(accepted.editResubmitProtection, "old", 10)).toBe(true);
    expect(supersededEditDelta(accepted.editResubmitProtection, "new", 21)).toBe(false);
    const switched = { ...original(), ledgerSeq: 30 };
    expect(mergeSessionDetailMessageWindow(accepted, switched).messages.at(-1)?.content).toBe("stopped");
  });

  it("keeps the edited boundary across repeated windowed paint merges", () => {
    const pending = mergeSessionDetailMessageWindow(original(), edit());
    const painted = mergeStickySessionDetailPaint(pending, original());
    const repainted = mergeStickySessionDetailPaint(painted, original());
    expect(repainted.messages.map((item) => item.content)).toEqual(["earlier", "kept", "edited"]);
    expect(repainted.messageWindow).toMatchObject({ totalMessages: 103, newestMessageIndex: 103 });
    expect(repainted.currentPhase).toBe(pending.currentPhase);
  });

  it("restores failed edits through sticky painting but refuses a rollback of an acknowledged edit", () => {
    const pending = mergeSessionDetailMessageWindow(original(), edit());
    const rollback = rollbackEditResubmit(pending, original(), "edit")!;
    expect(mergeStickySessionDetailPaint(pending, rollback).messages.at(-1)?.content).toBe("stopped");
    const accepted = mergeSessionDetailMessageWindow(pending, ack());
    expect(rollbackEditResubmit(accepted, original(), "edit")).toBe(accepted);
  });

  // Nail: the onError rollback is NOT subject to the union-merge resurrection
  // bug (fxl-0022 family). Two independent reasons, both pinned here:
  // 1. the write carries editResubmitProtection.phase === "rolled_back", and
  //    mergeEditResubmitDetail short-circuits that phase with replace
  //    semantics (returns next verbatim, union never runs) — so even genuine
  //    removals land instead of being resurrected from previous;
  // 2. the restore direction is additive: the pre-edit snapshot is a superset
  //    of the tail-hidden pending cache.
  it("rolls a failed edit back through the query structural-sharing chain with replace semantics", () => {
    const client = new QueryClient({ defaultOptions: { queries: {
      structuralSharing: (before, next) => mergeSessionDetailMessageWindow(before as SessionDetail, next as SessionDetail),
    } } });
    client.setQueryData(["s"], original());
    client.setQueryData(["s"], edit());
    // While the request is in flight a late earlier page lands inside the
    // guarded prefix (index 100 < target 103) — a row the pre-edit snapshot
    // does not carry. The rollback below must genuinely remove it.
    client.setQueryData(["s"], { ...original(), ledgerSeq: 11,
      messages: [msg(100, "user", "late page"), msg(101, "user", "earlier", "earlier"),
        msg(102, "assistant", "kept", "earlier")] });
    const pending = client.getQueryData<SessionDetail>(["s"])!;
    expect(pending.messages.map((item) => item.content)).toEqual(["late page", "earlier", "kept", "edited"]);

    // Exactly what editResubmitMutation.onError writes through setQueryData.
    client.setQueryData(["s"], (current) => rollbackEditResubmit(current, original(), "edit"));
    const rolled = client.getQueryData<SessionDetail>(["s"])!;
    expect(rolled.messages.map((item) => item.content)).toEqual(["earlier", "kept", "original", "stopped"]);
    expect(rolled.messages.find((item) => item.id === "s-message-103")?.content).toBe("original");
    expect(rolled.editResubmitProtection?.phase).toBe("rolled_back");

    // Post-rollback poll: the server never saw the edit, so its snapshots are
    // original-shaped. The union may run again (guard now rolled_back), but
    // nothing resurrects the edited text or the superseded tail.
    client.setQueryData(["s"], { ...original(), ledgerSeq: 12 });
    const polled = client.getQueryData<SessionDetail>(["s"])!;
    expect(polled.messages.map((item) => item.content)).toEqual(["earlier", "kept", "original", "stopped"]);
    expect(polled.messages.some((item) => item.content === "edited")).toBe(false);
    client.clear();
  });
});
