import { describe, expect, it } from "vitest";

import panelSource from "./AgentVirtualHumanPluginPanel.tsx?raw";
import detailSource from "../AgentSelectedDetailContentPanel.tsx?raw";

describe("Agent virtual-human plugin settings", () => {
  it("keeps the binding Agent-scoped and revision-bound", () => {
    expect(panelSource).toContain("listAgentPlugins(agentId)");
    expect(panelSource).toContain("expectedVersion: binding?.configVersion ?? 0");
    expect(panelSource).toContain("updateAgentPluginBinding(agentId, PLUGIN_ID");
    expect(panelSource).toContain("proactiveMessagesEnabled");
    expect(panelSource).toContain("autonomyLevel");
    expect(panelSource).toContain("DEFAULT_VIRTUAL_HUMAN_PROACTIVE_DAILY_LIMIT");
    expect(panelSource).toContain("DEFAULT_VIRTUAL_HUMAN_PROACTIVE_MINIMUM_INTERVAL_MINUTES");
    expect(panelSource).toContain("mergeVirtualHumanBindingConfig(binding");
  });

  it("places the plugin under Agent capability binding without replacing tool policy", () => {
    expect(detailSource).toContain("AgentVirtualHumanPluginPanel");
    expect(detailSource).toContain("<AgentConfigPolicyPanePanel");
    expect(detailSource).toContain("<AgentConfigReferencesPanePanel");
  });

  it("shows bounded runtime health without exposing full prompts or traces", () => {
    expect(panelSource).toContain("fetchVirtualHumanSnapshot(agentId");
    expect(panelSource).toContain("VirtualHumanHealthSection");
    expect(panelSource).toContain("personaInitialized");
    expect(panelSource).toContain("promptPackReady");
    expect(panelSource).toContain("memoryPromotionCount");
    expect(panelSource).toContain("lastProactiveError");
    expect(panelSource).toContain("个注入段");
    expect(panelSource).toContain("healthHasIssue");
    expect(panelSource).toContain("需要关注");
    expect(panelSource).toContain("full prompts and tool traces stay hidden");
    expect(panelSource).not.toContain("promptTemplate");
    expect(panelSource).not.toContain("lastPromptAssembly");
  });

  it("keeps health and settings usable when the additive runtime snapshot is unavailable", () => {
    expect(panelSource).toContain("retry: false");
    expect(panelSource).toContain("failed={snapshotQuery.isError}");
    expect(panelSource).toContain("!enabled");
    expect(panelSource).toContain("配置仍可保存");
    expect(panelSource).toContain("由 Agent 档案维护");
  });

  it("keeps the health grid compact for desktop configuration panes", () => {
    expect(panelSource).toContain("styles.healthGrid");
    expect(panelSource).toContain("styles.healthMeta");
    expect(panelSource).toContain("aria-label={lang === \"zh\" ? \"虚拟人运行健康\"");
  });
});
