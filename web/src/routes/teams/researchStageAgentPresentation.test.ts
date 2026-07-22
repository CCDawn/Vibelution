import { describe, expect, it } from "vitest";

import type { AgentConfigWorkspaceAgent, TeamOrganizationCanvas } from "../../api/types";

import {
  researchStageAgentConfigStatusLabel,
  researchStageAgentConfigTone,
  researchStageAgentDirectChatRoute,
  researchStageAgentManagementRoute,
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
});
