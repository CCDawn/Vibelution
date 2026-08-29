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

function buildHelpers(agentId: string) {
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
        agent: null,
        bindingLabel: "",
        bindingSource: "member",
      }],
    },
    selectedSourceCollectionRunEffectiveId: "run-1",
    sourceCollectionSummaryQuery: query({ latestTasks: { finding: { sessionId: "old-session" } } }),
    agentSummaryQuery: query<AgentConfigWorkspaceAgent[]>([]),
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
});
