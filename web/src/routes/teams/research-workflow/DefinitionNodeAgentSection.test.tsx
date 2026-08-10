import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { DefinitionNodeAgentSection } from "./DefinitionNodeAgentSection";

describe("DefinitionNodeAgentSection", () => {
  it("reuses the existing Agent card before a run exists", () => {
    const markup = renderToStaticMarkup(
      <MemoryRouter>
        <DefinitionNodeAgentSection
          binding={{
            nodeId: "source_extraction",
            roleKey: "source_extractor",
            agentId: "agent-extractor",
            displayName: "资料提炼 Agent",
            resolvedFrom: "workflow_default",
          }}
        />
      </MemoryRouter>,
    );

    expect(markup).toContain("Agent 配置");
    expect(markup).toContain("资料提炼 Agent");
    expect(markup).toContain("已绑定 · 团队/工作流默认");
    expect(markup).toContain("pane=config");
    expect(markup).toContain("agent=agent-extractor");
  });
});
