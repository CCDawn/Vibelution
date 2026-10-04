import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { AgentInstance } from "../api/types";
import { ToolsRouteAgentScopePanel } from "./ToolsRouteAgentScopePanel";
import toolsRouteSource from "./ToolsRoute.tsx?raw";

const previewAgent = {
  agentId: "agent-scope-preview",
  agentCode: "AG-UX",
  displayName: "Scope Preview Agent",
} as AgentInstance;

const copy = {
  blocked: "当前范围受阻",
  callable: "所选范围可调用",
  configure: "配置",
  configureAgent: "配置 Agent",
  loading: "加载中",
  scope: "Agent 范围",
  synced: "已同步",
  unsaved: "未保存",
  visible: "当前范围可见",
};

describe("ToolsRouteAgentScopePanel copy", () => {
  it("keeps the Agent identity and selected-scope counts together", () => {
    const html = renderToStaticMarkup(
      <ToolsRouteAgentScopePanel
        copy={copy}
        activeAgents={[previewAgent]}
        activeAgent={previewAgent}
        agentsLoading={false}
        activeAgentScopeId="main_agent"
        scopeOptions={[{ id: "main_agent", label: "主 Agent" }]}
        scopeCounts={{ visible: 128, callable: 125, blocked: 3 }}
        dirty={false}
        deepLinkNotice=""
        onAgentChange={() => undefined}
        onScopeChange={() => undefined}
      />,
    );

    expect(html).toContain("AG-UX Scope Preview Agent");
    expect(html).toContain("所选范围可调用");
    expect(html).toContain("125");
  });

  it("distinguishes scope counts from this Agent's allow-list and test approval in zh/en copy", () => {
    expect(toolsRouteSource).toContain('callable: lang === "zh" ? "所选范围可调用" : "Callable in selected scope"');
    expect(toolsRouteSource).toContain("Agent tool permissions · ${activePolicyAgentLabel}");
    expect(toolsRouteSource).toContain('lang === "zh" ? "明确允许" : "Explicitly allowed"');
    expect(toolsRouteSource).toContain("顶部统计所选 Agent 范围内的可调用工具（不是全局注册总数）；当前 Agent 的明确允许项与工具测试批准分别判断。");
    expect(toolsRouteSource).toContain("The counts above describe callable tools in the selected Agent scope, not the global registry. This Agent's explicit grants and tool-test approval are separate checks.");
    expect(toolsRouteSource).not.toContain('"实际允许"');
  });
});
