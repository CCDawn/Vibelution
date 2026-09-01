import { describe, expect, it } from "vitest";

import type { AgentInstance, SessionSummary } from "../../api/types";
import {
  companionAgentIdForDirectSession,
  sessionsForChatRoute,
} from "./companionChatRouteIsolation";

function agent(overrides: Partial<AgentInstance> = {}): AgentInstance {
  return {
    agentId: "agent-ordinary",
    displayName: "Ordinary",
    kind: "persistent",
    status: "active",
    directSessionId: "session-ordinary",
    metadata: {},
    ...overrides,
  } as AgentInstance;
}

function session(id: string, agentId: string): SessionSummary {
  return { id, agentId } as SessionSummary;
}

describe("companionChatRouteIsolation", () => {
  const companion = agent({
    agentId: "agent-companion",
    directSessionId: "session-companion",
    metadata: { virtualHumanCompanion: true },
  });
  const ordinary = agent();
  const sessions = [
    session("session-companion", "agent-companion"),
    session("session-ordinary", "agent-ordinary"),
  ];

  it("keeps Companion sessions out of bare and ordinary Chat selection", () => {
    expect(sessionsForChatRoute({
      sessions,
      agents: [companion, ordinary],
      companionRouteVerified: false,
    })?.map((item) => item.id)).toEqual(["session-ordinary"]);
  });

  it("waits for Agent identity instead of guessing from Session names", () => {
    expect(sessionsForChatRoute({
      sessions,
      agents: undefined,
      companionRouteVerified: false,
    })).toBeUndefined();
    expect(sessionsForChatRoute({
      sessions,
      agents: [agent({
        agentId: "agent-named-companion",
        directSessionId: "session-companion",
        displayName: "洛天依",
      })],
      companionRouteVerified: false,
    })?.map((item) => item.id)).toEqual(["session-companion", "session-ordinary"]);
  });

  it("preserves the native Session on an explicit Companion route", () => {
    expect(sessionsForChatRoute({
      sessions,
      agents: [companion, ordinary],
      companionRouteVerified: true,
    })?.map((item) => item.id)).toEqual(["session-companion", "session-ordinary"]);
  });

  it("upgrades only an exact marked Companion direct Session", () => {
    const companionActivity = [{
      agentId: companion.agentId,
      displayName: companion.displayName,
      directSessionId: companion.directSessionId,
      sessionActivity: undefined,
    }];
    expect(companionAgentIdForDirectSession(companionActivity, "session-companion"))
      .toBe("agent-companion");
    expect(companionAgentIdForDirectSession(companionActivity, "session-ordinary"))
      .toBe("");
  });
});
