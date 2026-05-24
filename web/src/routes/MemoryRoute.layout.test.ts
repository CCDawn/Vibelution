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

  it("splits memory into overview, effective scope, management, and source audit views", () => {
    expect(routeSource).toContain('export type MemoryRouteView = "overview" | "effective" | "manage" | "sources"');
    expect(routeSource).toContain("MEMORY_VIEWS");
    expect(routeSource).toContain("styles.subnav");
    expect(routeSource).toContain("renderOverviewView()");
    expect(routeSource).toContain("renderEffectiveView()");
    expect(routeSource).toContain("renderManageView()");
    expect(routeSource).toContain("renderSourcesView()");
    expect(routeSource).toContain('forcedView === "overview"');
    expect(routeSource).toContain('forcedView === "effective"');
    expect(routeSource).toContain('forcedView === "manage"');
  });

  it("surfaces agent visibility, prompt injection, and raw content in the detail pane", () => {
    expect(routeSource).toContain("activeItem.agentVisible");
    expect(routeSource).toContain("activeItem.inPrompt");
    expect(routeSource).toContain("<details className={styles.rawPanel} open>");
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
    expect(routeSource).toContain("channel: \"self_evolution\" as const");
    expect(routeSource).toContain("channel: \"supervised_evolution\" as const");
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

  it("is registered as an independent top-level route and global nav item", () => {
    expect(routerSource).toContain('path: "memory"');
    expect(routerSource).toContain('<MemoryRoute forcedView="overview" />');
    expect(routerSource).toContain('path: "memory/effective"');
    expect(routerSource).toContain('<MemoryRoute forcedView="effective" />');
    expect(routerSource).toContain('path: "memory/manage"');
    expect(routerSource).toContain('<MemoryRoute forcedView="manage" />');
    expect(routerSource).toContain('path: "memory/sources"');
    expect(routerSource).toContain('<MemoryRoute forcedView="sources" />');
    expect(appShellSource).toContain('to="/memory"');
    expect(appShellSource).toContain('t("navMemory")');
  });
});
