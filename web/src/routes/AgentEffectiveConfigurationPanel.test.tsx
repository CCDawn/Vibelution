import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  AgentEffectiveConfigurationInspectorPanel,
  AgentEffectiveConfigurationPanel,
} from "./AgentEffectiveConfigurationPanel";

const fields = [
  {
    key: "dialogueModel",
    label: "对话模型",
    effectiveValue: "gpt-5.6-terra",
    source: { kind: "agent", id: "A001", label: "Agent 模型绑定" },
    inheritanceChain: [
      { kind: "global", id: "global", label: "全局默认", value: "qwen", active: false },
      { kind: "agent", id: "A001", label: "Agent 模型绑定", value: "gpt-5.6-terra", active: true },
    ],
    status: "ready",
  },
  {
    key: "delegation",
    label: "委派策略",
    effectiveValue: { allowSubagents: true, maxConcurrent: 3, maxDepth: 2 },
    source: { kind: "system", id: "default", label: "系统默认委派策略" },
    inheritanceChain: [
      { kind: "system", id: "default", label: "系统默认委派策略", value: "default", active: true },
    ],
    status: "warning",
  },
] as const;

describe("AgentEffectiveConfigurationPanel", () => {
  it("shows effective values and source labels without exposing raw JSON", () => {
    const markup = renderToStaticMarkup(
      <AgentEffectiveConfigurationPanel
        fields={[...fields]}
        selectedFieldKey="dialogueModel"
        onSelectField={() => undefined}
        onOpenConfig={() => undefined}
      />,
    );

    expect(markup).toContain("当前有效配置");
    expect(markup).toContain("gpt-5.6-terra");
    expect(markup).toContain("Agent 模型绑定");
    expect(markup).toContain("可委派 · 并发 3 · 深度 2");
    expect(markup).not.toContain('"maxConcurrent"');
  });

  it("keeps the full inheritance chain in the inspector for the selected field", () => {
    const markup = renderToStaticMarkup(
      <AgentEffectiveConfigurationInspectorPanel
        field={fields[0]}
        onOpenConfig={() => undefined}
      />,
    );

    expect(markup).toContain("配置来源");
    expect(markup).toContain("全局默认");
    expect(markup).toContain("Agent 模型绑定");
    expect(markup).toContain("当前生效");
  });
});
