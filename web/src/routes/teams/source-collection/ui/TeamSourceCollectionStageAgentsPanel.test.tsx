import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { TeamSourceCollectionStageAgentsPanel } from "./TeamSourceCollectionStageAgentsPanel";

describe("TeamSourceCollectionStageAgentsPanel", () => {
  it("shows only the compact role, model and status summary", () => {
    const agent = {
      id: "source-finder",
      tone: "ready" as const,
      roleLabel: "资料寻找",
      agentName: "资料检索 Agent",
      modelLabel: "qwen-plus",
      statusLabel: "可运行",
      memoryRoute: "/memory/agent/source-finder",
      configRoute: "/agents?pane=config&agent=source-finder",
      configLabel: "打开设置",
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
    expect(inline).toContain('data-vui="dense-table"');
    expect(inline).toContain("职责");
    expect(inline).toContain("模型");
    expect(inline).toContain("状态");
    expect(inline).toContain("资料寻找");
    expect(inline).toContain("qwen-plus");
    expect(inline).toContain("可运行");
    expect(inline).toContain("打开设置");
    expect(inline).toContain("pane=config");
    expect(inline).toContain("agent=source-finder");
    expect(inline).toContain('data-tone="neutral"');
    expect(inline).not.toContain("资料检索 Agent");
    expect(inline).not.toContain("Agent 记忆");
    expect(stacked).toContain('data-vui="dense-table"');
  });

  it("renders an actionable empty state instead of a blank surface", () => {
    const empty = renderToStaticMarkup(
      <MemoryRouter>
        <TeamSourceCollectionStageAgentsPanel lang="zh" agents={[]} />
      </MemoryRouter>,
    );
    expect(empty).toContain('data-vui="empty-state"');
    expect(empty).toContain("尚未绑定 Agent");
    expect(empty).toContain("前往 Agent 中心绑定");
    expect(empty).toContain('href="/agents"');
    expect(empty).not.toContain('data-vui="dense-table"');

    const emptyEn = renderToStaticMarkup(
      <MemoryRouter>
        <TeamSourceCollectionStageAgentsPanel lang="en" agents={[]} />
      </MemoryRouter>,
    );
    expect(emptyEn).toContain("No agents bound");
    expect(emptyEn).toContain("Bind an Agent in Agent Center");
  });
});
