import { describe, expect, it } from "vitest";

import routeSource from "./ToolsRoute.tsx?raw";
import routerSource from "../app/router.tsx?raw";

describe("ToolsRoute layout contract", () => {
  it("lives inside Agent management navigation", () => {
    expect(routerSource).toContain('path: "agents/tools"');
    expect(routerSource).toContain("<ToolsRoute />");
    expect(routerSource).not.toContain('path: "tools"');
    expect(routerSource).not.toContain('to="/agents/tools" replace');
    expect(routeSource).toContain('<AgentManagementNav active="tools" />');
    expect(routeSource.indexOf('<AgentManagementNav active="tools" />')).toBeGreaterThan(routeSource.indexOf("</header>"));
    expect(routeSource.indexOf('<AgentManagementNav active="tools" />')).toBeLessThan(routeSource.indexOf("styles.summaryGrid"));
  });

  it("keeps manual generated-tool creation out of the page", () => {
    expect(routeSource).not.toContain('fetchJson<ToolRegistryItem>("/api/tools/generated"');
    expect(routeSource).not.toContain("toolsAddGenerated");
    expect(routeSource).not.toContain("createMutation");
  });

  it("surfaces tool readiness before raw schema details", () => {
    const readinessIndex = routeSource.indexOf("styles.readinessPanel");
    const schemaIndex = routeSource.indexOf("styles.schemaDisclosure");

    expect(readinessIndex).toBeGreaterThan(0);
    expect(schemaIndex).toBeGreaterThan(readinessIndex);
    expect(routeSource).toContain("toolReadinessCards(activeTool, activeScopeState");
    expect(routeSource).toContain("readinessTone");
  });

  it("summarizes filter counts and test outcomes as scan-friendly cards", () => {
    expect(routeSource).toContain("toolFilterCounts");
    expect(routeSource).toContain("filterCounts");
    expect(routeSource).toContain("styles.resultSummaryGrid");
    expect(routeSource).toContain("testResultSummaryCards(testResult, t)");
    expect(routeSource).toContain("styles.resultCard");
  });

  it("supports agent-scoped tool lists and test requests", () => {
    expect(routeSource).toContain("activeAgentScopeId");
    expect(routeSource).toContain("toolsQuery.data?.agentScopes");
    expect(routeSource).toContain("styles.agentScopeBar");
    expect(routeSource).toContain("scopeStateForTool(tool, activeAgentScopeId)");
    expect(routeSource).toContain("JSON.stringify({ args: {}, agentScope: payload.agentScopeId, agentId: payload.agentId })");
    expect(routeSource).toContain("agentId: activePolicyAgent.agentId");
  });

  it("exposes Agent ToolPolicy controls from the tool bench", () => {
    expect(routeSource).toContain("fetchJson<AgentInstance[]>(\"/api/agents\")");
    expect(routeSource).toContain("toolPolicyMutation");
    expect(routeSource).toContain("setPolicyDraft((current) => nextToolPolicy(current ?? activePolicy, activeTool.name, mode))");
    expect(routeSource).toContain("styles.agentPolicyPanel");
    expect(routeSource).toContain("styles.policyStatePill");
    expect(routeSource).toContain("styles.policyModeButtonActive");
  });

  it("supports Agent-scoped bulk ToolPolicy draft assignment", () => {
    expect(routeSource).toContain("policyDraft");
    expect(routeSource).toContain("permissionTools");
    expect(routeSource).toContain("styles.agentBulkPolicyPanel");
    expect(routeSource).toContain("setSelectedToolsPolicyMode(\"allowed\")");
    expect(routeSource).toContain("setSelectedToolsPolicyMode(\"blocked\")");
    expect(routeSource).toContain("setSelectedToolsPolicyMode(\"inherited\")");
    expect(routeSource).toContain("applyPolicyDraft");
    expect(routeSource).toContain("body: JSON.stringify({ toolPolicy: payload.policy })");
  });

  it("lets the image2 tool choose a configured model without exposing provider secrets", () => {
    expect(routeSource).toContain("IMAGE2_TOOL_NAME = \"image2_generate_tool\"");
    expect(routeSource).toContain("fetchJson<ToolImage2ModelConfig>(\"/api/tools/image2/models\")");
    expect(routeSource).toContain("fetchJson<ToolImage2ModelConfig>(\"/api/tools/image2/default-model\"");
    expect(routeSource).toContain("activeIsImage2Tool ? (");
    expect(routeSource).toContain("styles.image2ModelPanel");
    expect(routeSource).toContain("API Key、base_url 和 provider 仍在设置页维护");
    expect(routeSource).not.toContain("apiKeyValue");
    expect(routeSource).not.toContain("baseUrlInput");
  });

  it("keeps test controls and result panels in normal document flow", () => {
    expect(routeSource).toContain("styles.policyPanel");
    expect(routeSource).toContain("styles.agentPolicyPanel");
    expect(routeSource).toContain("styles.image2ModelPanel");
    expect(routeSource).toContain("styles.detailActions");
    expect(routeSource.indexOf("styles.detailActions")).toBeGreaterThan(routeSource.indexOf("styles.policyPanel"));
    expect(routeSource.indexOf("styles.agentBulkPolicyPanel")).toBeLessThan(routeSource.indexOf("styles.detailHeader"));
    expect(routeSource.indexOf("styles.testPanel")).toBeGreaterThan(routeSource.indexOf("styles.detailActions"));
  });

  it("keeps raw args schema folded behind a disclosure", () => {
    expect(routeSource).toContain("<details className={styles.schemaDisclosure}>");
    expect(routeSource).toContain("<summary>");
    expect(routeSource).toContain("toolsShowSchema");
  });

  it("lets the left tool list collapse from the centered resize handle", () => {
    expect(routeSource).toContain("PaneCollapseHandle");
    expect(routeSource).toContain("leftPanelCollapsed");
    expect(routeSource).toContain("setLeftPanelCollapsed");
    expect(routeSource).toContain("--tools-left-panel-width");
  });
});
