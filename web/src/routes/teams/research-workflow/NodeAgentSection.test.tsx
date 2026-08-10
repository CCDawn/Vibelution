import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import type { ResearchWorkflowNodeDetail } from "../../../api/types/researchWorkflow";
import { NodeAgentSection } from "./NodeAgentSection";

describe("NodeAgentSection", () => {
  it("reuses the workflow Agent card with exact config and session state", () => {
    const detail = {
      nodeId: "source_finding",
      primaryRoleKey: "source_finder",
      bindingSnapshot: {
        agentId: "agent-finder",
        displayName: "资料检索 Agent",
        resolvedFrom: "node_override",
      },
      sessionBinding: {
        sessionId: "session-1",
        status: "bound",
      },
    } as unknown as ResearchWorkflowNodeDetail;

    const markup = renderToStaticMarkup(
      <MemoryRouter>
        <NodeAgentSection detail={detail} />
      </MemoryRouter>,
    );

    expect(markup).toContain("Agent 配置");
    expect(markup).toContain("资料寻找");
    expect(markup).toContain("资料检索 Agent");
    expect(markup).toContain("会话已绑定");
    expect(markup).toContain("pane=config");
    expect(markup).toContain("agent=agent-finder");
    expect(markup).not.toContain("source_finder");
  });
});
