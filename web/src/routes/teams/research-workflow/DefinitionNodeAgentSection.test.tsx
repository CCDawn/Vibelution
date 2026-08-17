import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { DefinitionNodeAgentSection } from "./DefinitionNodeAgentSection";

function renderSection() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, enabled: false } },
  });
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <DefinitionNodeAgentSection
          teamId="research-team"
          nodeId="source_extraction"
          stageId="knowledge_collection"
          stageLabel="知识搜集"
          title="资料提炼"
          binding={{
            nodeId: "source_extraction",
            roleKey: "source_extractor",
            agentId: "agent-extractor",
            displayName: "资料提炼 Agent",
            resolvedFrom: "workflow_default",
          }}
          effectiveBindings={[]}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("DefinitionNodeAgentSection", () => {
  it("shows agent identity, model card and budget meters before a run exists", () => {
    const markup = renderSection();

    expect(markup).toContain("资料提炼 Agent");
    expect(markup).toContain("知识搜集");
    expect(markup).toContain("Tokens");
    expect(markup).toContain('data-testid="node-inspector-model-trigger"');
    expect(markup).toContain("pane=config");
    expect(markup).toContain("agent=agent-extractor");
    expect(markup).not.toContain("Agent 配置");
    expect(markup).not.toContain("source_extractor");
    expect(markup).not.toContain("已绑定 · 团队/工作流默认");
  });
});
