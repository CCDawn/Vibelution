import { describe, expect, it } from "vitest";

import type { SessionSummary } from "../../api/types";
import {
  buildSessionsById,
  mergeAllVisibleSessions,
  resolveActiveSessionAgentId,
  resolveActivitySeenSessionSources,
} from "./chatVisibleSessionCatalogModel";

function session(overrides: Partial<SessionSummary> = {}): SessionSummary {
  return {
    id: "session-1",
    title: "Session",
    agentId: "agent-1",
    status: "ready",
    taskSummary: "",
    lastActive: "",
    updatedAt: "",
    currentPhase: "complete",
    ...overrides,
  };
}

describe("chatVisibleSessionCatalogModel", () => {
  it("mergeAllVisibleSessions dedupes, filters archived agents, and merges child sessions", () => {
    const pendingArchiveAgentIds = new Set(["agent-archived"]);
    const merged = mergeAllVisibleSessions(
      [session({ id: "s1", agentId: "agent-1" }), session({ id: "s1", agentId: "agent-1" })],
      [session({ id: "s2", agentId: "agent-2", parentSessionId: "root", rootSessionId: "root" })],
      pendingArchiveAgentIds,
    );
    expect(merged.map((item) => item.id)).toEqual(["s1", "s2"]);

    const withoutArchived = mergeAllVisibleSessions(
      [session({ id: "s3", agentId: "agent-archived" })],
      [],
      pendingArchiveAgentIds,
    );
    expect(withoutArchived).toEqual([]);
  });

  it("resolveActiveSessionAgentId prefers detail, then direct summary, then directory", () => {
    const sessionsById = buildSessionsById([session({ id: "s1", agentId: "agent-directory" })]);
    expect(resolveActiveSessionAgentId({
      sessionDetailAgentId: "agent-detail",
      directSessionActiveSummary: session({ id: "s1", agentId: "agent-direct" }),
      activeSessionId: "s1",
      sessionsById,
    })).toBe("agent-detail");
    expect(resolveActiveSessionAgentId({
      sessionDetailAgentId: undefined,
      directSessionActiveSummary: session({ id: "s1", agentId: "agent-direct" }),
      activeSessionId: "s1",
      sessionsById,
    })).toBe("agent-direct");
    expect(resolveActiveSessionAgentId({
      sessionDetailAgentId: undefined,
      directSessionActiveSummary: undefined,
      activeSessionId: "s1",
      sessionsById,
    })).toBe("agent-directory");
  });

  it("resolveActivitySeenSessionSources only includes matching active session snapshots", () => {
    const sessionsById = buildSessionsById([session({ id: "s1" })]);
    expect(resolveActivitySeenSessionSources(
      "s1",
      sessionsById,
      session({ id: "s1", agentId: "agent-detail" }) as never,
      session({ id: "other", agentId: "agent-other" }),
    )).toEqual([
      session({ id: "s1" }),
      undefined,
      session({ id: "s1", agentId: "agent-detail" }),
    ]);
  });
});
