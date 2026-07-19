import { describe, expect, it } from "vitest";

import {
  isSessionNotFoundError,
  isStaleLedgerUpdate,
  sessionDetailSnapshotKey,
} from "./chatSessionDetailHelpers";
import type { SessionDetail } from "../../api/types";

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
});
