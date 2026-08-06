import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AgentToolSummaryPanel } from "./AgentToolSummaryPanel";

describe("AgentToolSummaryPanel", () => {
  it("keeps tool metrics in a compact inline summary", () => {
    const markup = renderToStaticMarkup(
      <AgentToolSummaryPanel
        copy={{
          allowedTools: "允许",
          blockedTools: "禁用",
          preferredTools: "优先",
          toolCategoryCount: "分类",
          toolPolicyTitle: "工具策略",
        }}
        lang="zh"
        policyId="tools-default"
        allowedCount={4}
        preferredCount={2}
        blockedCount={1}
        toolCategoryCount={3}
        onConfigure={() => undefined}
      />,
    );

    expect(markup).toContain("允许");
    expect(markup).toContain(">4<");
    expect(markup).toContain("配置工具能力");
    expect(markup).toContain('class="flex [flex-wrap:wrap]');
  });
});
