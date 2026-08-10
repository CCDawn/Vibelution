import { describe, expect, it } from "vitest";

import { buildResearchAgentCard } from "./researchAgentCardModel";

describe("research Agent card presentation", () => {
  it("does not present an internal role key as a model name", () => {
    const card = buildResearchAgentCard({
      nodeId: "source_finding",
      roleKey: "source_finder",
      roleLabel: "资料寻找",
      agentId: "agent-1",
      agentName: "资料检索 Agent",
      resolvedFrom: "workflow_default",
      sessionBound: false,
    });

    expect(card.roleLabel).toBe("资料寻找");
    expect(card.modelLabel).toBe("");
    expect(card.statusLabel).toBe("已绑定 · 团队/工作流默认");
  });

  it("uses a user-facing fallback instead of leaking an unknown role key", () => {
    const card = buildResearchAgentCard({
      nodeId: "future_node",
      roleKey: "future_internal_role",
      agentId: "",
      resolvedFrom: "unbound",
      sessionBound: false,
    });

    expect(card.roleLabel).toBe("科研执行");
    expect(card.roleLabel).not.toContain("future_internal_role");
  });
});
