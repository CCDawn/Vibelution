import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import type { ResearchStageAgentBinding } from "../../TeamResearchStageAgentPanel";
import { ChallengeCupStageAgentConfigurationPanel } from "./ChallengeCupStageAgentConfigurationPanel";
import panelSource from "./ChallengeCupStageAgentConfigurationPanel.tsx?raw";

const bindings: ResearchStageAgentBinding[] = [
  {
    key: "experiment_planner",
    roleKeys: ["experiment_planner"],
    zh: "实验规划",
    en: "Experiment planner",
    zhFocus: "计划、baseline 与 smoke gate",
    enFocus: "Plan, baseline, smoke gate",
    agentId: "agent-experiment-planner",
    agent: {
      agentId: "agent-experiment-planner",
      displayName: "实验规划 Agent",
      health: [],
      dialogueModel: { label: "qwen-plus" },
    } as ResearchStageAgentBinding["agent"],
    bindingLabel: "实验规划 Agent",
    bindingSource: "canvas",
  },
];

describe("ChallengeCupStageAgentConfigurationPanel", () => {
  it("reuses the session task-card geometry and links each bound Agent to configuration", () => {
    const markup = renderToStaticMarkup(
      <MemoryRouter>
        <ChallengeCupStageAgentConfigurationPanel
          bindings={bindings}
          lang="zh"
          stageType="experiment"
        />
      </MemoryRouter>,
    );

    expect(markup).toContain('data-testid="challenge-cup-stage-agent-configuration"');
    expect(markup).toContain("实验规划 Agent");
    expect(markup).toContain("可用");
    expect(markup).toContain("配置");
    expect(markup).toContain("agent-experiment-planner");
    expect(panelSource).toContain("ResearchProjectAgentTaskPanel.styles");
    expect(panelSource).toContain("VRouteLinkButton");
    expect(panelSource).not.toContain('tone="success"');
  });
});
