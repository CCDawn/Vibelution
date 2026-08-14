import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  isSessionActivitySeen,
  markSessionActivitySeen,
  markSessionActivitySnapshotsSeen,
  resolveAgentActivityTone,
  resolveSessionActivityTone,
  sessionActivityStamp,
  sessionIsRunningStatus,
} from "./sessionActivityIndicator";

describe("sessionActivityIndicator", () => {
  beforeEach(() => {
    const store = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => {
        store.set(key, value);
      },
      removeItem: (key: string) => {
        store.delete(key);
      },
      clear: () => store.clear(),
    });
  });

  it("prioritizes approval over running and error over completed", () => {
    expect(resolveSessionActivityTone({ id: "s1", status: "running" }, { needsApproval: true })).toBe("approval");
    expect(resolveSessionActivityTone({ id: "s1", status: "failed" })).toBe("error");
    expect(resolveSessionActivityTone({ id: "s1", status: "running" })).toBe("running");
    expect(resolveAgentActivityTone(["completed", "running", "error"])).toBe("error");
    expect(resolveAgentActivityTone(["completed", "running"])).toBe("running");
  });

  it("does not treat historical ready sessions as unread completed", () => {
    expect(resolveSessionActivityTone({
      id: "s-ready",
      status: "ready",
      updatedAt: "2026-01-01T00:00:00.000Z",
    })).toBe("none");
  });

  it("does not treat recency-only updates as unread completed", () => {
    const previous = { id: "s-ready", status: "ready", taskSummary: "same reply", updatedAt: "t1" };
    markSessionActivitySeen(previous.id, sessionActivityStamp(previous));
    const updated = { id: "s-ready", status: "ready", taskSummary: "same reply", updatedAt: "t2" };
    expect(sessionActivityStamp(updated)).toBe(sessionActivityStamp(previous));
    expect(resolveSessionActivityTone(updated)).toBe("none");
  });

  it("shows unread completed when a previously read ready session gets a new preview", () => {
    const previous = { id: "s-ready", status: "ready", taskSummary: "turn 1" };
    markSessionActivitySeen(previous.id, sessionActivityStamp(previous));
    const updated = { id: "s-ready", status: "ready", taskSummary: "turn 2" };
    expect(resolveSessionActivityTone(updated)).toBe("completed");
    markSessionActivitySeen(updated.id, sessionActivityStamp(updated));
    expect(resolveSessionActivityTone(updated)).toBe("none");
  });

  it("keeps a session read when directory and detail use different completion identities", () => {
    const directory = { id: "s-open", status: "ready", taskSummary: "short preview" };
    const detail = { id: "s-open", status: "ready", taskSummary: "full assistant reply" };
    expect(markSessionActivitySnapshotsSeen(directory.id, [directory, detail])).toBe(true);
    expect(resolveSessionActivityTone(directory)).toBe("none");
    expect(resolveSessionActivityTone(detail)).toBe("none");
  });

  it("still honors a legacy single-string seen stamp", () => {
    const session = { id: "s-legacy", status: "completed", taskSummary: "old reply" };
    globalThis.localStorage.setItem(
      "vibelution.session-activity-seen.v1",
      JSON.stringify({ [session.id]: sessionActivityStamp(session) }),
    );
    expect(isSessionActivitySeen(session.id, sessionActivityStamp(session))).toBe(true);
    expect(resolveSessionActivityTone(session)).toBe("none");
  });

  it("shows completed until marked seen, then none", () => {
    const session = { id: "s-done", status: "completed", updatedAt: "2026-01-01T00:00:00.000Z" };
    expect(resolveSessionActivityTone(session)).toBe("completed");
    markSessionActivitySeen(session.id, sessionActivityStamp(session));
    expect(isSessionActivitySeen(session.id, sessionActivityStamp(session))).toBe(true);
    expect(resolveSessionActivityTone(session)).toBe("none");
  });

  it("hides completed indicator while the session is actively open", () => {
    expect(resolveSessionActivityTone(
      { id: "s-open", status: "completed", updatedAt: "t1" },
      { isActive: true },
    )).toBe("none");
  });

  it("detects running phases", () => {
    expect(sessionIsRunningStatus("tooling")).toBe(true);
    expect(sessionIsRunningStatus("ready")).toBe(false);
  });

  it("treats runtime-running as in-session while the status is not terminal", () => {
    expect(resolveSessionActivityTone(
      { id: "s-lag", updatedAt: "t1" },
      { isRuntimeRunning: true },
    )).toBe("running");
    expect(resolveSessionActivityTone(
      { id: "s-lag-phase", currentPhase: "idle", updatedAt: "t1" },
      { isRuntimeRunning: true },
    )).toBe("running");
  });

  it("does not let a stale runtime flag override a terminal authoritative status", () => {
    expect(resolveSessionActivityTone(
      { id: "s-stale", status: "ready", updatedAt: "t1" },
      { isRuntimeRunning: true },
    )).toBe("none");
    expect(resolveSessionActivityTone(
      { id: "s-stale-done", status: "done", updatedAt: "t1" },
      { isRuntimeRunning: true },
    )).toBe("completed");
  });

  it("keeps priority and hiding semantics when the stale runtime flag is set", () => {
    // Real live phases still win even when another field is terminal.
    expect(resolveSessionActivityTone(
      { id: "s-live", status: "ready", currentPhase: "tooling" },
      { isRuntimeRunning: true },
    )).toBe("running");
    // Approval and error still outrank the stale flag.
    expect(resolveSessionActivityTone(
      { id: "s-approve", status: "ready", updatedAt: "t1" },
      { isRuntimeRunning: true, needsApproval: true },
    )).toBe("approval");
    expect(resolveSessionActivityTone(
      { id: "s-error", currentPhase: "failed", updatedAt: "t1" },
      { isRuntimeRunning: true },
    )).toBe("error");
    // Seen/active completed semantics are preserved.
    expect(resolveSessionActivityTone(
      { id: "s-open", status: "completed", updatedAt: "t1" },
      { isRuntimeRunning: true, isActive: true },
    )).toBe("none");
  });
});
