import { describe, expect, it } from "vitest";

import {
  agentCenterConfigRoute,
  agentCenterMemoryRoute,
  agentCenterModelsRoute,
  agentCenterPromptsRoute,
  agentCenterToolsRoute,
  safeAgentCenterReturnToPath,
  teamMemoryRoute,
} from "./agentCenterRoutes";

describe("agentCenterRoutes", () => {
  it("keeps Agent Center deep links aligned with each target route", () => {
    const returnTo = "/agents?agent=agent-1&pane=config";

    expect(agentCenterConfigRoute({ agentId: "agent-1", returnLabel: "chat", returnTo })).toBe(
      "/agents?pane=config&agent=agent-1&returnTo=%2Fagents%3Fagent%3Dagent-1%26pane%3Dconfig&returnLabel=chat",
    );
    expect(agentCenterToolsRoute({ agentId: "agent-1", returnLabel: "agents", returnTo })).toBe(
      "/agents/tools?agent=agent-1&returnTo=%2Fagents%3Fagent%3Dagent-1%26pane%3Dconfig&returnLabel=agents",
    );
    expect(agentCenterPromptsRoute({ agentId: "agent-1", templateId: "prompt-main", focus: "editor", returnLabel: "agents", returnTo })).toBe(
      "/agents/prompts?agent=agent-1&template=prompt-main&focus=editor&returnTo=%2Fagents%3Fagent%3Dagent-1%26pane%3Dconfig&returnLabel=agents",
    );
    expect(agentCenterModelsRoute({ agentId: "agent-1", section: "runtime-context", returnLabel: "agents", returnTo })).toBe(
      "/config?agent=agent-1&section=runtime-context&returnTo=%2Fagents%3Fagent%3Dagent-1%26pane%3Dconfig&returnLabel=agents",
    );
    expect(agentCenterMemoryRoute({ agentId: "agent-1", view: "agents", returnLabel: "agents", returnTo })).toBe(
      "/memory/agents?agentId=agent-1&view=agents&returnTo=%2Fagents%3Fagent%3Dagent-1%26pane%3Dconfig&returnLabel=agents",
    );
    expect(agentCenterMemoryRoute({ agentId: "agent-1", teamId: "team-a", view: "agents", returnLabel: "teams", returnTo: "/teams?team=team-a" })).toBe(
      "/memory/agents?agentId=agent-1&teamId=team-a&view=agents&returnTo=%2Fteams%3Fteam%3Dteam-a&returnLabel=teams",
    );
    expect(agentCenterMemoryRoute({
      agentId: "agent-1",
      knowledgeBaseId: "agent:agent-1:reports",
      view: "knowledge",
      returnLabel: "炒股智能体",
      returnTo: "/finance?session=native-session",
    })).toBe(
      "/memory/knowledge?agentId=agent-1&knowledgeBaseId=agent%3Aagent-1%3Areports&view=knowledge&returnTo=%2Ffinance%3Fsession%3Dnative-session&returnLabel=%E7%82%92%E8%82%A1%E6%99%BA%E8%83%BD%E4%BD%93",
    );
    expect(teamMemoryRoute({ teamId: "team-a", view: "knowledge", returnLabel: "teams", returnTo: "/teams?team=team-a" })).toBe(
      "/memory/knowledge?teamId=team-a&view=knowledge&returnTo=%2Fteams%3Fteam%3Dteam-a&returnLabel=teams",
    );
    expect(teamMemoryRoute({ teamId: "team-a", view: "graph", agentId: "agent-1", nodeId: "team:team-a" })).toBe(
      "/memory/graph?teamId=team-a&agentId=agent-1&nodeId=team%3Ateam-a&view=graph",
    );
  });

  it("drops unsafe return targets", () => {
    expect(safeAgentCenterReturnToPath("//example.com")).toBe("");
    expect(safeAgentCenterReturnToPath("/\\example.com")).toBe("");
    expect(agentCenterToolsRoute({ agentId: "agent-1", returnTo: "https://example.com" })).toBe("/agents/tools?agent=agent-1");
  });
});
