import { describe, expect, it } from "vitest";

import type { AgentConfigWorkspaceAgent, Team, TeamOrganizationCanvas } from "../../api/types";

import {
  researchStageAgentConfigStatusLabel,
  researchStageAgentConfigTone,
  researchStageAgentDirectChatRoute,
  researchStageAgentManagementRoute,
  researchStageSessionChatRoute,
  sourceCollectionAgentIdsFromCanvas,
  sourceCollectionAgentIdsFromTeam,
  sourceCollectionOwnerAgentIdFromCanvas,
  sourceCollectionOwnerAgentIdFromTeam,
} from "./researchStageAgentPresentation";

describe("researchStageAgentPresentation", () => {
  it("maps canvas roles to source-collection agent ids", () => {
    const canvas = {
      nodes: [
        { id: "1", role: "Source_Finder", agentId: "a-finder", purpose: "", label: "", x: 0, y: 0, status: "ready" },
        { id: "2", role: "source_ingestor", agentId: "a-ingest", purpose: "", label: "", x: 0, y: 0, status: "ready" },
      ],
    } as TeamOrganizationCanvas;
    expect(sourceCollectionAgentIdsFromCanvas(canvas)).toEqual({
      source_finder: "a-finder",
      source_ingestor: "a-ingest",
    });
    expect(sourceCollectionOwnerAgentIdFromCanvas(canvas)).toBe("a-finder");
  });

  it("uses Team.members instead of Canvas for source-collection ids and owner", () => {
    const canvas = {
      nodes: [
        { id: "1", role: "source_finder", agentId: "stale-canvas-finder", label: "Stale" },
        { id: "2", role: "source_ingestor", agentId: "stale-canvas-ingestor", label: "Stale" },
      ],
    } as TeamOrganizationCanvas;
    const team = {
      members: [
        { agentId: "ssot-finder", role: "source_finder", agentName: "SSOT Finder" },
        { agentId: "ssot-ingestor", role: "source_ingestor", agentName: "SSOT Ingestor" },
      ],
    } as Team;

    expect(sourceCollectionAgentIdsFromTeam(team, canvas)).toEqual({
      source_finder: "ssot-finder",
      source_ingestor: "ssot-ingestor",
    });
    expect(sourceCollectionOwnerAgentIdFromTeam(team, canvas)).toBe("ssot-finder");
  });

  it("labels agent config readiness from health", () => {
    const blocked = {
      health: [{ severity: "blocking", code: "x", title: "t", message: "m" }],
    } as AgentConfigWorkspaceAgent;
    expect(researchStageAgentConfigTone(blocked)).toBe("blocked");
    expect(researchStageAgentConfigStatusLabel(blocked, "zh")).toBe("需修复");
    expect(researchStageAgentConfigStatusLabel(null, "en")).toBe("missing");
  });

  it("builds management and direct-chat routes", () => {
    expect(researchStageAgentManagementRoute("agent-1")).toContain("agent=agent-1");
    expect(researchStageAgentManagementRoute("")).toBe("/agents?pane=config");
    expect(
      researchStageAgentDirectChatRoute(
        { directSessionId: "sess-1" } as AgentConfigWorkspaceAgent,
        "/teams",
        "Teams",
      ),
    ).toContain("session=sess-1");
  });

  it("builds a chat route from the current stage task session", () => {
    expect(
      researchStageSessionChatRoute(
        "session-current-task",
        "/teams?team=research-team",
        "返回知识搜集",
      ),
    ).toBe(
      "/chat?session=session-current-task&returnTo=%2Fteams%3Fteam%3Dresearch-team&returnLabel=%E8%BF%94%E5%9B%9E%E7%9F%A5%E8%AF%86%E6%90%9C%E9%9B%86",
    );
    expect(researchStageSessionChatRoute("")).toBe("");
  });
});
