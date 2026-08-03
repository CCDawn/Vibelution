import { describe, expect, it, beforeEach } from "vitest";

import {
  clearSessionDeleteTombstone,
  filterOutTombstonedConversations,
  filterOutTombstonedSessions,
  isSessionDeleteTombstoned,
  markSessionDeleteTombstone,
  resetSessionDeleteTombstonesForTests,
} from "./sessionDeleteTombstone";

describe("sessionDeleteTombstone", () => {
  beforeEach(() => {
    resetSessionDeleteTombstonesForTests();
  });

  it("marks and filters tombstoned sessions", () => {
    markSessionDeleteTombstone("session-a");
    expect(isSessionDeleteTombstoned("session-a")).toBe(true);
    expect(isSessionDeleteTombstoned("session-b")).toBe(false);
    expect(
      filterOutTombstonedSessions([
        { id: "session-a" },
        { id: "session-b" },
      ]),
    ).toEqual([{ id: "session-b" }]);
  });

  it("filters conversations by directSessionId or conversationId", () => {
    markSessionDeleteTombstone("session-x");
    expect(
      filterOutTombstonedConversations([
        { conversationId: "session-x", directSessionId: "session-x" },
        { conversationId: "session-y", directSessionId: "session-y" },
      ]),
    ).toEqual([{ conversationId: "session-y", directSessionId: "session-y" }]);
  });

  it("expires tombstones after ttl", () => {
    const now = 1_000_000;
    markSessionDeleteTombstone("session-old", { nowMs: now });
    expect(isSessionDeleteTombstoned("session-old", { nowMs: now + 1000, ttlMs: 5000 })).toBe(true);
    expect(isSessionDeleteTombstoned("session-old", { nowMs: now + 6000, ttlMs: 5000 })).toBe(false);
  });

  it("clears tombstones on failed delete recovery", () => {
    markSessionDeleteTombstone("session-a");
    clearSessionDeleteTombstone("session-a");
    expect(isSessionDeleteTombstoned("session-a")).toBe(false);
  });
});
