import { describe, expect, it } from "vitest";

import { buildResearchStageAgentBindingsByStage } from "./researchStageAgentBindings";
import type { AgentConfigWorkspaceAgent, Team, TeamOrganizationCanvas } from "../../api/types";

function agent(id: string, name = id): AgentConfigWorkspaceAgent {
  return { agentId: id, displayName: name, status: "ready" } as AgentConfigWorkspaceAgent;
}

describe("buildResearchStageAgentBindingsByStage", () => {
  it("prefers canvas role bindings over members and fallbacks", () => {
    const canvas = {
      nodes: [
        { agentId: "finder-canvas", role: "source_finder", label: "Canvas Finder" },
      ],
    } as TeamOrganizationCanvas;
    const selectedTeam = {
      members: [
        { agentId: "finder-member", role: "source_finder", agentName: "Member Finder" },
      ],
    } as Team;
    const activeAgentsById = new Map([
      ["finder-canvas", agent("finder-canvas", "Canvas Finder")],
      ["finder-member", agent("finder-member", "Member Finder")],
    ]);

    const bindings = buildResearchStageAgentBindingsByStage({
      canvas,
      selectedTeam,
      activeAgentsById,
      knowledgeExpansionWorkflowTeamSelected: false,
    });
    const finder = bindings.knowledge_collection.find((item) => item.key === "source_finder");
    expect(finder?.agentId).toBe("finder-canvas");
    expect(finder?.bindingSource).toBe("canvas");
    expect(finder?.bindingLabel).toBe("Canvas Finder");
  });

  it("falls back to member role when canvas is unbound", () => {
    const selectedTeam = {
      members: [
        { agentId: "extractor-1", role: "source_extractor", agentName: "Extractor" },
      ],
    } as Team;
    const activeAgentsById = new Map([["extractor-1", agent("extractor-1", "Extractor")]]);
    const bindings = buildResearchStageAgentBindingsByStage({
      canvas: null,
      selectedTeam,
      activeAgentsById,
      knowledgeExpansionWorkflowTeamSelected: false,
    });
    const extractor = bindings.knowledge_collection.find((item) => item.key === "source_extractor");
    expect(extractor?.agentId).toBe("extractor-1");
    expect(extractor?.bindingSource).toBe("member");
  });
});
