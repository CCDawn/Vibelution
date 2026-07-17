import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { AgentOverviewResourcesPanel } from "./AgentOverviewResourcesPanel";

describe("AgentOverviewResourcesPanel", () => {
  it("keeps related configuration and references reachable from the overview aside", () => {
    const markup = renderToStaticMarkup(
      <AgentOverviewResourcesPanel
        title="关联资源"
        emptyLabel="暂未关联资源"
        openLabel="打开"
        resources={[
          { id: "prompt", label: "提示词", value: "prompt-chat-default", route: "/agents?pane=config" },
          { id: "tools", label: "工具", value: "research-toolkit", route: "/agents?pane=config" },
          { id: "room", label: "群聊", value: "科研讨论组", route: "/chat?room=research" },
        ]}
        onOpenRoute={vi.fn()}
      />,
    );

    expect(markup).toContain("关联资源");
    expect(markup).toContain("prompt-chat-default");
    expect(markup).toContain("research-toolkit");
    expect(markup).toContain("科研讨论组");
    expect(markup).toContain("打开");
    expect(markup).toContain('aria-label="提示词完整值"');
  });
});
