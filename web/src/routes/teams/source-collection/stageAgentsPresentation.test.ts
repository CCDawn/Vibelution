import { describe, expect, it } from "vitest";

import { buildSourceCollectionStageAgentCards } from "./stageAgentsPresentation";

describe("buildSourceCollectionStageAgentCards", () => {
  it("maps bound and missing agents into controls rail cards", () => {
    const cards = buildSourceCollectionStageAgentCards({
      stageId: "finding",
      lang: "zh",
      agentSummaryPending: false,
      agentSummaryFetching: false,
      agentSummaryError: false,
      teamId: "research-team",
      returnTo: "/teams?team=research-team",
      bindings: [
        {
          key: "source_finder",
          agentId: "agent-1",
          agent: {
            agentId: "agent-1",
            displayName: "资料寻找",
          } as never,
          zh: "资料寻找",
          en: "Source finder",
        },
        {
          key: "source_extractor",
          zh: "资料提炼",
          en: "Source extractor",
        },
      ],
    });
    expect(cards).toHaveLength(2);
    expect(cards[0]?.id).toContain("finding");
    expect(cards[0]?.agentName).toBeTruthy();
    expect(cards[0]?.configLabel).toBe("配置");
    expect(cards[1]?.tone).toBe("missing");
    expect(cards[1]?.statusLabel).toBe("待绑定");
  });
});
