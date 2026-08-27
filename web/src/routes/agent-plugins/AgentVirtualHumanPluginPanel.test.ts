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
  });

  it("places the plugin under Agent capability binding without replacing tool policy", () => {
    expect(detailSource).toContain("AgentVirtualHumanPluginPanel");
    expect(detailSource).toContain("<AgentConfigPolicyPanePanel");
    expect(detailSource).toContain("<AgentConfigReferencesPanePanel");
  });
});
