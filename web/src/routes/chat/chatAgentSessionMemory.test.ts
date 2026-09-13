import { describe, expect, it } from "vitest";

import {
  CHAT_AGENT_LAST_SESSION_STORAGE_KEY,
  forgetAgentLastSession,
  forgetAgentLastSessionBySessionId,
  lastSessionForAgent,
  normalizeAgentLastSessionMap,
  rememberAgentLastSession,
  resolveAgentOpenSessionId,
} from "./chatAgentSessionMemory";
import { markSessionDeleteTombstone, resetSessionDeleteTombstonesForTests } from "../sessionDeleteTombstone";

describe("chatAgentSessionMemory", () => {
  function memoryStorage() {
    const storage = new Map<string, string>();
    return {
      storage,
      adapter: {
        getItem: (key: string) => storage.get(key) ?? null,
        setItem: (key: string, value: string) => {
          storage.set(key, value);
        },
      },
    };
  }

  it("prefers the last viewed session over a newer running session", () => {
    expect(resolveAgentOpenSessionId({
      lastSessionId: "session-viewed",
      knownSessionIds: ["session-viewed", "session-running"],
      latestSessionId: "session-running",
      directSessionId: "session-direct",
    })).toBe("session-viewed");
  });

  it("opens a last-viewed session even when it is not in the currently loaded set", () => {
    expect(resolveAgentOpenSessionId({
      lastSessionId: "session-child",
      knownSessionIds: ["session-running", "session-direct"],
      latestSessionId: "session-running",
      directSessionId: "session-direct",
    })).toBe("session-child");
  });

  it("falls back to the Agent direct session when nothing else is known", () => {
    expect(resolveAgentOpenSessionId({
      lastSessionId: "",
      knownSessionIds: [],
      latestSessionId: "",
      directSessionId: "session-direct",
    })).toBe("session-direct");
  });

  it("stores the last viewed session per Agent", () => {
    const storage = new Map<string, string>();
    const adapter = {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => {
        storage.set(key, value);
      },
    };
    rememberAgentLastSession("agent-a", "session-1", adapter);
    rememberAgentLastSession("agent-a", "session-2", adapter);
    rememberAgentLastSession("agent-b", "session-b", adapter);
    const map = normalizeAgentLastSessionMap(
      JSON.parse(adapter.getItem(CHAT_AGENT_LAST_SESSION_STORAGE_KEY) ?? "{}"),
    );
    expect(lastSessionForAgent("agent-a", map)).toBe("session-2");
    expect(lastSessionForAgent("agent-b", map)).toBe("session-b");
  });

  it("skips a tombstoned last-viewed session and falls back to a live candidate", () => {
    resetSessionDeleteTombstonesForTests();
    markSessionDeleteTombstone("session-deleted");
    try {
      expect(resolveAgentOpenSessionId({
        lastSessionId: "session-deleted",
        knownSessionIds: ["session-live"],
        latestSessionId: "session-live",
        directSessionId: "session-direct",
      })).toBe("session-live");
    } finally {
      resetSessionDeleteTombstonesForTests();
    }
  });

  it("does not reopen a tombstoned Agent direct session when nothing else is known", () => {
    resetSessionDeleteTombstonesForTests();
    markSessionDeleteTombstone("session-direct");
    try {
      expect(resolveAgentOpenSessionId({
        lastSessionId: "",
        knownSessionIds: [],
        latestSessionId: "",
        directSessionId: "session-direct",
      })).toBe("");
    } finally {
      resetSessionDeleteTombstonesForTests();
    }
  });

  it("forgets one Agent pointer without touching other Agents", () => {
    const { adapter, storage } = memoryStorage();
    rememberAgentLastSession("agent-a", "session-1", adapter);
    rememberAgentLastSession("agent-b", "session-2", adapter);

    forgetAgentLastSession("agent-a", adapter);

    const map = normalizeAgentLastSessionMap(
      JSON.parse(storage.get(CHAT_AGENT_LAST_SESSION_STORAGE_KEY) ?? "{}"),
    );
    expect(lastSessionForAgent("agent-a", map)).toBe("");
    expect(lastSessionForAgent("agent-b", map)).toBe("session-2");
  });

  it("forgets every pointer that references a deleted session", () => {
    const { adapter, storage } = memoryStorage();
    rememberAgentLastSession("agent-a", "session-deleted", adapter);
    rememberAgentLastSession("agent-b", "session-deleted", adapter);
    rememberAgentLastSession("agent-c", "session-keep", adapter);

    forgetAgentLastSessionBySessionId("session-deleted", adapter);

    const map = normalizeAgentLastSessionMap(
      JSON.parse(storage.get(CHAT_AGENT_LAST_SESSION_STORAGE_KEY) ?? "{}"),
    );
    expect(lastSessionForAgent("agent-a", map)).toBe("");
    expect(lastSessionForAgent("agent-b", map)).toBe("");
    expect(lastSessionForAgent("agent-c", map)).toBe("session-keep");
  });
});
