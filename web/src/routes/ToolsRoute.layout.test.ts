import { describe, expect, it } from "vitest";

// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { readFileSync } from "node:fs";
import routeSource from "./ToolsRoute.tsx?raw";
import routerSource from "../app/router.tsx?raw";

const stylesSource = readFileSync(new URL("./ToolsRoute.module.css", import.meta.url), "utf-8");

describe("ToolsRoute layout contract", () => {
  it("lives inside Agent management navigation", () => {
    expect(routerSource).toContain('path: "agents/tools"');
    expect(routerSource).toContain("<ToolsRoute />");
    expect(routerSource).not.toContain('path: "tools"');
    expect(routerSource).not.toContain('to="/agents/tools" replace');
    expect(routeSource).toContain('<AgentManagementNav active="tools" className={styles.managementNav} />');
    expect(routeSource.indexOf('<AgentManagementNav active="tools" className={styles.managementNav} />')).toBeGreaterThan(
      routeSource.indexOf("</header>"),
    );
    expect(routeSource.indexOf('<AgentManagementNav active="tools" className={styles.managementNav} />')).toBeLessThan(
      routeSource.indexOf("styles.summaryGrid"),
    );
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
    expect(routeSource).toContain("testResultSummaryCards(visibleTestResult, t)");
    expect(routeSource).toContain("styles.resultCard");
  });

  it("keeps tool actions and test results scoped to the active tool and Agent", () => {
    expect(routeSource).toContain("type ScopedToolTestResult");
    expect(routeSource).toContain("toolTestKey(variables.toolId, variables.agentScopeId, variables.agentId)");
    expect(routeSource).toContain("const visibleTestResult = testResult?.key === activeToolTestKey ? testResult.result : null");
    expect(routeSource).toContain("enableMutation.variables?.toolId === activeTool?.id");
    expect(routeSource).toContain("deleteMutation.variables === activeTool?.id");
    expect(routeSource).toContain("activeToolTestPending");
    expect(routeSource).not.toContain("setTestResult(null);\n  }, [activeAgentScopeId, activePolicyAgentId, activeToolId]);");
  });

  it("groups the tool browser by tool packages instead of a flat tool list", () => {
    expect(routeSource).toContain("toolsQuery.data?.toolBundles");
    expect(routeSource).toContain("toolBundleGroups");
    expect(routeSource).toContain("visibleToolBundleGroups");
    expect(routeSource).toContain("tool.bundleIds");
    expect(routeSource).toContain("styles.toolBundleGroup");
    expect(routeSource).toContain("styles.toolBundleHeader");
    expect(routeSource).toContain("所属工具包");
    expect(routeSource).not.toContain("{visibleTools.map((tool)");
  });

  it("supports agent-scoped tool lists and test requests", () => {
    expect(routeSource).toContain("activeAgentScopeId");
    expect(routeSource).toContain("toolsQuery.data?.agentScopes");
    expect(routeSource).toContain("styles.agentScopeBar");
    expect(routeSource).toContain("scopeStateForTool(tool, activeAgentScopeId)");
    expect(routeSource).toContain("JSON.stringify({ args: {}, agentScope: payload.agentScopeId, agentId: payload.agentId })");
    expect(routeSource).toContain("agentId: activePolicyAgent.agentId");
  });

  it("keeps Agent ToolPolicy state lightweight and routes configuration to Agent Center", () => {
    expect(routeSource).toContain("fetchJson<AgentInstance[]>(\"/api/agents\")");
    expect(routeSource).toContain("const agentPolicyWorkspaceNeeded = Boolean(activeTool)");
    expect(routeSource).toContain("enabled: agentPolicyWorkspaceNeeded");
    expect(routeSource).toContain("这里用于测试工具，不在这里配置 Agent");
    expect(routeSource).toContain("Test tools here, configure Agents in Agent Center");
    expect(routeSource).toContain("styles.agentPermissionSummaryPanel");
    expect(routeSource).toContain("styles.permissionSummaryGrid");
    expect(routeSource).toContain("styles.permissionSummaryCards");
    expect(routeSource).toContain("styles.toolAgentFitPanel");
    expect(routeSource).toContain("styles.policyStatePill");
    expect(routeSource).toContain("to=\"/agents\"");
    expect(routeSource).toContain("去 Agent 中心配置");
    expect(routeSource).toContain("编辑 Agent 策略");
    expect(routeSource).not.toContain("toolPolicyMutation");
    expect(routeSource).not.toContain("body: JSON.stringify({ toolPolicy: payload.policy })");
  });

  it("avoids fixed registry and Agent polling on the Tools workspace", () => {
    expect(routeSource).toContain("fetchJson<ToolRegistryPayload>(\"/api/tools\")");
    expect(routeSource).toContain("void queryClient.invalidateQueries({ queryKey: queryKeys.agents() })");
    expect(routeSource).toContain("activeIsWebSearchTool ? resolvePollingInterval(pageVisible, 15_000) : false");
    expect(routeSource).not.toContain("resolvePollingInterval(pageVisible, 8_000)");
    expect(routeSource).not.toContain("resolvePollingInterval(pageVisible, 12_000)");
  });

  it("calls out tools that require explicit Agent allow-list permission", () => {
    expect(routeSource).toContain("explicit_required");
    expect(routeSource).toContain("tool.permissionPolicy?.requiresExplicitAllow");
    expect(routeSource).toContain("需显式授权");
    expect(routeSource).toContain("policyModeCounts.explicit_required");
    expect(routeSource).toContain("policy_${policyMode}");
    expect(routeSource).toContain("policy_${activePolicyMode}");
  });

  it("removes the duplicate Agent permission table from Tools", () => {
    expect(routeSource).not.toContain("permissionTools");
    expect(routeSource).not.toContain("PERMISSION_FILTERS");
    expect(routeSource).not.toContain("permissionSearchText");
    expect(routeSource).not.toContain("setPermissionFilter(filter)");
    expect(routeSource).not.toContain("setPermissionSearchText(event.target.value)");
    expect(routeSource).not.toContain("styles.agentBulkPolicyPanel");
    expect(routeSource).not.toContain("styles.bulkPolicyToolRow");
    expect(routeSource).not.toContain("styles.bulkPolicyActions");
    expect(routeSource).not.toContain("styles.agentPolicyPanel");
    expect(routeSource).not.toContain("policyDraft");
    expect(routeSource).not.toContain("setSelectedToolsPolicyMode");
    expect(routeSource).not.toContain("applyPolicyDraft");
  });

  it("lets the image2 tool choose a configured model without exposing provider secrets", () => {
    expect(routeSource).toContain("IMAGE2_TOOL_NAME = \"image2_generate_tool\"");
    expect(routeSource).toContain("fetchJson<ToolImage2ModelConfig>(\"/api/tools/image2/models\")");
    expect(routeSource).toContain("fetchJson<ToolImage2ModelConfig>(\"/api/tools/image2/default-model\"");
    expect(routeSource).toContain("activeIsImage2Tool ? (");
    expect(routeSource).toContain("styles.image2ModelPanel");
    expect(routeSource).toContain("模型名会在调用前按远端 /v1/models 发现结果解析");
    expect(routeSource).toContain("image2DiscoveryStateLabel");
    expect(routeSource).toContain("selectedModel.resolvedModel");
    expect(routeSource).not.toContain("apiKeyValue");
    expect(routeSource).not.toContain("baseUrlInput");
  });

  it("shows web search dependency health only for the selected search tool", () => {
    expect(routeSource).toContain("WEB_SEARCH_TOOL_NAME = \"web_search_tool\"");
    expect(routeSource).toContain("activeIsWebSearchTool");
    expect(routeSource).toContain("fetchJson<ToolDependencyHealth>(\"/api/tools/web-search/health\")");
    expect(routeSource).toContain("enabled: activeIsWebSearchTool");
    expect(routeSource).toContain("styles.dependencyHealthPanel");
    expect(routeSource).toContain("AUTOGLM_TOKEN_URL");
    expect(routeSource).not.toContain("fetchJson<ToolRegistryPayload>(\"/api/tools/web-search/health\")");
  });

  it("keeps test controls and result panels in normal document flow", () => {
    expect(routeSource).toContain("styles.policyPanel");
    expect(routeSource).toContain("styles.toolAgentFitPanel");
    expect(routeSource).toContain("styles.image2ModelPanel");
    expect(routeSource).toContain("styles.detailActions");
    expect(routeSource.indexOf("styles.detailActions")).toBeGreaterThan(routeSource.indexOf("styles.policyPanel"));
    expect(routeSource.indexOf("styles.dependencyHealthPanel")).toBeLessThan(routeSource.indexOf("styles.policyPanel"));
    expect(routeSource.indexOf("styles.agentPermissionSummaryPanel")).toBeLessThan(routeSource.indexOf("styles.detailHeader"));
    expect(routeSource.indexOf("styles.agentPermissionSummaryPanel")).toBeGreaterThan(0);
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

  it("supports bulk selection while preserving tool registry safety rules", () => {
    expect(routeSource).toContain("selectedToolIds");
    expect(routeSource).toContain("bulkSetToolsEnabled");
    expect(routeSource).toContain("bulkDeleteTools");
    expect(routeSource).toContain("bulkCopy.deleteConfirm");
    expect(routeSource).toContain("window.confirm(bulkCopy.deleteConfirm)");
    const bulkDeleteSection = routeSource.slice(routeSource.indexOf("async function bulkDeleteTools"));
    expect(bulkDeleteSection.indexOf("window.confirm(bulkCopy.deleteConfirm)")).toBeLessThan(
      bulkDeleteSection.indexOf("fetchJson<GeneratedToolDeleteResponse>"),
    );
    expect(routeSource).toContain("canBulkToggleTool(tool)");
    expect(routeSource).toContain("tool.deleteAllowed");
    expect(routeSource).toContain("fetchJson<ToolRegistryItem>(`/api/tools/generated/");
    expect(routeSource).toContain("fetchJson<GeneratedToolDeleteResponse>(`/api/tools/");
    expect(routeSource).toContain("styles.bulkActionBar");
    expect(routeSource).toContain("styles.selectableToolRow");
  });

  it("keeps long tool descriptions readable in the dense tool browser", () => {
    expect(stylesSource).toContain(".toolCopy span");
    expect(stylesSource).toContain("display: -webkit-box");
    expect(stylesSource).toContain("-webkit-line-clamp: 2");
    expect(stylesSource).toContain("white-space: normal");
    expect(stylesSource).toContain("align-items: start");
  });

  it("keeps bulk controls in compact document flow instead of covering tool rows", () => {
    expect(stylesSource).toContain(".listPanel {\n  grid-template-rows: auto auto auto auto minmax(0, 1fr);\n  overflow: hidden;");
    expect(stylesSource).toContain(".bulkActionBar {\n  display: grid;");
    expect(stylesSource).toContain("grid-template-columns: minmax(0, 1fr) auto auto");
    expect(stylesSource).toContain(".toolList {\n  display: grid;\n  align-content: start;\n  gap: 7px;");
    expect(stylesSource).toContain("@media (max-width: 980px)");
    expect(stylesSource).toContain(".bulkActionBar .dangerButton");
  });

  it("reflows Agent permission summary before desktop narrow widths squeeze labels vertical", () => {
    expect(stylesSource).toContain(".permissionSummaryGrid");
    expect(stylesSource).toContain("grid-template-columns: minmax(220px, 0.55fr) minmax(0, 1fr) auto");
    expect(stylesSource).toContain("@media (max-width: 1180px)");
    expect(stylesSource).toContain("grid-template-columns: minmax(0, 1fr) auto");
    expect(stylesSource).toContain("grid-column: 1 / -1");
    expect(stylesSource).toContain("grid-template-columns: repeat(5, minmax(52px, 1fr))");
  });
});
