import { describe, expect, it, beforeEach } from "vitest";

import type { SessionSummary } from "../api/types";
import {
  isSessionCreatePreserved,
  mergePreservedCreatedSessions,
  pinSessionCreatePreserve,
  resetSessionCreatePreservesForTests,
  takeSessionCreatePreserve,
  unpinSessionCreatePreserve,
} from "./sessionCreatePreserve";
import {
  markSessionDeleteTombstone,
  resetSessionDeleteTombstonesForTests,
} from "./sessionDeleteTombstone";

function session(id: string, title: string): SessionSummary {
  return {
    id,
    title,
    status: "ready",
    taskSummary: "",
    lastActive: "2026-08-15T08:00:00.000Z",
    updatedAt: "2026-08-15T08:00:00.000Z",
    currentPhase: "ready",
  };
}

describe("sessionCreatePreserve", () => {
  beforeEach(() => {
    resetSessionCreatePreservesForTests();
    resetSessionDeleteTombstonesForTests();
  });

  it("re-attaches a pinned create that the server page still omits", () => {
    pinSessionCreatePreserve(session("session-new", "Fresh"));
    const merged = mergePreservedCreatedSessions([session("session-old", "Old")]);
    expect(merged.map((item) => item.id)).toEqual(["session-new", "session-old"]);
  });

  it("clears the pin once the server list includes the created id", () => {
    pinSessionCreatePreserve(session("session-new", "Fresh"));
    const merged = mergePreservedCreatedSessions([
      session("session-new", "Fresh from server"),
      session("session-old", "Old"),
    ]);
    expect(merged.map((item) => item.id)).toEqual(["session-new", "session-old"]);
    expect(isSessionCreatePreserved("session-new")).toBe(false);
  });

  it("keeps local temp shells that are not server-addressable yet", () => {
    const merged = mergePreservedCreatedSessions([session("session-old", "Old")], {
      localItems: [session("temp-session-abc", "Optimistic")],
    });
    expect(merged.map((item) => item.id)).toEqual(["temp-session-abc", "session-old"]);
  });

  it("unpins explicitly so failed creates can drop from later merges", () => {
    pinSessionCreatePreserve(session("session-new", "Fresh"));
    unpinSessionCreatePreserve("session-new");
    const merged = mergePreservedCreatedSessions([session("session-old", "Old")]);
    expect(merged.map((item) => item.id)).toEqual(["session-old"]);
  });

  it("drops a pinned create once that session is deleted", () => {
    pinSessionCreatePreserve(session("session-new", "Fresh"));
    markSessionDeleteTombstone("session-new");
    const merged = mergePreservedCreatedSessions([session("session-old", "Old")], {
      localItems: [session("session-new", "Fresh")],
    });
    expect(merged.map((item) => item.id)).toEqual(["session-old"]);
    expect(isSessionCreatePreserved("session-new")).toBe(false);
  });

  it("does not reattach a deleted temp shell", () => {
    markSessionDeleteTombstone("temp-session-abc");
    const merged = mergePreservedCreatedSessions([session("session-old", "Old")], {
      localItems: [session("temp-session-abc", "Optimistic")],
    });
    expect(merged.map((item) => item.id)).toEqual(["session-old"]);
  });

  it("omits a server row the user already deleted", () => {
    markSessionDeleteTombstone("session-new");
    const merged = mergePreservedCreatedSessions([
      session("session-new", "Fresh from server"),
      session("session-old", "Old"),
    ]);
    expect(merged.map((item) => item.id)).toEqual(["session-old"]);
    expect(isSessionCreatePreserved("session-new")).toBe(false);
  });

  it("returns a taken pin so a failed delete can restore it", () => {
    pinSessionCreatePreserve(session("session-new", "Fresh"));
    const taken = takeSessionCreatePreserve("session-new");
    expect(taken?.id).toBe("session-new");
    expect(isSessionCreatePreserved("session-new")).toBe(false);
    pinSessionCreatePreserve(taken!);
    expect(isSessionCreatePreserved("session-new")).toBe(true);
  });
});
