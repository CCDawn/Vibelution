import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { ResearchWorkflowNodeDetail } from "../../../api/types/research-workflow/core";
import { NodeAgentSection } from "./NodeAgentSection";

function renderSection(detail: ResearchWorkflowNodeDetail) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, enabled: false } },
  });
  return renderToStaticMarkup(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <NodeAgentSection
          teamId="research-team"
          stageId="knowledge_collection"
          stageLabel="知识搜集"
          detail={detail}
          effectiveBindings={[]}
          budget={null}
          primaryOffer={null}
          busy={false}
          onOffer={vi.fn()}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("NodeAgentSection", () => {
  it("shows agent identity and exact session link without dumping role keys", () => {
    const detail = {
      nodeId: "source_finding",
      primaryRoleKey: "source_finder",
      agentId: "agent-finder",
      displayName: "资料检索 Agent",
      resolvedFrom: "node_override",
      sessionId: "session-1",
      taskId: "task-1",
      turnId: "turn-1",
      sessionAnchorDegraded: false,
      chatDeepLink: "/chat?session=session-1&focusTask=task-1&focusTurn=turn-1",
      label: "资料寻找",
      runtimeCurrent: false,
      status: "ready",
    } as ResearchWorkflowNodeDetail;

    const markup = renderSection(detail);

    expect(markup).toContain("资料检索 Agent");
    expect(markup).toContain("资料寻找");
    expect(markup).toContain("pane=config");
    expect(markup).toContain("agent=agent-finder");
    expect(markup).toContain('href="/chat?session=session-1');
    expect(markup).toContain("Tokens");
    expect(markup).not.toContain("source_finder");
    expect(markup).not.toContain("Agent 配置");
    expect(markup).not.toContain("会话已绑定");
  });
});
