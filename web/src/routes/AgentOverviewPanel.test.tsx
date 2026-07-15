import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AgentOverviewPanel } from "./AgentOverviewPanel";

describe("AgentOverviewPanel", () => {
  it("keeps technical identifiers available without crowding the primary overview", () => {
    const markup = renderToStaticMarkup(
      <AgentOverviewPanel
        facts={[
          { id: "model", icon: "model", title: "model details", label: "模型", value: "GPT-5.6" },
          { id: "system-ids", icon: "system", title: "agent-id", label: "系统编号", value: "A050" },
          { id: "tools", icon: "tools", title: "tool-policy", label: "工具能力", value: "tool-050" },
        ]}
        territory={{
          eyebrow: "工作空间",
          title: "private",
          privateLabel: "私人工作区",
          privateValue: "workspace/agents/a050",
          sharedLabel: "共享资料区",
          sharedValue: "workspace/shared",
          writeBoundaryLabel: "默认保存位置",
          writeBoundaryValue: "private",
        }}
        modeMembership={{ eyebrow: "使用位置", title: "会话", modes: [{ id: "chat", label: "会话" }] }}
        policies={[]}
      >
        <div>运营内容</div>
      </AgentOverviewPanel>,
    );

    expect(markup).toContain("GPT-5.6");
    expect(markup).toContain("技术信息");
    expect(markup).toContain("工作空间、策略与系统标识");
    expect(markup).toContain("<details");
    expect(markup).not.toContain("<details open");
    expect(markup).toContain("A050");
    expect(markup).toContain("workspace/agents/a050");
    expect(markup).toContain("运营内容");
    expect(markup.indexOf("运营内容")).toBeLessThan(markup.indexOf("技术信息"));
  });
});
