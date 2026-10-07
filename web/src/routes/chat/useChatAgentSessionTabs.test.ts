import { describe, expect, it, beforeEach } from "vitest";

import type { SessionSummary } from "../../api/types";
import { markSessionDeleteTombstone, resetSessionDeleteTombstonesForTests } from "../sessionDeleteTombstone";
import { buildAgentSessionTabs } from "./chatSessionSurfaceModel";
import { mergeAgentSessionTabSources } from "./useChatAgentSessionTabs";

function session(id: string, title: string, agentId = "agent-a"): SessionSummary {
  return {
    id, title, agentId, status: "ready", taskSummary: "", currentPhase: "ready",
    lastActive: "2026-10-07T00:00:00.000Z", updatedAt: "2026-10-07T00:00:00.000Z",
  };
}

describe("mergeAgentSessionTabSources", () => {
  beforeEach(() => {
    resetSessionDeleteTombstonesForTests();
  });

  it("keeps a recovered temp shell after the server list and the active-route fallback omit it", () => {
    const merged = buildAgentSessionTabs({
      sessions: mergeAgentSessionTabSources(
        [session("session-old", "问候")],
        [session("session-old", "问候")],
        [session("temp-session-a", "探测乙a8eef9")],
      ),
      selectedChatAgentDirectSessionId: undefined,
    });
    expect(merged.map((item) => item.id).sort()).toEqual(["session-old", "temp-session-a"]);
  });

  it("does not put back a temp shell the user already closed", () => {
    markSessionDeleteTombstone("temp-session-a", { confirmed: true });
    const merged = mergeAgentSessionTabSources(
      [session("session-old", "问候")],
      [],
      [session("temp-session-a", "探测乙a8eef9")],
    );
    expect(merged.map((item) => item.id)).toEqual(["session-old"]);
  });
});
