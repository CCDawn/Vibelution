import { describe, expect, it } from "vitest";

import routeSource from "./MemoryRoute.tsx?raw";
import routerSource from "../app/router.tsx?raw";
import appShellSource from "../app/AppShell.tsx?raw";

describe("MemoryRoute layout contract", () => {
  it("reads the read-only memory overview endpoint through the shared query key", () => {
    expect(routeSource).toContain("queryKeys.memoryOverview()");
    expect(routeSource).toContain('fetchJson<MemoryOverview>("/api/memory/overview")');
  });

  it("exposes manual memory management actions through guarded API mutations", () => {
    expect(routeSource).toContain("useMutation");
    expect(routeSource).toContain('fetchJson<MemoryMutationResponse>("/api/memory/items"');
    expect(routeSource).toContain('method: "POST"');
    expect(routeSource).toContain('method: "PATCH"');
    expect(routeSource).toContain('method: "DELETE"');
    expect(routeSource).toContain('memoryMutationEndpoint(sectionId, itemId, "/restore")');
    expect(routeSource).toContain("managedState");
    expect(routeSource).toContain("copy.addMemory");
    expect(routeSource).toContain("copy.editMemory");
    expect(routeSource).toContain("copy.disableMemory");
    expect(routeSource).toContain("copy.restoreMemory");
    expect(routeSource).toContain("copy.deleteMemory");
  });

  it("keeps source, item, and detail panels available in the source audit view", () => {
    const sourceAndItemRendererIndex = routeSource.indexOf("const renderSourceAndItemPanels");
    const sourcePanelIndex = routeSource.indexOf("styles.sourcePanel", sourceAndItemRendererIndex);
    const itemPanelIndex = routeSource.indexOf("styles.itemPanel", sourcePanelIndex);
    const sourcesViewIndex = routeSource.indexOf("const renderSourcesView");
    const sourcesWorkspaceIndex = routeSource.indexOf("styles.workspace", sourcesViewIndex);
    const sourcesPanelsIndex = routeSource.indexOf("renderSourceAndItemPanels(copy.sourceAudit)", sourcesWorkspaceIndex);
    const detailPanelIndex = routeSource.indexOf("renderDetailPanel()", sourcesPanelsIndex);

    expect(sourceAndItemRendererIndex).toBeGreaterThan(0);
    expect(sourcePanelIndex).toBeGreaterThan(0);
    expect(itemPanelIndex).toBeGreaterThan(sourcePanelIndex);
    expect(sourcesViewIndex).toBeGreaterThan(itemPanelIndex);
    expect(sourcesPanelsIndex).toBeGreaterThan(sourcesWorkspaceIndex);
    expect(detailPanelIndex).toBeGreaterThan(sourcesPanelsIndex);
  });

  it("splits memory into overview, effective scope, management, source audit, and team knowledge views", () => {
    expect(routeSource).toContain(
      'export type MemoryRouteView = "overview" | "effective" | "manage" | "sources" | "knowledge"',
    );
    expect(routeSource).toContain("MEMORY_VIEWS");
    expect(routeSource).toContain("styles.subnav");
    expect(routeSource).toContain("renderOverviewView()");
    expect(routeSource).toContain("renderEffectiveView()");
    expect(routeSource).toContain("renderManageView()");
    expect(routeSource).toContain("renderSourcesView()");
    expect(routeSource).toContain("renderKnowledgeView()");
    expect(routeSource).toContain('forcedView === "overview"');
    expect(routeSource).toContain('forcedView === "effective"');
    expect(routeSource).toContain('forcedView === "manage"');
    expect(routeSource).toContain('forcedView === "knowledge"');
  });

  it("wires the team knowledge platform to scoped overview, source, proposal, review, search, and governance APIs", () => {
    expect(routeSource).toContain("queryKeys.memoryUsageContract()");
    expect(routeSource).toContain('fetchJson<MemoryUsageContractPayload>("/api/memory/usage-contract")');
    expect(routeSource).toContain("queryKeys.knowledgeOverview()");
    expect(routeSource).toContain('fetchJson<TeamKnowledgeOverview>("/api/knowledge/overview")');
    expect(routeSource).toContain('sourceType: "manual_user_entry"');
    expect(routeSource).toContain("/source-artifacts");
    expect(routeSource).toContain("/refinement-proposals");
    expect(routeSource).toContain("/ingestion-packages");
    expect(routeSource).toContain("/review");
    expect(routeSource).toContain("/api/knowledge/search");
    expect(routeSource).toContain("/api/knowledge/governance/tasks");
    expect(routeSource).toContain("/api/knowledge/operations/health");
    expect(routeSource).toContain("/api/knowledge/governance/plan");
    expect(routeSource).toContain("/api/knowledge/steward/overview");
    expect(routeSource).toContain("/api/knowledge/steward/recommendations");
    expect(routeSource).toContain("/api/knowledge/steward/workbench");
    expect(routeSource).toContain("/api/knowledge/ingestion-adapters");
    expect(routeSource).toContain("/trace/");
    expect(routeSource).toContain("/rating-suggestions");
    expect(routeSource).toContain("/rating-suggestions/review-batch");
    expect(routeSource).toContain("/api/knowledge/permissions/audit");
    expect(routeSource).toContain("copy.approveProposal");
    expect(routeSource).toContain("copy.rejectProposal");
    expect(routeSource).toContain("copy.submitRatingSuggestion");
    expect(routeSource).toContain("copy.bulkApplySuggestions");
    expect(routeSource).toContain("copy.bulkRejectSuggestions");
    expect(routeSource).toContain("selectedRatingSuggestionIds");
    expect(routeSource).toContain("toggleVisibleRatingSuggestions");
    expect(routeSource).toContain("copy.permissionAudit");
    expect(routeSource).toContain("copy.ingestionPackage");
    expect(routeSource).toContain("copy.submitIngestionPackage");
    expect(routeSource).toContain("copy.governanceTasks");
    expect(routeSource).toContain("copy.usageContract");
    expect(routeSource).toContain("copy.memoryDomains");
    expect(routeSource).toContain("copy.forbiddenActions");
    expect(routeSource).toContain("styles.usageContractPanel");
    expect(routeSource).toContain("styles.contractDomainGrid");
    expect(routeSource).toContain("copy.operationsHealth");
    expect(routeSource).toContain("copy.governancePlan");
    expect(routeSource).toContain("copy.planOnly");
    expect(routeSource).toContain("searchMode");
    expect(routeSource).toContain("semanticScore");
    expect(routeSource).toContain("copy.ingestionAdapters");
    expect(routeSource).toContain("copy.traceability");
    expect(routeSource).toContain("copy.knowledgeSteward");
    expect(routeSource).toContain("knowledgeStewardQuery");
    expect(routeSource).toContain("styles.knowledgeStewardPanel");
    expect(routeSource).toContain("styles.stewardRecommendations");
    expect(routeSource).toContain("styles.stewardWorkbench");
    expect(routeSource).toContain("styles.stewardStageGrid");
    expect(routeSource).toContain("knowledgeStewardWorkbenchQuery");
    expect(routeSource).toContain("knowledgeStewardRecommendationsQuery");
    expect(routeSource).toContain("knowledgeOperationsHealthQuery");
    expect(routeSource).toContain("knowledgeGovernancePlanQuery");
    expect(routeSource).toContain("memoryUsageContractQuery");
    expect(routeSource).toContain("copy.noDirectApply");
    expect(routeSource).toContain("copy.reviewerRequired");
    expect(routeSource).toContain("copy.recommendationsOnly");
    expect(routeSource).toContain("copy.acceptanceChecklist");
  });

  it("shows a priority review queue on the default memory overview", () => {
    expect(routeSource).toContain("priorityReviewPairs");
    expect(routeSource).toContain("memoryPairPriority");
    expect(routeSource).toContain("reviewReasonLabels(copy, item)");
    expect(routeSource).toContain("memoryPairActionTarget(pair)");
    expect(routeSource).toContain("styles.reviewQueuePanel");
    expect(routeSource).toContain("styles.reviewQueueList");
    expect(routeSource).toContain("styles.reviewQueueTitleLine");
    expect(routeSource).toContain("styles.reviewQueueSummary");
    expect(routeSource).toContain("styles.reviewQueueTime");
    expect(routeSource).toContain("styles.reviewReasonPill");
    expect(routeSource).toContain("copy.reviewQueue");
    expect(routeSource).toContain("copy.reviewQueueHint");
    expect(routeSource).toContain("copy.auditMemory");
    expect(routeSource).toContain("copy.manageMemoryAction");
    expect(routeSource).toContain("reasonDisabled");
    expect(routeSource).toContain("reasonOverridden");
    expect(routeSource).toContain("reasonMissing");
    expect(routeSource).toContain("reasonTruncated");
    expect(routeSource).toContain("reasonInPrompt");
    expect(routeSource).toContain("reasonAgentVisible");
    expect(routeSource).toContain("reasonUserManaged");
  });

  it("makes memory management bulk selection and edit preview visible", () => {
    expect(routeSource).toContain("selectedMemoryKeys");
    expect(routeSource).toContain("bulkActionPending");
    expect(routeSource).toContain("toggleVisibleMemorySelection");
    expect(routeSource).toContain("runBulkMemoryAction");
    expect(routeSource).toContain("styles.bulkActionBar");
    expect(routeSource).toContain("styles.itemSelectionRow");
    expect(routeSource).toContain("styles.itemContentButton");
    expect(routeSource).toContain("renderMemoryList(flatVisibleItems, copy.noMatches, false, true)");
    expect(routeSource.indexOf("styles.manageListPanel")).toBeLessThan(routeSource.indexOf("styles.manageFormPanel"));
    expect(routeSource).toContain("copy.manageConfigPanel");
    expect(routeSource).toContain("copy.manageConfigHint");
    expect(routeSource).toContain("copy.manageListHint");
    expect(routeSource).toContain("type ManageFilterMode");
    expect(routeSource).toContain('next.set("manage", activeManageFilter)');
    expect(routeSource).toContain("normalizeManageFilterMode");
    expect(routeSource).toContain("itemMatchesManageFilter");
    expect(routeSource).toContain("copy.manageFilters");
    expect(routeSource).toContain("copy.sourceFilters");
    expect(routeSource).toContain("styles.manageFilterPanel");
    expect(routeSource).toContain("styles.manageSourceFilters");
    expect(routeSource).toContain("styles.sourceChip");
    expect(routeSource).toContain("const renderSelectedMemoryConfig");
    expect(routeSource).toContain("styles.selectedConfigSummary");
    expect(routeSource.indexOf("{renderSelectedMemoryConfig()}")).toBeGreaterThan(routeSource.indexOf("{renderManagementEditor()}"));
    expect(routeSource).toContain("copy.selectedCount");
    expect(routeSource).toContain("copy.bulkDisable");
    expect(routeSource).toContain("copy.bulkRestore");
    expect(routeSource).toContain("styles.editPreviewPanel");
    expect(routeSource).toContain("styles.editPreviewGrid");
  });

  it("surfaces agent visibility, prompt injection, and raw content in the detail pane", () => {
    expect(routeSource).toContain("activeItem.agentVisible");
    expect(routeSource).toContain("activeItem.inPrompt");
    expect(routeSource).toContain("<details className={styles.rawPanel} open={showEditor}>");
    expect(routeSource).toContain("activeItem.content");
    expect(routeSource).toContain("copySourceSummary");
    expect(routeSource).toContain("copySourcePath");
    expect(routeSource).toContain("copyRawContentAction");
    expect(routeSource).toContain("copyCurrentLink");
    expect(routeSource).toContain("copy.management");
    expect(routeSource).toContain("styles.managementPanel");
  });

  it("adds perception matrix and quick filters before the source drilldown", () => {
    expect(routeSource).toContain("styles.matrixPanel");
    expect(routeSource).toContain("copy.perceptionMatrix");
    expect(routeSource).toContain("styles.filterGroup");
    expect(routeSource).toContain("itemMatchesFilter");
    expect(routeSource).toContain("filterPrompt");
    expect(routeSource).toContain("filterMissing");
  });

  it("uses structured backend memory perception fields instead of usage text heuristics", () => {
    expect(routeSource).toContain("item.visibilityClass");
    expect(routeSource).toContain("item.channels.includes");
    expect(routeSource).toContain("itemChannelPills(copy, item)");
    expect(routeSource).toContain('"self_evolution"');
    expect(routeSource).toContain('"supervised_evolution"');
    expect(routeSource).not.toContain("function usageText");
    expect(routeSource).not.toContain('text.includes("');
  });

  it("keeps selected memory location in query params for deep links", () => {
    expect(routeSource).toContain("useSearchParams");
    expect(routeSource).toContain('searchParams.get("section")');
    expect(routeSource).toContain('searchParams.get("item")');
    expect(routeSource).toContain('searchParams.get("filter")');
    expect(routeSource).toContain('searchParams.get("channel")');
    expect(routeSource).toContain('searchParams.get("q")');
    expect(routeSource).toContain('const searchParamText = searchParams.toString();');
    expect(routeSource).toContain('next.set("channel", activeChannel)');
    expect(routeSource).toContain("setSearchParams(next, { replace: true })");
    expect(routeSource).toContain("next.toString() !== searchParamText");
  });

  it("lets perception matrix cards filter memory by channel", () => {
    expect(routeSource).toContain("type ChannelFilter");
    expect(routeSource).toContain("normalizeChannelFilter");
    expect(routeSource).toContain("itemMatchesChannelFilter");
    expect(routeSource).toContain("handleChannelCardClick");
    expect(routeSource).toContain("styles.matrixCardButton");
    expect(routeSource).toContain("styles.matrixCardActive");
    expect(routeSource).toContain("aria-pressed={activeChannel === card.channel}");
    expect(routeSource).toContain("onClick={() => handleChannelCardClick(card.channel)}");
    expect(routeSource).toContain("channel: \"research\" as const");
    expect(routeSource).toContain("channel: \"self_evolution\" as const");
    expect(routeSource).toContain("channel: \"supervised_evolution\" as const");
  });

  it("exposes research as a first-class memory channel", () => {
    expect(routeSource).toContain('type MemoryChannel = "conversation" | "research"');
    expect(routeSource).toContain('const MEMORY_CHANNELS: MemoryChannel[] = ["conversation", "research"');
    expect(routeSource).toContain("copy.researchMemory");
    expect(routeSource).toContain("copy.researchMemoryHint");
  });

  it("prioritizes impact explanation before raw memory content", () => {
    const impactIndex = routeSource.indexOf("styles.impactPanel");
    const rawPanelIndex = routeSource.indexOf("styles.rawPanel");

    expect(impactIndex).toBeGreaterThan(0);
    expect(rawPanelIndex).toBeGreaterThan(impactIndex);
    expect(routeSource).toContain("impactCopy(copy, activeItem)");
  });

  it("makes source origin and inspection actions directly visible in the UI", () => {
    expect(routeSource).toContain("sourceOriginLabel(section, item)");
    expect(routeSource).toContain("styles.itemOrigin");
    expect(routeSource).toContain("styles.detailActions");
    expect(routeSource).toContain("styles.detailActionButton");
    expect(routeSource).toContain("styles.copyNotice");
    expect(routeSource).toContain("section.sourceApi");
    expect(routeSource).toContain("handleCopySourcePath");
    expect(routeSource).toContain("activeItem.path || activeItem.source || activeSection.sourcePath");
  });

  it("keeps inspection actions compact enough for narrow detail panes", () => {
    expect(routeSource).toContain("styles.detailActions");
    expect(routeSource).toContain("styles.detailActionButton");
    expect(routeSource).toContain("copySourceSummary");
    expect(routeSource).toContain("copySourcePath");
    expect(routeSource).toContain("copyRawContentAction");
    expect(routeSource).toContain("copyCurrentLink");
  });

  it("keeps loaded memory visible when a later refresh fails", () => {
    expect(routeSource).toContain("showRefreshNotice");
    expect(routeSource).toContain("panelNotice");
    expect(routeSource).toContain("hasOverviewSections");
    expect(routeSource).toContain("refreshFailed");
    expect(routeSource).not.toContain("overviewQuery.isError ? (");
  });

  it("is registered as a primary Memory Library with legacy Agent memory redirects", () => {
    expect(routerSource).toContain('path: "memory"');
    expect(routerSource).toContain('<MemoryRoute forcedView="overview" />');
    expect(routerSource).toContain('path: "memory/effective"');
    expect(routerSource).toContain('<MemoryRoute forcedView="effective" />');
    expect(routerSource).toContain('path: "memory/manage"');
    expect(routerSource).toContain('<MemoryRoute forcedView="manage" />');
    expect(routerSource).toContain('path: "memory/sources"');
    expect(routerSource).toContain('<MemoryRoute forcedView="sources" />');
    expect(routerSource).toContain('path: "memory/knowledge"');
    expect(routerSource).toContain('<MemoryRoute forcedView="knowledge" />');
    expect(routerSource).toContain('path: "agents/memory"');
    expect(routerSource).toContain('<LegacyMemoryRedirect to="/memory" />');
    expect(routerSource).toContain('path: "agents/memory/effective"');
    expect(routerSource).toContain('<LegacyMemoryRedirect to="/memory/effective" />');
    expect(routerSource).toContain('path: "agents/memory/manage"');
    expect(routerSource).toContain('<LegacyMemoryRedirect to="/memory/manage" />');
    expect(routerSource).toContain('path: "agents/memory/sources"');
    expect(routerSource).toContain('<LegacyMemoryRedirect to="/memory/sources" />');
    expect(routerSource).toContain('path: "agents/memory/knowledge"');
    expect(routerSource).toContain('<LegacyMemoryRedirect to="/memory/knowledge" />');
    expect(routeSource).toContain('{ key: "overview", href: "/memory" }');
    expect(routeSource).toContain('to={`/memory/sources?section=');
    expect(routeSource).toContain('to={`/memory/manage?section=');
    expect(routeSource).not.toContain("AgentManagementNav");
    expect(routeSource.indexOf("{renderSubnav()}")).toBeLessThan(routeSource.indexOf("styles.viewStack"));
    expect(appShellSource).toContain('to="/memory"');
    expect(appShellSource).toContain('t("navMemory")');
  });

  it("visualizes the P1 team knowledge pipeline and prompt boundary", () => {
    expect(routeSource).toContain("copy.platformPipeline");
    expect(routeSource).toContain("copy.pipelineSource");
    expect(routeSource).toContain("copy.pipelineProposal");
    expect(routeSource).toContain("copy.pipelineBatch");
    expect(routeSource).toContain("copy.pipelineFormal");
    expect(routeSource).toContain("copy.pipelineRating");
    expect(routeSource).toContain("copy.toolReadableOnly");
    expect(routeSource).toContain("copy.promptBoundary");
    expect(routeSource).toContain("styles.pipelinePanel");
    expect(routeSource).toContain("styles.pipelineSteps");
  });
});
