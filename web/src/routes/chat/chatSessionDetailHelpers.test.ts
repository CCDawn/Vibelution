import { describe, expect, it } from "vitest";

import {
  buildSessionDetailShellFromSummary,
  isForeignSessionDetailQueryKey,
  isSessionNotFoundError,
  isStaleLedgerUpdate,
  resolveSessionDetailPlaceholder,
  sessionDetailSnapshotKey,
} from "./chatSessionDetailHelpers";
import type { SessionDetail, SessionSummary } from "../../api/types";

describe("chatSessionDetailHelpers", () => {
  it("detects session-not-found errors across locales", () => {
    expect(isSessionNotFoundError(new Error("Session not found"))).toBe(true);
    expect(isSessionNotFoundError(new Error("会话不存在"))).toBe(true);
    expect(isSessionNotFoundError(new Error("network down"))).toBe(false);
  });

  it("treats only strictly lower ledger seq as stale", () => {
    expect(isStaleLedgerUpdate(5, 4)).toBe(true);
    expect(isStaleLedgerUpdate(5, 5)).toBe(false);
    expect(isStaleLedgerUpdate(5, 6)).toBe(false);
    expect(isStaleLedgerUpdate(0, 1)).toBe(false);
  });

  it("builds a stable session detail snapshot key", () => {
    const detail = {
      id: "s1",
      status: "running",
      currentPhase: "answering",
      updatedAt: "t1",
      messages: [{ id: "m1", role: "assistant", content: "hi", streaming: false }],
    } as SessionDetail;
    expect(sessionDetailSnapshotKey(detail)).toContain("s1|running|answering|t1|1|m1|");
  });

  it("builds an empty detail shell from summary for optimistic switches", () => {
    const summary = {
      id: "s2",
      title: "Hello",
      status: "idle",
      currentPhase: "ready",
    } as SessionSummary;
    const shell = buildSessionDetailShellFromSummary(summary);
    expect(shell?.id).toBe("s2");
    expect(shell?.title).toBe("Hello");
    expect(shell?.messages).toEqual([]);
    expect(shell?.messageWindow?.hasEarlier).toBe(false);
  });

  it("prefers cached detail over summary shell and rejects foreign sessions", () => {
    const cached = { id: "s2", title: "Cached", messages: [{ id: "m" }] } as SessionDetail;
    const summary = { id: "s2", title: "Summary" } as SessionSummary;
    expect(
      resolveSessionDetailPlaceholder({
        activeSessionId: "s2",
        cachedDetail: cached,
        summary,
      })?.title,
    ).toBe("Cached");
    expect(
      resolveSessionDetailPlaceholder({
        activeSessionId: "s2",
        cachedDetail: { id: "other", title: "Nope" } as SessionDetail,
        summary,
      })?.title,
    ).toBe("Summary");
    expect(
      resolveSessionDetailPlaceholder({
        activeSessionId: "s2",
        cachedDetail: undefined,
        summary: { id: "other", title: "Nope" } as SessionSummary,
      }),
    ).toBeUndefined();
  });

  it("detects foreign session detail query keys for cancel-on-switch", () => {
    expect(isForeignSessionDetailQueryKey(["sessions", "old"], "new")).toBe(true);
    expect(isForeignSessionDetailQueryKey(["sessions", "new"], "new")).toBe(false);
    expect(isForeignSessionDetailQueryKey(["sessions", "new", "child-sessions"], "new")).toBe(false);
    expect(isForeignSessionDetailQueryKey(["sessions", "none"], "new")).toBe(false);
  });
});
