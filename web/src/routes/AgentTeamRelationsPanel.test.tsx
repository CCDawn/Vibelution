import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AgentTeamRelationsPanel } from "./AgentTeamRelationsPanel";

describe("AgentTeamRelationsPanel", () => {
  it("renders confirmed team membership without inferring delegation or approval edges", () => {
    const markup = renderToStaticMarkup(
      <AgentTeamRelationsPanel
        relations={[
          {
            teamId: "research-team",
            name: "科研团队",
            purpose: "问题拆解与研究验证",
            members: [
              { agentId: "A001", label: "科研规划师", functionLabel: "当前 Agent · 科研规划", current: true },
              { agentId: "A002", label: "资料寻找", functionLabel: "资料寻访", current: false },
            ],
          },
        ]}
        onOpenTeam={() => undefined}
      />,
    );

    expect(markup).toContain("团队关系");
    expect(markup).toContain("科研团队");
    expect(markup).toContain("科研规划师");
    expect(markup).toContain("资料寻找");
    expect(markup).toContain("成员关系来自团队画布");
    expect(markup).not.toContain("可委派");
    expect(markup).not.toContain("人工门禁");
  });
});
