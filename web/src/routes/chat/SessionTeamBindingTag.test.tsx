import { describe, expect, it } from "vitest";

import type { SessionSummary } from "../../api/types";
import { resolveSessionTeamBinding } from "./SessionTeamBindingTag";
import { teamWorkspaceRoute } from "../teams/researchWorkspaceModel";

function session(overrides: Partial<SessionSummary> = {}): SessionSummary {
  return {
    id: "session-1",
    title: "Alpha",
    status: "idle",
    taskSummary: "",
    lastActive: "",
    updatedAt: "",
    currentPhase: "idle",
    ...overrides,
  };
}

describe("resolveSessionTeamBinding", () => {
  it("uses session team fields", () => {
    const binding = resolveSessionTeamBinding(
      session({ teamId: "team-a", teamName: "Alpha Team", agentId: "agent-1" }),
    );
    expect(binding).toEqual({ teamId: "team-a", teamName: "Alpha Team" });
  });

  it("uses experiment binding when session has no team fields", () => {
    const binding = resolveSessionTeamBinding(
      session({
        agentId: "agent-1",
        experimentBinding: {
          teamId: "team-exp",
          researchProjectId: "proj",
          experimentName: "Exp",
          agentId: "agent-1",
          roleKey: "runner",
          roleLabel: "Runner",
          attempt: 1,
          retryOfSessionId: "",
          createdFromTaskId: "",
          createdAt: "",
        },
      }),
    );
    expect(binding?.teamId).toBe("team-exp");
  });

  it("resolves membership from team catalog", () => {
    const binding = resolveSessionTeamBinding(
      session({ agentId: "agent-1", conversationIndexKind: "personal_agent" }),
      [
        {
          teamId: "team-mem",
          name: "Member Team",
          purpose: "协作",
          members: [{ agentId: "agent-1", agentCode: "A001", role: "lead", purpose: "" }],
        } as never,
      ],
    );
    expect(binding).toEqual({ teamId: "team-mem", teamName: "Member Team", purpose: "协作" });
  });

  it("hides user chat without agent or team", () => {
    expect(resolveSessionTeamBinding(session({ conversationIndexKind: "user_chat" }))).toBeUndefined();
  });

  it("ignores archived team membership", () => {
    expect(
      resolveSessionTeamBinding(
        session({ agentId: "agent-1", conversationIndexKind: "personal_agent" }),
        [
          {
            teamId: "team-archived",
            name: "Old Team",
            status: "archived",
            members: [{ agentId: "agent-1", agentCode: "A001", role: "lead", purpose: "", agentStatus: "active" }],
          } as never,
        ],
      ),
    ).toBeUndefined();
  });

  it("team workspace route matches open-team destination", () => {
    expect(teamWorkspaceRoute("team-a")).toContain("teamId=team-a");
    expect(teamWorkspaceRoute("team-a")).toContain("/teams?");
  });
});
