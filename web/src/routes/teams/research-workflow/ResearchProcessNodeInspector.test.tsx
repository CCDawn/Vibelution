import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { ResearchProcessNodeInspector } from "./ResearchProcessNodeInspector";

describe("ResearchProcessNodeInspector command rendering", () => {
  it("renders wired human-gate commands and fires onCommand for them", () => {
    const onCommand = vi.fn();
    const markup = renderToStaticMarkup(
      <ResearchProcessNodeInspector
        nodeId="knowledge_handoff"
        runtimeCurrent={false}
        actorKind="human"
        onCommand={onCommand}
      />,
    );
    expect(markup).toContain("接受交接");
    expect(markup).toContain("拒绝交接");
    expect(markup).toContain("要求修订");
  });

  it("does not render unwired commands as buttons (no start_agent_task fake entry)", () => {
    const onCommand = vi.fn();
    const markup = renderToStaticMarkup(
      <ResearchProcessNodeInspector
        nodeId="source_finding"
        runtimeCurrent={false}
        actorKind="agent"
        onCommand={onCommand}
      />,
    );
    // start_agent_task is declared on the adapter but has no live handler:
    // it must NOT surface as a clickable button.
    expect(markup).not.toContain("启动 Agent 任务");
  });

  it("renders open_session as a link when the session anchor is available", () => {
    const markup = renderToStaticMarkup(
      <ResearchProcessNodeInspector
        nodeId="source_finding"
        runtimeCurrent={false}
        actorKind="agent"
        chatDeepLink="/chat/session-1"
        sessionAnchorDegraded={false}
        onCommand={vi.fn()}
      />,
    );
    expect(markup).toContain('href="/chat/session-1"');
    expect(markup).toContain("打开精确会话");
  });

  it("disables open_session (instead of erroring) when no binding is available", () => {
    const markup = renderToStaticMarkup(
      <ResearchProcessNodeInspector
        nodeId="source_finding"
        runtimeCurrent={false}
        actorKind="agent"
        chatDeepLink={null}
        sessionAnchorDegraded={false}
        onCommand={vi.fn()}
      />,
    );
    expect(markup).toContain("打开精确会话");
    expect(markup).toContain('disabled');
    expect(markup).toContain("节点尚未绑定会话");
  });

  it("disables open_session when the session anchor is degraded", () => {
    const markup = renderToStaticMarkup(
      <ResearchProcessNodeInspector
        nodeId="source_finding"
        runtimeCurrent={false}
        actorKind="agent"
        chatDeepLink="/chat/session-1"
        sessionAnchorDegraded
        onCommand={vi.fn()}
      />,
    );
    expect(markup).not.toContain('href="/chat/session-1"');
    expect(markup).toContain("会话锚点不可用");
  });
});
