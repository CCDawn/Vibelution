import { describe, expect, it } from "vitest";
import type { SessionSummary } from "../api/types";
import { recentAgentSessions } from "./agentSessionHistory";

function shell(id: string, updatedAt: string): SessionSummary {
  return {
    id, title: id, status: "idle", taskSummary: "", currentPhase: "ready",
    lastActive: updatedAt, updatedAt,
  };
}

const sessions = Array.from({ length: 100 }, (_, i) => ({
  id: `session-${i}`, title: `讨论 ${i}`, taskSummary: i === 12 ? "来源核验" : "", updatedAt: new Date(i * 1000).toISOString(),
})) as SessionSummary[];

describe("agent session history", () => {
  it("keeps five recent sessions and the active/renaming targets without deleting history", () => {
    const visible = recentAgentSessions(sessions, ["session-12", "session-13"]);
    expect(visible.map(s => s.id)).toEqual(["session-12", "session-13", "session-95", "session-96", "session-97", "session-98", "session-99"]);
    expect(sessions).toHaveLength(100);
    expect(sessions[0].id).toBe("session-0");
  });

  it("keeps an unfinished temp shell outside the five most recently updated rows", () => {
    const visible = recentAgentSessions([
      shell("temp-session-old", "1970-01-01T00:00:00.000Z"),
      ...sessions,
    ], []);
    expect(visible.map((item) => item.id)).toEqual([
      "temp-session-old", "session-95", "session-96", "session-97", "session-98", "session-99",
    ]);
  });
});
