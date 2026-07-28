import { describe, expect, it } from "vitest";

import type { AgentConfigWorkspaceAgent, TeamOrganizationCanvas } from "../../api/types";

import {
  researchStageAgentConfigStatusLabel,
  researchStageAgentConfigTone,
  researchStageAgentDirectChatRoute,
  researchStageAgentManagementRoute,
  researchStageSessionChatRoute,
  sourceCollectionAgentIdsFromCanvas,
  sourceCollectionOwnerAgentIdFromCanvas,
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
