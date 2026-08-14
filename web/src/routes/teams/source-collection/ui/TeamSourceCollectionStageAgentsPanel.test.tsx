import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { TeamSourceCollectionStageAgentsPanel } from "./TeamSourceCollectionStageAgentsPanel";

describe("TeamSourceCollectionStageAgentsPanel", () => {
  it("keeps the existing inline layout by default and exposes a stacked inspector layout", () => {
    const agent = {
      id: "source-finder",
      tone: "ready" as const,
      roleLabel: "资料寻找",
      agentName: "资料检索 Agent",
      modelLabel: "",
      statusLabel: "已绑定",
      memoryRoute: "",
      configRoute: "/agents?pane=config&agent=source-finder",
      configLabel: "Agent 配置",
    };
    const inline = renderToStaticMarkup(
      <MemoryRouter>
        <TeamSourceCollectionStageAgentsPanel lang="zh" agents={[agent]} />
      </MemoryRouter>,
    );
    const stacked = renderToStaticMarkup(
      <MemoryRouter>
        <TeamSourceCollectionStageAgentsPanel lang="zh" agents={[agent]} layout="stacked" />
      </MemoryRouter>,
    );

    expect(inline).toContain('data-layout="inline"');
    expect(stacked).toContain('data-layout="stacked"');
    expect(stacked).toContain("!grid-cols-[minmax(0,1fr)]");
    expect(stacked).toContain("[&amp;_strong]:whitespace-normal");
  });
});
