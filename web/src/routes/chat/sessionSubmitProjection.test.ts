import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import type { SessionDetail } from "../../api/types";
import { acceptSessionSubmit, beginSessionSubmit, mergeSessionSubmitDetail, removeSessionSubmitPaint, sameSubmittedReferenceSnapshot } from "./sessionSubmitProjection";

const input = { sessionId: "s", clientSubmissionId: "request-1", content: "hello", createdAt: "2026-11-06T02:00:00Z" };
const detail = (): SessionDetail => ({ id: "s", status: "ready", currentPhase: "ready", messages: [], queuedTurns: [] } as unknown as SessionDetail);

describe("shared native conversation submit projection", () => {
  it("keeps local paint through stale non-window detail until exactly one native row replaces it", () => {
    const pending = acceptSessionSubmit(beginSessionSubmit(detail(), input), input, { turnId: "turn-1" })!;
    const stale = mergeSessionSubmitDetail(pending, detail());
    expect(stale.messages).toHaveLength(1);
    expect(stale.messages[0].metadata).toMatchObject({ optimisticUserMessage: true, pending: false, turnId: "turn-1" });
    const native = { ...detail(), messages: [{ id: "native", role: "user", content: "hello", timestamp: input.createdAt,
      metadata: { clientSubmissionId: input.clientSubmissionId, turnId: "turn-1" } }] } as SessionDetail;
    expect(mergeSessionSubmitDetail(stale, native).messages.map(row => row.id)).toEqual(["native"]);
    expect(mergeSessionSubmitDetail(stale, { ...detail(), id: "other" }).messages).toEqual([]);
  });

  it("uses native queue identity immediately without creating a new running user/turn", () => {
    const busy = { ...detail(), status: "running", activeTurnId: "existing" } as SessionDetail;
    expect(beginSessionSubmit(busy, input, true)).toBe(busy);
    const receipt = { turnId: "", queuedTurnId: "queue-1", queuePosition: 2 };
    const queued = acceptSessionSubmit(busy, input, receipt)!;
    expect(queued.messages).toEqual([]);
    expect(queued.activeTurnId).toBe("existing");
    expect(queued.queuedTurns).toEqual([expect.objectContaining({ id: "queue-1", content: "hello", position: 2, clientSubmissionId: "request-1" })]);
    expect(acceptSessionSubmit(queued, input, receipt)?.queuedTurns).toHaveLength(1);
    expect(acceptSessionSubmit({ id: "s", queuedTurns: [] } as unknown as SessionDetail, input, receipt)?.queuedTurns).toHaveLength(1);
  });

  it("removes only its own optimistic paint even under window-union structural sharing", () => {
    const client = new QueryClient();
    const key = ["launcher-assistant", "detail", "s"];
    client.setQueryDefaults(key, { structuralSharing: (previous, next) => mergeSessionSubmitDetail(previous as SessionDetail | undefined, next as SessionDetail) });
    const first = beginSessionSubmit(detail(), input);
    client.setQueryData(key, beginSessionSubmit(first, { ...input, clientSubmissionId: "request-2", content: "newer" }));
    removeSessionSubmitPaint(client, key, input);
    expect(client.getQueryData<SessionDetail>(key)?.messages.map(row => row.content)).toEqual(["newer"]);
    client.clear();
  });

  it("retains a reference re-quoted while the original snapshot was sending", () => {
    const quote = { kind: "message", referenceId: "m", sourceSessionId: "s2", sourceMessageId: "m1", quote: "old" };
    expect(sameSubmittedReferenceSnapshot({ ...quote }, quote)).toBe(true);
    expect(sameSubmittedReferenceSnapshot({ ...quote, quote: "new" }, quote)).toBe(false);
  });
});
