/** @vitest-environment happy-dom */

import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import {
  CHAT_AGENT_LAST_SESSION_STORAGE_KEY,
  lastSessionForAgent,
  normalizeAgentLastSessionMap,
  rememberAgentLastSession,
} from "./chat/chatAgentSessionMemory";
import { evictUnopenableSessionFromCaches } from "./chatSessionIndexQuery";
import { resetSessionDeleteTombstonesForTests } from "./sessionDeleteTombstone";

describe("evictUnopenableSessionFromCaches stale pointer cleanup", () => {
  it("drops last-viewed pointers that referenced the missing session", () => {
    resetSessionDeleteTombstonesForTests();
    window.localStorage.clear();
    rememberAgentLastSession("agent-a", "session-ghost", window.localStorage);
    rememberAgentLastSession("agent-b", "session-keep", window.localStorage);

    evictUnopenableSessionFromCaches(new QueryClient(), "session-ghost");

    const map = normalizeAgentLastSessionMap(
      JSON.parse(window.localStorage.getItem(CHAT_AGENT_LAST_SESSION_STORAGE_KEY) ?? "{}"),
    );
    expect(lastSessionForAgent("agent-a", map)).toBe("");
    expect(lastSessionForAgent("agent-b", map)).toBe("session-keep");
    window.localStorage.clear();
    resetSessionDeleteTombstonesForTests();
  });
});
