import { describe, expect, it, vi } from "vitest";

import type { AgentConfigWorkspaceAgent, Team } from "../../api/types";
import { createSourceCollectionStageAgentHelpers } from "./createSourceCollectionStageAgentHelpers";

function query<T>(data: T) {
  return {
    data,
    isPending: false,
    isFetching: false,
    isError: false,
  } as never;
}

function challengeTeam(): Team {
  return {
    teamId: "research-team",
    teamKind: "research",
    teamSource: "research_organization",
    members: [],
  } as Team;
}

function buildHelpers(agentId: string, runId = "run-1", agent: AgentConfigWorkspaceAgent | null = null, taskSessionId = "old-session") {
  const seed = vi.fn(async () => ({ chatRoute: "/chat?session=new" }));
  const navigate = vi.fn();
  const helpers = createSourceCollectionStageAgentHelpers({
    lang: "zh",
    selectedTeam: challengeTeam(),
    knowledgeExpansionWorkflowTeamSelected: false,
    researchStageAgentBindingsByStage: {
      knowledge_collection: [{
        key: "source_finder",
        roleKeys: ["source_finder"],
        zh: "资料寻找",
        en: "Source finder",
        zhFocus: "搜索",
        enFocus: "Search",
        agentId,
        agent,
        bindingLabel: "",
        bindingSource: "member",
      }],
    },
    selectedSourceCollectionRunEffectiveId: runId,
    sourceCollectionSummaryQuery: query({ latestTasks: { finding: { sessionId: taskSessionId } } }),
    agentSummaryQuery: query<AgentConfigWorkspaceAgent[]>(agent ? [agent] : []),
    seedSourceCollectionAgentSessionContextMutation: { mutateAsync: seed },
    repairKnowledgeExpansionTeamAgentsMutation: { isPending: false, mutate: vi.fn() },
    navigate: navigate as never,
  });
  return { helpers, seed, navigate };
}

describe("createSourceCollectionStageAgentHelpers", () => {
  it("routes a stale Challenge Cup Agent to its SSOT configuration without seeding", async () => {
    const { helpers, seed, navigate } = buildHelpers("stale-agent");

    await helpers.openSourceCollectionStageAgentChat("finding");

    expect(seed).not.toHaveBeenCalled();
    expect(navigate).toHaveBeenCalledWith("/agents?pane=config&agent=stale-agent");
  });

  it("routes an unbound Challenge Cup stage to the Agent configuration pane", async () => {
    const { helpers, seed, navigate } = buildHelpers("");

    await helpers.openSourceCollectionStageAgentChat("finding");

    expect(seed).not.toHaveBeenCalled();
    expect(navigate).toHaveBeenCalledWith("/agents?pane=config");
  });

  it.each(["stale-agent", ""])("keeps configuration navigation for Agent %s without a run", async (agentId) => {
    const { helpers, seed, navigate } = buildHelpers(agentId, "");

    expect(helpers.sourceCollectionStageAgentChatState("finding").status).toBe("blocked");
    await helpers.openSourceCollectionStageAgentChat("finding");

    expect(seed).not.toHaveBeenCalled();
    expect(navigate).toHaveBeenCalledExactlyOnceWith(agentId ? `/agents?pane=config&agent=${agentId}` : "/agents?pane=config");
  });

  it("seeds the ready project session and navigates to the returned route", async () => {
    const agent = { agentId: "source-agent" } as AgentConfigWorkspaceAgent;
    const { helpers, seed, navigate } = buildHelpers(agent.agentId, "run-1", agent);

    expect(helpers.sourceCollectionStageAgentChatState("finding").status).toBe("ready");
    await helpers.openSourceCollectionStageAgentChat("finding");

    expect(seed).toHaveBeenCalledExactlyOnceWith({
      teamId: "research-team", runId: "run-1", stageId: "finding", agentId: "source-agent", agentRole: "source_finder",
    });
    expect(navigate).toHaveBeenCalledExactlyOnceWith("/chat?session=new");
  });

  it("marks a normal Agent without run context as blocked without seeding", async () => {
    const agent = { agentId: "source-agent" } as AgentConfigWorkspaceAgent;
    const { helpers, seed, navigate } = buildHelpers(agent.agentId, "", agent, "");

    // No historic task route is available for the new run context.
    expect(helpers.sourceCollectionStageAgentChatState("finding").status).toBe("blocked");
    await helpers.openSourceCollectionStageAgentChat("finding");

    expect(seed).not.toHaveBeenCalled();
    expect(navigate).not.toHaveBeenCalled();
  });

  it("opens the known native task route when a run does not need seeding", async () => {
    const agent = { agentId: "source-agent" } as AgentConfigWorkspaceAgent;
    const { helpers, seed, navigate } = buildHelpers(agent.agentId, "", agent);
    const state = helpers.sourceCollectionStageAgentChatState("finding");

    expect(state.status).toBe("ready");
    expect(state.route).toContain("session=old-session");
    await helpers.openSourceCollectionStageAgentChat("finding");

    expect(seed).not.toHaveBeenCalled();
    expect(navigate).toHaveBeenCalledExactlyOnceWith(state.route);
  });
});
