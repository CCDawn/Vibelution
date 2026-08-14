import { describe, expect, it } from "vitest";

import {
  CHAT_AGENT_LAST_SESSION_STORAGE_KEY,
  lastSessionForAgent,
  normalizeAgentLastSessionMap,
  rememberAgentLastSession,
  resolveAgentOpenSessionId,
} from "./chatAgentSessionMemory";

describe("chatAgentSessionMemory", () => {
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
});
