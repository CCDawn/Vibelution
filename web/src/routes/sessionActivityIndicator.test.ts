import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  isSessionActivitySeen,
  markSessionActivitySeen,
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

  it("shows completed until marked seen, then none", () => {
    const session = { id: "s-done", status: "ready", updatedAt: "2026-01-01T00:00:00.000Z" };
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

  it("treats runtime-running as in-session even when status lags", () => {
    expect(resolveSessionActivityTone(
      { id: "s-lag", status: "ready", updatedAt: "t1" },
      { isRuntimeRunning: true },
    )).toBe("running");
  });
});
