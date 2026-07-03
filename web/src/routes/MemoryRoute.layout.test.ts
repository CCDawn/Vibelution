import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import routeSource from "./MemoryRoute.tsx?raw";
import agentMemoryPanelSource from "./MemoryAgentMemoryPanel.tsx?raw";
import cleanupPanelSource from "./MemoryCleanupPanel.tsx?raw";
import detailPanelSource from "./MemoryDetailPanel.tsx?raw";
import effectivePanelSource from "./MemoryEffectivePanel.tsx?raw";
import knowledgeRagPanelSource from "./MemoryKnowledgeRagPanel.tsx?raw";
import knowledgeStewardPanelSource from "./MemoryKnowledgeStewardPanel.tsx?raw";
import managementEditorSource from "./MemoryManagementEditor.tsx?raw";
import managePanelSource from "./MemoryManagePanel.tsx?raw";
import matrixPanelSource from "./MemoryMatrixPanel.tsx?raw";
import overviewPanelSource from "./MemoryOverviewPanel.tsx?raw";
import projectMemoryQueuePanelSource from "./MemoryProjectMemoryQueuePanel.tsx?raw";
import reviewQueuePanelSource from "./MemoryReviewQueuePanel.tsx?raw";
import selectedConfigPanelSource from "./MemorySelectedConfigPanel.tsx?raw";
import sourceAndItemPanelsSource from "./MemorySourceAndItemPanels.tsx?raw";
import warningStripSource from "./MemoryWarningStrip.tsx?raw";
import routerSource from "../app/router.tsx?raw";
import appShellSource from "../app/AppShell.tsx?raw";
import graphCanvasSource from "./MemoryGraphCanvas.tsx?raw";
import styles from "./MemoryRoute.styles";
import stylesModuleSource from "./MemoryRoute.styles.ts?raw";

const memoryCssSource = [
  stylesModuleSource,
  ...Object.keys(styles).map((key) => `.${key}`),
  ...Object.values(styles),
].join("\n");
const graphWorkerSource = readFileSync(new URL("./memoryGraphLayout.worker.ts", import.meta.url), "utf-8");

describe("MemoryRoute layout contract", () => {
  it("uses shell language state without loading the full app dictionary", () => {
    expect(routeSource).toContain("useShellI18n");
    expect(routeSource).toContain("const { lang } = useShellI18n()");
    expect(routeSource).not.toContain("useAppI18n");
  });

  it("reads the read-only memory overview endpoint through the shared query key", () => {
    expect(routeSource).toContain("queryKeys.memoryOverview()");
    expect(routeSource).toContain('fetchJson<MemoryOverview>("/api/memory/overview?includeContent=false")');
    expect(routeSource).toContain("queryKeys.memoryItemDetail(activeSection?.id ?? \"\", activeItem?.id ?? \"\")");
    expect(routeSource).toContain("/api/memory/items/${encodeURIComponent(activeSection?.id ?? \"\")}/${encodeURIComponent(activeItem?.id ?? \"\")}");
    expect(routeSource).toContain("queryKeys.memoryItemDetails()");
  });

  it("reads Agent-private memory through the dedicated inventory API", () => {
    expect(routeSource).toContain("AgentMemoryInventoryPayload");
    expect(routeSource).toContain('fetchJson<AgentMemoryInventoryPayload>("/api/memory/agents")');
    expect(routeSource).toContain(
      "`/api/memory/agents/${encodeURIComponent(selectedAgentMemoryAgentId)}?actorAgentId=${encodeURIComponent(selectedAgentMemoryAgentId)}`",
    );
    expect(routeSource).toContain("createAgentMemoryPanel()");
    expect(routeSource).toContain("copy.agentMemoryView");
    expect(agentMemoryPanelSource).toContain("copy.agentMemoryPrivateFiles");
    expect(routeSource).toContain("styles.agentMemoryViewStack");
    expect(memoryCssSource).toContain(".agentMemoryViewStack");
    expect(memoryCssSource).toContain(".agentMemoryWorkspace");
    expect(routeSource).toContain('from "./MemoryAgentMemoryPanel"');
    expect(routeSource).toContain("<MemoryAgentMemoryPanel");
    expect(routeSource).not.toContain("const renderAgentMemoryView = () =>");
    expect(agentMemoryPanelSource).toContain("export function MemoryAgentMemoryPanel");
    expect(agentMemoryPanelSource).toContain("styles.agentMemoryWorkspace");
    expect(agentMemoryPanelSource).toContain("styles.sourcePanel");
    expect(agentMemoryPanelSource).toContain("styles.itemPanel");
    expect(agentMemoryPanelSource).toContain("styles.detailPanel");
    expect(agentMemoryPanelSource).not.toContain("useQuery");
    expect(agentMemoryPanelSource).not.toContain("useMutation");
    expect(agentMemoryPanelSource).not.toContain("fetchJson");
  });

  it("supports returning from Agent Center deep links", () => {
    expect(routeSource).toContain("safeAgentCenterReturnToPath");
    expect(routeSource).toContain("const returnToPath = useMemo(() => safeAgentCenterReturnToPath(searchParams.get(\"returnTo\")), [searchParamText])");
    expect(routeSource).toContain("const returnToLabel = searchParams.get(\"returnLabel\") === \"agents\" ? copy.returnToAgents : copy.returnToSource");
    expect(routeSource).toContain("className={styles.returnButton}");
    expect(routeSource).toContain("to={returnToPath}");
    expect(styles.returnButton).toBeTypeOf("string");
    expect(styles.headerActions).toContain("justify-end");
  });

  it("exposes manual memory management actions through guarded API mutations", () => {
    expect(routeSource).toContain("useMutation");
    expect(routeSource).toContain('fetchJson<MemoryMutationResponse>("/api/memory/items"');
    expect(routeSource).toContain('method: "POST"');
    expect(routeSource).toContain('method: "PATCH"');
    expect(routeSource).toContain('method: "DELETE"');
    expect(routeSource).toContain('memoryMutationEndpoint(sectionId, itemId, "/restore")');
    expect(routeSource).toContain("managedState");
    expect(managePanelSource).toContain("copy.addMemory");
    expect(managePanelSource).toContain("copy.editMemory");
    expect(selectedConfigPanelSource).toContain("copy.disableMemory");
    expect(selectedConfigPanelSource).toContain("copy.restoreMemory");
    expect(selectedConfigPanelSource).toContain("copy.deleteMemory");
  });

  it("surfaces the project-memory proposal queue without implying a coordinator role", () => {
    expect(routeSource).toContain("AgentProjectMemoryUpdateProposal");
    expect(routeSource).toContain("queryKeys.agentProjectMemoryUpdates");
    expect(routeSource).toContain("/api/agents/project-memory-updates?");
    expect(routeSource).toContain("/project-memory-updates/");
    expect(routeSource).toContain('resolvedBy: "user"');
    expect(routeSource).toContain("projectMemoryProposalResolverLabel");
    expect(routeSource).toContain("旧治理记录");
    expect(routeSource).toContain("copy.projectMemoryQueue");
    expect(routeSource).toContain("copy.projectMemoryQueueApply");
    expect(routeSource).toContain("copy.projectMemoryQueueConflict");
    expect(routeSource).toContain('import { MemoryProjectMemoryQueuePanel } from "./MemoryProjectMemoryQueuePanel"');
    expect(routeSource).toContain("<MemoryProjectMemoryQueuePanel");
    expect(routeSource).not.toContain("const renderProjectMemoryQueue = () => {");
    expect(projectMemoryQueuePanelSource).toContain("export function MemoryProjectMemoryQueuePanel");
    expect(projectMemoryQueuePanelSource).toContain("className={styles.projectMemoryQueuePanel}");
    expect(projectMemoryQueuePanelSource).toContain("VNativeInput");
    expect(projectMemoryQueuePanelSource).not.toContain("useQuery");
    expect(projectMemoryQueuePanelSource).not.toContain("useMutation");
    expect(projectMemoryQueuePanelSource).not.toContain("fetchJson");
    expect(memoryCssSource).toContain(".projectMemoryQueuePanel");
    expect(memoryCssSource).toContain(".projectMemoryProposalRow");
  });

  it("keeps source, item, and detail panels available in the source audit view", () => {
    const sourcePanelIndex = sourceAndItemPanelsSource.indexOf("styles.sourcePanel");
    const itemPanelIndex = sourceAndItemPanelsSource.indexOf("styles.itemPanel", sourcePanelIndex);
    const sourcesViewIndex = routeSource.indexOf("const renderSourcesView");
    const sourcesWorkspaceIndex = routeSource.indexOf("styles.workspace", sourcesViewIndex);
    const sourcesPanelsIndex = routeSource.indexOf("createSourceAndItemPanels(copy.sourceAudit)", sourcesWorkspaceIndex);
    const detailPanelIndex = routeSource.indexOf("createDetailPanel()", sourcesPanelsIndex);

    expect(sourcePanelIndex).toBeGreaterThan(0);
    expect(itemPanelIndex).toBeGreaterThan(sourcePanelIndex);
    expect(sourcesViewIndex).toBeGreaterThan(0);
    expect(sourcesPanelsIndex).toBeGreaterThan(sourcesWorkspaceIndex);
    expect(detailPanelIndex).toBeGreaterThan(sourcesPanelsIndex);
  });

  it("keeps the source audit filter stable instead of deriving focus from the first item", () => {
    expect(routeSource).toContain("const activePair =\n    activeItemId\n      ? flatVisibleItems.find(({ item }) => item.id === activeItemId) ?? null\n      : null;");
    expect(routeSource).toContain('const activePairKey = activePair ? pairSelectionKey(activePair.section.id, activePair.item.id) : "";');
    expect(routeSource).toContain("const active = itemKey === activePairKey;");
    expect(routeSource).toContain("onSelectAllSections={() => {\n        setActiveItemId(\"\");\n        setActiveSectionId(\"\");\n      }}");
    expect(routeSource).toContain("onSelectSection={(sectionId) => {\n        setActiveItemId(\"\");\n        setActiveSectionId(sectionId);\n      }}");
    expect(routeSource).toContain("itemTitle={selectedSection?.title ?? title}");
    expect(routeSource).not.toContain("flatVisibleItems.find(({ item }) => item.id === activeItemId) ?? flatVisibleItems[0]");
    expect(routeSource).not.toContain("setActiveItemId(flatVisibleItems[0]?.item.id ?? \"\")");
  });

  it("delegates source and item audit panels to a dedicated view component", () => {
    expect(routeSource).toContain('from "./MemorySourceAndItemPanels"');
    expect(routeSource).toContain("<MemorySourceAndItemPanels");
    expect(routeSource).not.toContain("const renderSourceAndItemPanels = (title: string) => (");

    expect(sourceAndItemPanelsSource).toContain("export function MemorySourceAndItemPanels");
    expect(sourceAndItemPanelsSource).toContain("styles.sourcePanel");
    expect(sourceAndItemPanelsSource).toContain("styles.itemPanel");
    expect(sourceAndItemPanelsSource).toContain("styles.filterGroup");
    expect(sourceAndItemPanelsSource).not.toContain("useQuery");
    expect(sourceAndItemPanelsSource).not.toContain("useMutation");
    expect(sourceAndItemPanelsSource).not.toContain("fetchJson");
  });

  it("splits memory into overview, effective scope, Agent memory, source management, source audit, team knowledge, graph, and cleanup views", () => {
    expect(routeSource).toContain(
      'export type MemoryRouteView = "overview" | "effective" | "agents" | "manage" | "sources" | "knowledge" | "graph" | "cleanup"',
    );
    expect(routeSource).toContain("MEMORY_VIEWS");
    expect(routeSource).toContain("styles.subnav");
    expect(routeSource).toContain("<MemoryOverviewPanel");
    expect(routeSource).toContain("createEffectivePanel()");
    expect(routeSource).toContain("createAgentMemoryPanel()");
    expect(routeSource).toContain("createManagePanel()");
    expect(routeSource).toContain("renderSourcesView()");
    expect(routeSource).toContain("renderKnowledgeView()");
    expect(routeSource).toContain("renderGraphView()");
    expect(routeSource).toContain("createCleanupPanel()");
    expect(routeSource).toContain('forcedView === "overview"');
    expect(routeSource).toContain('forcedView === "effective"');
    expect(routeSource).toContain('forcedView === "agents"');
    expect(routeSource).toContain('forcedView === "manage"');
    expect(routeSource).toContain('forcedView === "knowledge"');
    expect(routeSource).toContain('forcedView === "graph"');
    expect(routeSource).toContain('forcedView === "cleanup"');
  });

  it("does not expose the removed workspace migration compatibility controls", () => {
    expect(routeSource).not.toContain("/api/storage/workspace-migration");
    expect(routeSource).not.toContain("/api/storage/legacy-workspace");
    expect(routeSource).not.toContain("WorkspaceMigrationStatus");
    expect(routeSource).not.toContain("LegacyWorkspaceCleanupPreview");
    expect(routeSource).not.toContain("硬删除旧 workspace");
  });

  it("keeps dense Memory workspaces bounded with internal scrolling", () => {
    expect(styles.route).toContain("grid-rows-[auto_auto_minmax(0,1fr)]");
    expect(styles.viewStack).toContain("h-full");
    expect(styles.viewStack).toContain("min-h-0");
    expect(styles.viewStack).toContain("overflow-hidden");
    expect(styles.workspace).toContain("h-full");
    expect(styles.workspace).toContain("min-h-0");
    expect(styles.workspace).toContain("grid-rows-[minmax(0,1fr)]");
    expect(styles.workspace).toContain("overflow-auto");
    expect(styles.detailPanel).toContain("min-h-0");
    expect(styles.detailPanel).toContain("overflow-auto");
    expect(styles.emptyDetail).toContain("min-h-[96px]");
    expect(styles.summaryGrid).toContain("grid-cols-[repeat(6,minmax(118px,1fr))]");
    expect(styles.summaryCard).toContain("grid-cols-[minmax(0,1fr)_auto]");
    expect(styles.overviewGrid).toContain("grid-cols-[repeat(2,minmax(0,1fr))]");
    expect(styles.reviewQueuePanel).toContain("max-h-[min(280px,34vh)]");
    expect(styles.reviewQueueList).toContain("overflow-auto");
    expect(styles.compactItemPrimary).toContain("flex");
    expect(styles.compactItemPrimary).not.toContain("rounded-[var(--radius-control)]");
    expect(styles.compactItemSummary).toContain("line-clamp-2");
    expect(styles.overviewPanel).toContain("grid-rows-[auto_minmax(0,1fr)]");
    expect(styles.overviewPanel).toContain("overflow-auto");
  });

  it("delegates the dense overview body to a dedicated panel component", () => {
    expect(routeSource).toContain('import { MemoryOverviewPanel } from "./MemoryOverviewPanel"');
    expect(routeSource).toContain("<MemoryOverviewPanel");
    expect(routeSource).not.toContain("const renderOverviewView = () => (");

    expect(overviewPanelSource).toContain("export function MemoryOverviewPanel");
    expect(overviewPanelSource).toContain("className={styles.summaryGrid}");
    expect(overviewPanelSource).toContain("className={styles.reviewQueuePanel}");
    expect(overviewPanelSource).toContain("className={styles.overviewGrid}");
    expect(overviewPanelSource).not.toContain("useQuery");
    expect(overviewPanelSource).not.toContain("useMutation");
    expect(overviewPanelSource).not.toContain("fetchJson");
  });

  it("delegates diagnostic warnings to a dedicated warning strip component", () => {
    expect(routeSource).toContain('import { MemoryWarningStrip } from "./MemoryWarningStrip"');
    expect(routeSource).toContain("<MemoryWarningStrip");
    expect(routeSource).not.toContain("const renderWarningStrip = () =>");

    expect(warningStripSource).toContain("export function MemoryWarningStrip");
    expect(warningStripSource).toContain("styles.warningStrip");
    expect(warningStripSource).toContain("TriangleAlert");
    expect(warningStripSource).toContain("warnings.join");
    expect(warningStripSource).not.toContain("useQuery");
    expect(warningStripSource).not.toContain("useMutation");
    expect(warningStripSource).not.toContain("fetchJson");
  });

  it("preserves a compact narrow Memory layout without turning every detail pane full width", () => {
    expect(styles.manageWorkspace).toContain("grid-cols-[minmax(300px,0.76fr)_minmax(0,1fr)]");
    expect(styles.manageWorkspace).toContain("grid-rows-[minmax(0,0.58fr)_minmax(0,1fr)]");
    expect(styles.manageWorkspace).toContain("h-full");
    expect(styles.manageWorkspace).toContain("overflow-hidden");
    expect(styles.manageWorkspace).toContain("[&_.manageListPanel]:row-span-2");
    expect(styles.manageWorkspace).toContain("[&_.detailPanel]:col-start-2");
    expect(styles.manageWorkspace).toContain("[&_.detailPanel]:row-start-2");
    expect(styles.manageWorkspace).toContain("[&_.detailPanel]:max-h-none");
    expect(styles.reviewReasonList).toContain("hidden");
  });

  it("lets routed Memory subviews fill the route slot before their own panels scroll", () => {
    for (const viewClassName of [styles.agentMemoryViewStack, styles.knowledgeViewStack, styles.graphViewStack]) {
      expect(viewClassName).toContain("h-full");
      expect(viewClassName).toContain("min-h-0");
      expect(viewClassName).toContain("overflow-hidden");
    }

    for (const workspaceClassName of [styles.agentMemoryWorkspace, styles.knowledgeWorkspace, styles.graphWorkspace]) {
      expect(workspaceClassName).toContain("h-full");
      expect(workspaceClassName).toContain("min-h-0");
      expect(workspaceClassName).toContain("overflow-hidden");
    }

    expect(styles.cleanupWorkspace).toContain("h-full");
    expect(styles.cleanupWorkspace).toContain("min-h-0");
    expect(styles.cleanupWorkspace).toContain("overflow-auto");
    expect(styles.graphCanvasPanel).toContain("h-full");
    expect(styles.graphCanvasPanel).toContain("overflow-hidden");
    expect(styles.sourcePanel).toContain("min-h-0");
    expect(styles.itemPanel).toContain("min-h-0");
  });

  it("keeps restored MemoryRoute grids from the CSS module migration", () => {
    const restoredGridExpectations: Array<[string, string]> = [
      [styles.matrixCard, "grid-cols-[minmax(0,1fr)_auto]"],
      [styles.projectMemoryProposalTitleLine, "grid-cols-[minmax(0,1fr)_auto]"],
      [styles.reviewQueueTitleLine, "grid-cols-[minmax(0,0.62fr)_minmax(82px,0.38fr)]"],
      [styles.manageSourceFilters, "grid-cols-[repeat(auto-fit,minmax(82px,1fr))]"],
      [styles.sourceButton, "grid-cols-[24px_minmax(0,1fr)_auto]"],
      [styles.contractDomainRow, "grid-cols-[minmax(116px,1fr)_minmax(96px,0.8fr)_auto]"],
      [styles.collapsedFormButton, "grid-cols-[auto_minmax(0,1fr)_auto]"],
      [styles.sourceRecordHeader, "grid-cols-[minmax(0,1fr)_auto]"],
      [styles.queueToolbar, "grid-cols-[repeat(2,minmax(0,1fr))]"],
      [styles.ragHealthStrip, "grid-cols-[repeat(auto-fit,minmax(108px,1fr))]"],
      [styles.cleanupTargetRow, "grid-cols-[18px_minmax(0,1fr)]"],
      [styles.visibilityHeader, "grid-cols-[22px_minmax(0,1fr)]"],
    ];

    for (const [className, gridTemplate] of restoredGridExpectations) {
      expect(className).toContain("!grid");
      expect(className).toContain(gridTemplate);
    }

    expect(styles.knowledgeViewStack).toContain("!flex");
    expect(styles.knowledgeViewStack).toContain("[&>.summaryGrid]:[grid-template-columns:repeat(4,minmax(0,1fr))]");
    expect(styles.knowledgeViewStack).not.toContain("[&>.summaryGrid]:grid-cols-");
  });

  it("wires the read-only 3D memory knowledge graph API and canvas shell", () => {
    expect(routeSource).toContain('queryKeys.memoryKnowledgeGraph(fallbackKnowledgeActorAgentId, "officialResearchGraph", requestedTeamId)');
    expect(routeSource).toContain('appendAgentParam(new URLSearchParams({ include: "officialResearchGraph" }), fallbackKnowledgeActorAgentId)');
    expect(routeSource).toContain("fetchJson<MemoryKnowledgeGraphPayload>(`/api/memory/knowledge-graph?${params.toString()}`)");
    expect(routeSource).toContain("MemoryKnowledgeGraphNodeDetailPayload");
    expect(routeSource).toContain("queryKeys.memoryKnowledgeGraphNodeDetail(selectedGraphNodeId, fallbackKnowledgeActorAgentId)");
    expect(routeSource).toContain('appendAgentParam(new URLSearchParams({ nodeId: selectedGraphNodeId }), fallbackKnowledgeActorAgentId)');
    expect(routeSource).toContain("/api/memory/knowledge-graph/node-detail?");
    expect(routeSource).toContain("selectedGraphDetailItems");
    expect(routeSource).toContain("copy.graphKnowledgeLoading");
    expect(routeSource).toContain("copy.graphKnowledgeTruncated");
    expect(routeSource).toContain("styles.graphKnowledgeContent");
    expect(routeSource).toContain("MemoryGraphCanvas");
    expect(routeSource).toContain("copy.graphGpu");
    expect(routeSource).toContain("copy.graphWorker");
    expect(routeSource).toContain("copy.graphReadOnly");
    expect(routeSource).toContain("copy.graphAcl");
    expect(routeSource).toContain("copy.graphInteractionHint");
    expect(routeSource).toContain("graphSearchText");
    expect(routeSource).toContain("activeGraphNodeType");
    expect(routeSource).toContain("selectedGraphNodeId");
    expect(routeSource).toContain("graphNodesMatchingSearch");
    expect(routeSource).toContain("copy.graphVisibleNodes");
    expect(routeSource).toContain("copy.graphVisibleEdges");
    expect(routeSource).toContain("copy.graphClearFocus");
    expect(routeSource).toContain("selectedGraphRelations");
    expect(routeSource).toContain("selectedGraphChildren");
    expect(routeSource).toContain("selectGraphNode");
    expect(routeSource).toContain("copy.graphResponsibilityQuestion");
    expect(routeSource).toContain("copy.graphDirectChildren");
    expect(routeSource).toContain("copy.graphNodeKnowledge");
    expect(routeSource).toContain("styles.graphResponsibilityPanel");
    expect(routeSource).toContain("styles.graphKnowledgePanel");
    expect(routeSource).toContain("copy.graphRelations");
    expect(routeSource).toContain("copy.graphIncoming");
    expect(routeSource).toContain("copy.graphOutgoing");
    expect(routeSource).toContain("copy.graphNoRelations");
    expect(routeSource).toContain("styles.graphRelationPanel");
    expect(routeSource).toContain("styles.graphRelationGroup");
    expect(routeSource).toContain("styles.graphClearFocusButton");
    expect(routeSource).toContain("styles.graphWorkspace");
    expect(routeSource).toContain("styles.graphCanvasPanel");
    expect(routeSource).toContain("styles.graphTypeList");
    expect(routeSource).toContain("next.set(\"agentId\", agentId.trim())");
    expect(routeSource).toContain("requestedKnowledgeActorAgentId,");
    expect(routeSource).toContain("buildMemoryLink(activeSectionId, activeItemId, activeFilter, activeManageFilter, activeChannel, searchText, requestedKnowledgeActorAgentId)");
    expect(routeSource).toContain("GRAPH_NODE_TYPE_LABELS");
    expect(routeSource).toContain("styles.graphNodeTypeMark");
    expect(routeSource).toContain("data-node-type");
    expect(routeSource).toContain("data-active");
    expect(routeSource).toContain("setActiveGraphNodeType");
    expect(routeSource).toContain("setSelectedGraphNodeId(\"\")");
    expect(graphCanvasSource).toContain("graphCanvasLabels");
    expect(graphCanvasSource).toContain("graphNodeBadge");
    expect(graphCanvasSource).toContain('DragMode = "rotate" | "pan"');
    expect(graphCanvasSource).toContain('event.button === 1 ? "pan" : "rotate"');
    expect(graphCanvasSource).toContain("DENSE_LABEL_LIMIT");
    expect(graphCanvasSource).toContain("SEARCH_LABEL_LIMIT");
    expect(graphCanvasSource).toContain("STELLAR_NODE_TYPES");
    expect(graphCanvasSource).toContain("SATELLITE_NODE_TYPES");
    expect(graphCanvasSource).toContain("createStellarBody");
    expect(graphCanvasSource).toContain("createPlanetBody");
    expect(graphCanvasSource).toContain("createSatelliteBody");
    expect(graphCanvasSource).toContain("planetSurfaceGeometry");
    expect(graphCanvasSource).toContain("starFacetGeometry");
    expect(graphCanvasSource).toContain("satelliteFacetGeometry");
    expect(graphCanvasSource).toContain("wireframe: true");
    expect(graphCanvasSource).toContain("flatShading: true");
    expect(graphCanvasSource).toContain("pickVisibleLabelIds");
    expect(graphCanvasSource).toContain("nodeColor");
    expect(graphCanvasSource).toContain("nodeSize");
    expect(graphCanvasSource).toContain("graphNodeBadgeQuestion");
    expect(graphCanvasSource).toContain("node.responsibilityQuestion");
    expect(graphCanvasSource).toContain("dataset.agentCategory");
    expect(graphCanvasSource).toContain("setPixelRatio(1)");
    expect(graphCanvasSource).toContain("renderInteractionFrame");
    expect(graphCanvasSource).toContain("requestRender");
    expect(graphCanvasSource).toContain("new THREE.SphereGeometry(0.3, 12, 10)");
    expect(graphCanvasSource).toContain("new THREE.IcosahedronGeometry(0.42, 1)");
    expect(graphCanvasSource).toContain("new THREE.DodecahedronGeometry(0.28, 0)");
    expect(graphCanvasSource).not.toContain("createGlowTexture");
    expect(graphCanvasSource).not.toContain("AdditiveBlending");
    expect(graphCanvasSource).not.toContain("TorusGeometry");
    expect(graphCanvasSource).toContain("translate(-50%, calc(-100% - 20px))");
    expect(graphCanvasSource).toContain("trimText(node.summary");
    expect(graphCanvasSource).toContain("hitObjects");
    expect(graphCanvasSource).toContain('import("three")');
    expect(graphCanvasSource).not.toContain('import * as THREE from "three"');
    expect(graphWorkerSource).toContain("layerSpread");
    expect(graphWorkerSource).toContain("runtime_scene: 34");
    expect(styles.graphCanvasShell).toContain("min-h-[360px]");
    expect(styles.graphCanvasShell).toContain("bg-[var(--vui-gradient-route-soft)]");
    expect(styles.graphCanvasShell).toContain("after:content-['']");
    expect(styles.graphCanvasShell).toContain("after:[background-size:91px_91px]");
    expect(styles.graphWorkspace).toContain("grid-cols-[minmax(210px,250px)_minmax(760px,1fr)_minmax(260px,0.34fr)]");
    expect(styles.graphNodeBadge).toBeTypeOf("string");
    expect(memoryCssSource).not.toContain("backdrop-filter");
    expect(styles.graphNodeBadge).toContain("data-[detail=true]:z-10");
    expect(memoryCssSource).toContain(".graphNodeBadgeType");
    expect(memoryCssSource).toContain(".graphNodeBadgeQuestion");
    expect(memoryCssSource).toContain(".graphResponsibilityPanel");
    expect(memoryCssSource).toContain(".graphKnowledgePanel");
    expect(styles.graphKnowledgeItem).toBeTypeOf("string");
    expect(memoryCssSource).toContain(".graphKnowledgeContent");
    expect(memoryCssSource).toContain(".graphInteractionHint");
    expect(memoryCssSource).toContain(".graphNodeTypeMark");
    expect(styles.graphTypeList).toContain("[&_button]:w-full");
    expect(styles.graphTypeList).toContain("[&_[data-active=true]]:border-[var(--accent-cool)]");
    expect(memoryCssSource).toContain(".graphClearFocusButton");
    expect(memoryCssSource).toContain(".graphRelationPanel");
    expect(styles.graphRelationGroup).toContain("[&_button]:w-full");
    expect(memoryCssSource).toContain(".graphRelationEmpty");
    expect(styles.graphNodeBadge).toContain("data-[agent-category=session_agent]");
    expect(styles.graphNodeBadge).toContain("data-[agent-category=team_member_agent]");
    expect(memoryCssSource).toContain(".ragPreviewPanel");
    expect(memoryCssSource).toContain(".ragHealthStrip");
    expect(knowledgeRagPanelSource).toContain("data-stale={Number(providerHealth?.staleItemCount ?? 0) > 0");
    expect(memoryCssSource).toContain(".ragPolicyStrip");
    expect(memoryCssSource).toContain(".ragContextCard");
    expect(styles.graphKnowledgeItem).toContain("line-clamp-3");
    expect(styles.graphNodeBadge).toContain("data-[node-type=knowledge_base]");
    expect(routerSource).toContain('path: "memory/graph"');
    expect(routerSource).toContain('<MemoryRoute forcedView="graph" />');
    expect(routerSource).toContain('path: "agents/memory/graph"');
    expect(routerSource).toContain('<LegacyMemoryRedirect to="/memory/graph" />');
  });

  it("wires the hard-delete memory cleanup console behind preview and confirmation APIs", () => {
    expect(routeSource).toContain("MemoryCleanupTargetRequest");
    expect(routeSource).toContain("MemoryCleanupPreviewResponse");
    expect(routeSource).toContain('fetchJson<MemoryCleanupPreviewResponse>("/api/memory/cleanup/preview"');
    expect(routeSource).toContain('fetchJson<MemoryCleanupExecuteResponse>("/api/memory/cleanup/execute"');
    expect(routeSource).toContain("confirmationPhrase");
    expect(routeSource).toContain("cleanupConfirmationText.trim()");
    expect(cleanupPanelSource).toContain("copy.cleanupHardDelete");
    expect(cleanupPanelSource).toContain("copy.cleanupNoBackup");
    expect(cleanupPanelSource).toContain("copy.cleanupCentralSourceBoundary");
    expect(routeSource).toContain("targetType: \"global_runtime_memory\"");
    expect(routeSource).toContain("targetType: \"sqlite_database_compact\"");
    expect(routeSource).toContain("targetType: \"evaluation_artifacts\"");
    expect(routeSource).toContain("targetType: \"session_artifacts\"");
    expect(routeSource).toContain("targetType: \"legacy_log_info\"");
    expect(routeSource).toContain("targetType: \"runtime_scene_logs\"");
    expect(routeSource).toContain("targetType: \"team_archive_artifacts\"");
    expect(routeSource).toContain("targetType: \"agent_private_memory\"");
    expect(routeSource).toContain("targetType: \"agent_formal_knowledge\"");
    expect(routeSource).toContain("targetType: \"agent_memory_policy\"");
    expect(routeSource).toContain("targetType: \"team_knowledge\"");
    expect(routeSource).toContain("targetType: \"knowledge_base\"");
    expect(routeSource).toContain("queryKeys.memoryCleanupPreview()");
    expect(routeSource).toContain('from "./MemoryCleanupPanel"');
    expect(routeSource).toContain("<MemoryCleanupPanel");
    expect(routeSource).not.toContain("const renderCleanupView = () =>");
    expect(cleanupPanelSource).toContain("export function MemoryCleanupPanel");
    expect(cleanupPanelSource).toContain("styles.cleanupWorkspace");
    expect(cleanupPanelSource).toContain("styles.cleanupTargetPanel");
    expect(cleanupPanelSource).toContain("styles.cleanupPreviewPanel");
    expect(cleanupPanelSource).toContain("styles.cleanupExecutePanel");
    expect(cleanupPanelSource).toContain("styles.cleanupExecuteButton");
    expect(cleanupPanelSource).not.toContain("useQuery");
    expect(cleanupPanelSource).not.toContain("useMutation");
    expect(cleanupPanelSource).not.toContain("fetchJson");
    expect(memoryCssSource).toContain(".cleanupWorkspace");
    expect(memoryCssSource).toContain(".cleanupTargetPanel");
    expect(memoryCssSource).toContain(".cleanupPreviewPanel");
    expect(memoryCssSource).toContain(".cleanupExecutePanel");
    expect(memoryCssSource).toContain(".cleanupExecuteButton");
    expect(styles.cleanupPathList).toContain("[&_span]:truncate");
    expect(routerSource).toContain('path: "memory/cleanup"');
    expect(routerSource).toContain('<MemoryRoute forcedView="cleanup" />');
    expect(routerSource).toContain('path: "agents/memory/cleanup"');
    expect(routerSource).toContain('<LegacyMemoryRedirect to="/memory/cleanup" />');
  });

  it("wires the team knowledge platform to a dashboard snapshot plus scoped action APIs", () => {
    expect(routeSource).toContain("queryKeys.memoryUsageContract()");
    expect(routeSource).toContain('fetchJson<MemoryUsageContractPayload>("/api/memory/usage-contract")');
    expect(routeSource).toContain("queryKeys.knowledgeDashboardSnapshot(fallbackKnowledgeActorAgentId)");
    expect(routeSource).toContain("appendAgentParam(new URLSearchParams({");
    expect(routeSource).toContain('recommendationLimit: "6"');
    expect(routeSource).toContain("fetchJson<KnowledgeDashboardSnapshotPayload>(`/api/knowledge/dashboard-snapshot?${params.toString()}`)");
    expect(routeSource).toContain('sourceType: "manual_user_entry"');
    expect(routeSource).not.toContain("/source-artifacts");
    expect(routeSource).toContain("KnowledgeSourceInboxPayload");
    expect(routeSource).toContain("KnowledgeCentralSourceRegistryPayload");
    expect(routeSource).toContain("KnowledgeSourceInboxReviewResponse");
    expect(routeSource).toContain("queryKeys.knowledgeSourceInbox(");
    expect(routeSource).toContain("queryKeys.knowledgeCentralSources(");
    expect(routeSource).toContain("/api/knowledge/sources/inbox");
    expect(routeSource).toContain("/api/knowledge/sources/registry");
    expect(routeSource).toContain("/central-source-artifacts");
    expect(routeSource).toContain("ownerSourceDraft");
    expect(routeSource).toContain("sourceOwnerType");
    expect(routeSource).toContain("sourceOwnerId");
    expect(routeSource).toContain("sourceInboxStatus");
    expect(routeSource).toContain("submitOwnerSource");
    expect(routeSource).toContain("reviewOwnerSource");
    expect(routeSource).toContain("attachCentralSource");
    expect(routeSource).toContain("copy.sourceGovernance");
    expect(routeSource).toContain("copy.ownerSourceInbox");
    expect(routeSource).toContain("copy.centralSourceRegistry");
    expect(routeSource).toContain("copy.originalContent");
    expect(routeSource).toContain("copy.attachCentralSource");
    expect(routeSource).toContain("styles.sourceGovernanceControls");
    expect(routeSource).toContain("styles.sourceGovernanceGrid");
    expect(routeSource).toContain("styles.sourceRecordList");
    expect(memoryCssSource).toContain(".sourceGovernanceControls");
    expect(memoryCssSource).toContain(".sourceGovernanceGrid");
    expect(memoryCssSource).toContain(".sourceRecord");
    expect(memoryCssSource).toContain(".sourceRecordMeta");
    expect(routeSource).toContain("/refinement-proposals");
    expect(routeSource).not.toContain("/ingestion-packages");
    expect(routeSource).toContain("/review");
    expect(routeSource).toContain("/api/knowledge/search");
    expect(routeSource).toContain("queryKeys.knowledgeSearch(");
    expect(routeSource).toContain("queryKeys.knowledgeItems(activeKnowledgeBaseForItems, activeKnowledgeActorAgentId)");
    expect(routeSource).toContain("queryKeys.knowledgeRagHealth(activeKnowledgeActorAgentId)");
    expect(routeSource).toContain("/api/knowledge/rag/health?");
    expect(routeSource).toContain("fetchJson<KnowledgeRagHealthPayload>");
    expect(routeSource).toContain("queryKeys.knowledgeRagRetrieve");
    expect(routeSource).toContain("/api/knowledge/rag/retrieve");
    expect(routeSource).toContain('params.set("agentId", activeKnowledgeActorAgentId)');
    expect(routeSource).toContain("actorAgentIdForKnowledgeContext(activeKnowledgeBase, knowledgeActorAgents, fallbackKnowledgeActorAgentId)");
    expect(routeSource).toContain("fetchJson<KnowledgeRagRetrievalPayload>");
    expect(routeSource).toContain('from "./MemoryKnowledgeRagPanel"');
    expect(routeSource).toContain("<MemoryKnowledgeRagPanel");
    expect(knowledgeRagPanelSource).toContain("export function MemoryKnowledgeRagPanel");
    expect(knowledgeRagPanelSource).toContain("copy.ragRetrieval");
    expect(knowledgeRagPanelSource).toContain("copy.ragContextCandidates");
    expect(knowledgeRagPanelSource).toContain("copy.ragProvider");
    expect(knowledgeRagPanelSource).toContain("copy.ragVector");
    expect(knowledgeRagPanelSource).toContain("copy.ragIndexed");
    expect(knowledgeRagPanelSource).toContain("copy.ragStale");
    expect(knowledgeRagPanelSource).toContain("copy.ragNoPromptInjection");
    expect(knowledgeRagPanelSource).toContain("copy.ragCitations");
    expect(knowledgeRagPanelSource).toContain("styles.ragPreviewPanel");
    expect(knowledgeRagPanelSource).toContain("styles.ragHealthStrip");
    expect(knowledgeRagPanelSource).toContain("styles.ragPolicyStrip");
    expect(knowledgeRagPanelSource).toContain("styles.ragContextCard");
    expect(knowledgeRagPanelSource).not.toContain("useQuery");
    expect(knowledgeRagPanelSource).not.toContain("useMutation");
    expect(knowledgeRagPanelSource).not.toContain("fetchJson");
    expect(routeSource).toContain("/api/knowledge/governance/tasks");
    expect(routeSource).toContain("knowledge/governance/tasks?agentId=");
    expect(routeSource).toContain("knowledgeDashboardSnapshot?.operationsHealth");
    expect(routeSource).toContain("knowledgeDashboardSnapshot?.governancePlan");
    expect(routeSource).toContain("knowledgeDashboardSnapshot?.steward");
    expect(routeSource).toContain("knowledgeDashboardSnapshot?.recommendations");
    expect(routeSource).toContain("knowledgeDashboardSnapshot?.workbench");
    expect(routeSource).toContain("/api/knowledge/ingestion-adapters");
    expect(routeSource).toContain("/trace/");
    expect(routeSource).toContain("queryKeys.knowledgeTrace(activeKnowledgeBaseForItems, activeKnowledgeActorAgentId, traceTargetId)");
    expect(routeSource).toContain("/rating-suggestions");
    expect(routeSource).toContain("queryKeys.knowledgeRatingSuggestions(");
    expect(routeSource).toContain("/rating-suggestions/review-batch");
    expect(routeSource).toContain("/api/knowledge/permissions/audit?agentId=");
    expect(routeSource).toContain("copy.approveProposal");
    expect(routeSource).toContain("copy.rejectProposal");
    expect(routeSource).toContain("copy.submitRatingSuggestion");
    expect(routeSource).toContain("copy.bulkApplySuggestions");
    expect(routeSource).toContain("copy.bulkRejectSuggestions");
    expect(routeSource).toContain("selectedRatingSuggestionIds");
    expect(routeSource).toContain("toggleVisibleRatingSuggestions");
    expect(routeSource).toContain("copy.permissionAudit");
    expect(routeSource).not.toContain("copy.ingestionPackage");
    expect(routeSource).not.toContain("copy.submitIngestionPackage");
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
    expect(routeSource).toContain('from "./MemoryKnowledgeStewardPanel"');
    expect(routeSource).toContain("<MemoryKnowledgeStewardPanel");
    expect(knowledgeStewardPanelSource).toContain("export function MemoryKnowledgeStewardPanel");
    expect(knowledgeStewardPanelSource).toContain("copy.knowledgeSteward");
    expect(routeSource).toContain("knowledgeDashboardSnapshotQuery");
    expect(knowledgeStewardPanelSource).toContain("styles.knowledgeStewardPanel");
    expect(knowledgeStewardPanelSource).toContain("styles.stewardRecommendations");
    expect(knowledgeStewardPanelSource).toContain("styles.stewardWorkbench");
    expect(knowledgeStewardPanelSource).toContain("styles.stewardStageGrid");
    expect(knowledgeStewardPanelSource).not.toContain("useQuery");
    expect(knowledgeStewardPanelSource).not.toContain("useMutation");
    expect(knowledgeStewardPanelSource).not.toContain("fetchJson");
    expect(routeSource).toContain("knowledgeDashboardSnapshot?.workbench");
    expect(routeSource).toContain("knowledgeDashboardSnapshot?.recommendations");
    expect(routeSource).toContain("knowledgeDashboardSnapshot?.operationsHealth");
    expect(routeSource).toContain("knowledgeDashboardSnapshot?.governancePlan");
    expect(routeSource).toContain("memoryUsageContractQuery");
    expect(knowledgeStewardPanelSource).toContain("copy.noDirectApply");
    expect(knowledgeStewardPanelSource).toContain("copy.reviewerRequired");
    expect(knowledgeStewardPanelSource).toContain("copy.recommendationsOnly");
    expect(knowledgeStewardPanelSource).toContain("copy.acceptanceChecklist");
  });

  it("shows a priority review queue on the default memory overview", () => {
    expect(routeSource).toContain("priorityReviewPairs");
    expect(routeSource).toContain("memoryPairPriority");
    expect(routeSource).toContain("reviewReasonLabels(copy, item)");
    expect(routeSource).toContain("memoryPairActionTarget(pair)");
    expect(routeSource).toContain('import { MemoryReviewQueuePanel } from "./MemoryReviewQueuePanel"');
    expect(routeSource).toContain("<MemoryReviewQueuePanel");
    expect(routeSource).not.toContain("const renderReviewQueue = () => {");
    expect(reviewQueuePanelSource).toContain("export function MemoryReviewQueuePanel");
    expect(reviewQueuePanelSource).toContain("className={styles.reviewQueueList}");
    expect(overviewPanelSource).toContain("styles.reviewQueuePanel");
    expect(reviewQueuePanelSource).toContain("styles.reviewQueueTitleLine");
    expect(reviewQueuePanelSource).toContain("styles.reviewQueueSummary");
    expect(reviewQueuePanelSource).toContain("styles.reviewQueueTime");
    expect(reviewQueuePanelSource).toContain("styles.reviewReasonPill");
    expect(reviewQueuePanelSource).not.toContain("useQuery");
    expect(reviewQueuePanelSource).not.toContain("useMutation");
    expect(reviewQueuePanelSource).not.toContain("fetchJson");
    expect(overviewPanelSource).toContain("copy.reviewQueue");
    expect(overviewPanelSource).toContain("copy.reviewQueueHint");
    expect(reviewQueuePanelSource).toContain("copy.auditMemory");
    expect(reviewQueuePanelSource).toContain("copy.manageMemoryAction");
    expect(routeSource).toContain("reasonDisabled");
    expect(routeSource).toContain("reasonOverridden");
    expect(routeSource).toContain("reasonMissing");
    expect(routeSource).toContain("reasonTruncated");
    expect(routeSource).toContain("reasonInPrompt");
    expect(routeSource).toContain("reasonAgentVisible");
    expect(routeSource).toContain("reasonUserManaged");
    expect(overviewPanelSource).toContain('title={copy.reviewQueueHint}');
    expect(routeSource).not.toContain("<p className={styles.panelLead}>{copy.reviewQueueHint}</p>");
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
    expect(routeSource).toContain('from "./MemoryManagePanel"');
    expect(routeSource).toContain("<MemoryManagePanel");
    expect(routeSource).not.toContain("const renderManageView = () => (");
    expect(managePanelSource.indexOf("styles.manageListPanel")).toBeLessThan(managePanelSource.indexOf("styles.manageFormPanel"));
    expect(managePanelSource).toContain("copy.manageConfigPanel");
    expect(managePanelSource).toContain("copy.manageListHint");
    expect(managePanelSource).toContain("title={copy.manageListHint}");
    expect(routeSource).not.toContain("<p>{copy.manageConfigHint}</p>");
    expect(routeSource).toContain("type ManageFilterMode");
    expect(routeSource).toContain('next.set("manage", activeManageFilter)');
    expect(routeSource).toContain("normalizeManageFilterMode");
    expect(routeSource).toContain("itemMatchesManageFilter");
    expect(managePanelSource).toContain("copy.manageFilters");
    expect(managePanelSource).toContain("copy.sourceFilters");
    expect(managePanelSource).toContain("styles.manageFilterPanel");
    expect(managePanelSource).toContain("styles.manageSourceFilters");
    expect(managePanelSource).toContain("styles.sourceChip");
    expect(managePanelSource).toContain("styles.bulkActionBar");
    expect(managePanelSource).not.toContain("useQuery");
    expect(managePanelSource).not.toContain("useMutation");
    expect(managePanelSource).not.toContain("fetchJson");
    expect(routeSource).toContain('from "./MemorySelectedConfigPanel"');
    expect(routeSource).toContain("<MemorySelectedConfigPanel");
    expect(routeSource).not.toContain("const renderSelectedMemoryConfig = () =>");
    expect(selectedConfigPanelSource).toContain("export function MemorySelectedConfigPanel");
    expect(selectedConfigPanelSource).toContain("styles.selectedConfigSummary");
    expect(selectedConfigPanelSource).toContain("onEdit");
    expect(selectedConfigPanelSource).toContain("onRestore");
    expect(selectedConfigPanelSource).toContain("onDisableOrDelete");
    expect(selectedConfigPanelSource).not.toContain("useQuery");
    expect(selectedConfigPanelSource).not.toContain("useMutation");
    expect(selectedConfigPanelSource).not.toContain("fetchJson");
    expect(routeSource).toContain('from "./MemoryManagementEditor"');
    expect(routeSource).toContain("MemoryManagementEditorDraft");
    expect(routeSource).toContain("<MemoryManagementEditor");
    expect(routeSource).not.toContain("const renderManagementEditor = () =>");
    expect(managementEditorSource).toContain("export function MemoryManagementEditor");
    expect(managementEditorSource).toContain("export type MemoryManagementEditorDraft");
    expect(managementEditorSource).toContain("styles.editPreviewPanel");
    expect(managementEditorSource).toContain("styles.editPreviewGrid");
    expect(managementEditorSource).toContain("onDraftChange");
    expect(managementEditorSource).toContain("onSave");
    expect(managementEditorSource).not.toContain("useQuery");
    expect(managementEditorSource).not.toContain("useMutation");
    expect(managementEditorSource).not.toContain("fetchJson");
    expect(routeSource.indexOf("selectedConfig={createSelectedMemoryConfig()}")).toBeGreaterThan(
      routeSource.indexOf("managementEditor={createManagementEditor()}"),
    );
    expect(managePanelSource).toContain("copy.selectedCount");
    expect(managePanelSource).toContain("copy.bulkDisable");
    expect(managePanelSource).toContain("copy.bulkRestore");
    expect(managementEditorSource).toContain("styles.editPreviewPanel");
    expect(managementEditorSource).toContain("styles.editPreviewGrid");
    expect(styles.itemButtonDense).toContain("min-h-[62px]");
    expect(styles.itemContentButtonDense).toContain("grid-rows-[16px_14px_18px]");
    expect(styles.manageItemBadges).toContain("[&>span]:truncate");
    expect(styles.manageItemBadges).toContain("grid-cols-[repeat(auto-fit,minmax(82px,1fr))]");
    expect(styles.manageItemBadges).toContain("max-h-[74px]");
  });

  it("keeps explanatory Memory platform copy out of persistent paragraphs", () => {
    expect(routeSource).toContain("meta={memoryViewSubtitle(copy, forcedView)}");
    expect(projectMemoryQueuePanelSource).toContain('title={copy.projectMemoryQueueHint}');
    expect(overviewPanelSource).toContain('title={copy.reviewQueueHint}');
    expect(routeSource).toContain('title={copy.knowledgeSubtitle}');
    expect(routeSource).toContain('title={copy.knowledgeHint}');
    expect(knowledgeRagPanelSource).toContain('title={copy.ragRetrievalHint}');
    expect(cleanupPanelSource).toContain('title={copy.cleanupNoBackup}');
    expect(cleanupPanelSource).toContain('title={copy.cleanupCentralSourceBoundary}');
    expect(routeSource).toContain('title={copy.graphInteractionHint}');

    expect(routeSource).not.toContain("className={styles.subtitle}>{memoryViewSubtitle");
    expect(routeSource).not.toContain("<p className={styles.panelLead}>{copy.projectMemoryQueueHint}</p>");
    expect(routeSource).not.toContain("<p className={styles.panelLead}>{copy.knowledgeHint}</p>");
    expect(routeSource).not.toContain("<p>{copy.managementHint}</p>");
    expect(routeSource).not.toContain("<p>{copy.ragRetrievalHint}</p>");
    expect(routeSource).not.toContain("<span>{copy.cleanupNoBackup}</span>");
    expect(styles.panelLead).toContain("hidden");
    expect(styles.manageFormPanel).toContain("[&>p]:hidden");
  });

  it("surfaces agent visibility, prompt injection, and raw content in the detail pane", () => {
    expect(routeSource).toContain('from "./MemoryDetailPanel"');
    expect(routeSource).toContain("<MemoryDetailPanel");
    expect(routeSource).not.toContain("const renderDetailPanel = (showEditor = true) =>");
    expect(detailPanelSource).toContain("export function MemoryDetailPanel");
    expect(detailPanelSource).toContain("item.agentVisible");
    expect(detailPanelSource).toContain("item.inPrompt");
    expect(detailPanelSource).toContain("<details className={styles.rawPanel} open={showEditor}>");
    expect(detailPanelSource).toContain("item.content");
    expect(detailPanelSource).toContain("copySourceSummary");
    expect(detailPanelSource).toContain("copySourcePath");
    expect(detailPanelSource).toContain("copyRawContentAction");
    expect(detailPanelSource).toContain("copyCurrentLink");
    expect(detailPanelSource).not.toContain("useQuery");
    expect(detailPanelSource).not.toContain("useMutation");
    expect(detailPanelSource).not.toContain("fetchJson");
    expect(routeSource).toContain("copy.management");
    expect(routeSource).toContain("styles.managementPanel");
  });

  it("adds perception matrix and quick filters before the source drilldown", () => {
    expect(routeSource).toContain('import { MemoryMatrixPanel } from "./MemoryMatrixPanel"');
    expect(routeSource).toContain("<MemoryMatrixPanel");
    expect(routeSource).not.toContain("const renderMatrixPanel = (title = copy.whereMemoryWorks) => (");
    expect(matrixPanelSource).toContain("export function MemoryMatrixPanel");
    expect(matrixPanelSource).toContain("styles.matrixPanel");
    expect(matrixPanelSource).toContain("copy.perceptionMatrix");
    expect(matrixPanelSource).not.toContain("useQuery");
    expect(matrixPanelSource).not.toContain("useMutation");
    expect(matrixPanelSource).not.toContain("fetchJson");
    expect(sourceAndItemPanelsSource).toContain("styles.filterGroup");
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
    expect(matrixPanelSource).toContain("styles.matrixCardButton");
    expect(matrixPanelSource).toContain("styles.matrixCardActive");
    expect(matrixPanelSource).toContain("aria-pressed={activeChannel === card.channel}");
    expect(matrixPanelSource).toContain("onClick={() => onSelectChannel(card.channel)}");
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
    const impactIndex = detailPanelSource.indexOf("styles.impactPanel");
    const rawPanelIndex = detailPanelSource.indexOf("styles.rawPanel");

    expect(impactIndex).toBeGreaterThan(0);
    expect(rawPanelIndex).toBeGreaterThan(impactIndex);
    expect(routeSource).toContain("impactCopy(copy, resolvedActiveItem)");
  });

  it("makes source origin and inspection actions directly visible in the UI", () => {
    expect(routeSource).toContain("sourceOriginLabel(section, item)");
    expect(routeSource).toContain("styles.itemOrigin");
    expect(detailPanelSource).toContain("styles.detailActions");
    expect(detailPanelSource).toContain("styles.detailActionButton");
    expect(detailPanelSource).toContain("styles.copyNotice");
    expect(detailPanelSource).toContain("section.sourceApi");
    expect(routeSource).toContain("handleCopySourcePath");
    expect(routeSource).toContain("resolvedActiveItem.path || resolvedActiveItem.source || activeSection.sourcePath");
  });

  it("keeps inspection actions compact enough for narrow detail panes", () => {
    expect(detailPanelSource).toContain("styles.detailActions");
    expect(detailPanelSource).toContain("styles.detailActionButton");
    expect(detailPanelSource).toContain("copySourceSummary");
    expect(detailPanelSource).toContain("copySourcePath");
    expect(detailPanelSource).toContain("copyRawContentAction");
    expect(detailPanelSource).toContain("copyCurrentLink");
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
    expect(routerSource).toContain('path: "memory/agents"');
    expect(routerSource).toContain('<MemoryRoute forcedView="agents" />');
    expect(routerSource).toContain('path: "memory/manage"');
    expect(routerSource).toContain('<MemoryRoute forcedView="manage" />');
    expect(routerSource).toContain('path: "memory/sources"');
    expect(routerSource).toContain('<MemoryRoute forcedView="sources" />');
    expect(routerSource).toContain('path: "memory/knowledge"');
    expect(routerSource).toContain('<MemoryRoute forcedView="knowledge" />');
    expect(routerSource).toContain('path: "memory/cleanup"');
    expect(routerSource).toContain('<MemoryRoute forcedView="cleanup" />');
    expect(routerSource).toContain('path: "agents/memory"');
    expect(routerSource).toContain('<LegacyMemoryRedirect to="/memory" />');
    expect(routerSource).toContain('path: "agents/memory/effective"');
    expect(routerSource).toContain('<LegacyMemoryRedirect to="/memory/effective" />');
    expect(routerSource).toContain('path: "agents/memory/agents"');
    expect(routerSource).toContain('<LegacyMemoryRedirect to="/memory/agents" />');
    expect(routerSource).toContain('path: "agents/memory/manage"');
    expect(routerSource).toContain('<LegacyMemoryRedirect to="/memory/manage" />');
    expect(routerSource).toContain('path: "agents/memory/sources"');
    expect(routerSource).toContain('<LegacyMemoryRedirect to="/memory/sources" />');
    expect(routerSource).toContain('path: "agents/memory/knowledge"');
    expect(routerSource).toContain('<LegacyMemoryRedirect to="/memory/knowledge" />');
    expect(routerSource).toContain('path: "agents/memory/cleanup"');
    expect(routerSource).toContain('<LegacyMemoryRedirect to="/memory/cleanup" />');
    expect(routeSource).toContain('{ key: "overview", href: "/memory" }');
    expect(routeSource).toContain("auditHref: `/memory/sources?section=");
    expect(routeSource).toContain("manageHref: memoryPairActionTarget(pair) === \"manage\" ? `/memory/manage?section=");
    expect(reviewQueuePanelSource).toContain("to={item.auditHref}");
    expect(reviewQueuePanelSource).toContain("to={item.manageHref}");
    expect(routeSource).not.toContain("AgentManagementNav");
    expect(routeSource.indexOf("{renderSubnav()}")).toBeLessThan(routeSource.indexOf("className={viewStackClassName}"));
    expect(appShellSource).toContain('to="/memory"');
    expect(appShellSource).toContain('t("navMemory")');
  });

  it("keeps effective memory panels scrollable instead of clipping dense narrow content", () => {
    expect(routeSource).toContain('from "./MemoryEffectivePanel"');
    expect(routeSource).toContain("<MemoryEffectivePanel");
    expect(routeSource).not.toContain("const renderEffectiveView = () => (");
    expect(effectivePanelSource).toContain("export function MemoryEffectivePanel");
    expect(effectivePanelSource).toContain("styles.effectiveGrid");
    expect(effectivePanelSource).toContain("styles.overviewPanel");
    expect(effectivePanelSource).not.toContain("useQuery");
    expect(effectivePanelSource).not.toContain("useMutation");
    expect(effectivePanelSource).not.toContain("fetchJson");
    expect(styles.effectiveGrid).toContain("[&_.overviewPanel]:max-h-[min(260px,36vh)]");
    expect(styles.effectiveGrid).toContain("[&_.overviewPanel]:overflow-auto");
    expect(styles.effectiveGrid).toContain("[&_.panelLead]:line-clamp-2");
    expect(styles.compactMemoryList).toContain("max-h-[148px]");
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

  it("keeps team knowledge governance compact and hides internal policy tokens behind readable labels", () => {
    expect(routeSource).toContain("function policyTokenLabel");
    expect(routeSource).toContain("function memoryDomainDisplayLabel");
    expect(routeSource).toContain("function memoryDomainOwnerLabel");
    expect(routeSource).toContain("function memoryBoundaryLabel");
    expect(knowledgeStewardPanelSource).toContain("function stewardStageDisplayTitle");
    expect(routeSource).toContain("policyTokenLabel(domain.promptDefault, lang)");
    expect(routeSource).toContain("(memoryUsageContract?.domains ?? []).slice(0, 4).map");
    expect(routeSource).toContain("memoryDomainDisplayLabel(domain.label, domain.domainId, lang)");
    expect(routeSource).toContain("memoryDomainOwnerLabel(domain.owner, lang)");
    expect(routeSource).toContain("memoryBoundaryLabel(domain.boundary, lang)");
    expect(knowledgeStewardPanelSource).toContain("formatPolicyToken(knowledgeSteward?.steward.permissionBoundary");
    expect(knowledgeStewardPanelSource).toContain("compactInlineList(knowledgeSteward?.steward.toolPolicy.preferredTools, 3)");
    expect(knowledgeStewardPanelSource).toContain("compactInlineList(knowledgeSteward?.steward.toolPolicy.allowedTools, 2)");
    expect(knowledgeStewardPanelSource).toContain('preferredCount} {lang === "zh" ? "项" : "items"}');
    expect(knowledgeStewardPanelSource).toContain("recommendations.length ? (");
    expect(knowledgeStewardPanelSource).toContain("stewardStageDisplayTitle(stage.stageId, stage.title, lang)");
    expect(routeSource).toContain("visibleTools.length");
    expect(routeSource).toContain("hiddenTools.length");
    expect(routeSource).toContain("const viewStackClassName =");
    expect(routeSource).toContain("styles.knowledgeViewStack");
    expect(routeSource).toContain("className={styles.knowledgeGovernanceDeck}");
    expect(routeSource).toContain('type KnowledgeWorkspaceMode = "sources" | "search" | "review" | "governance" | "permissions"');
    expect(routeSource).toContain("styles.knowledgeModeTabs");
    expect(routeSource).toContain('activeKnowledgeWorkspaceMode === "sources"');
    expect(routeSource).toContain('activeKnowledgeWorkspaceMode === "search"');
    expect(routeSource).toContain('activeKnowledgeWorkspaceMode === "review"');
    expect(routeSource).toContain('activeKnowledgeWorkspaceMode === "governance"');
    expect(routeSource).toContain('activeKnowledgeWorkspaceMode === "permissions"');
    expect(routeSource).toContain("showOwnerSourceForm ? (");
    expect(routeSource).toContain("styles.collapsedFormButton");
    expect(routeSource).toContain("copy.selectedKnowledgeDetail");

    expect(styles.knowledgeGovernanceDeck).toContain("hidden");
    expect(styles.knowledgeViewStack).toContain("flex");
    expect(styles.knowledgeViewStack).toContain("[&>.summaryGrid]:[grid-template-columns:repeat(4,minmax(0,1fr))]");
    expect(styles.knowledgeViewStack).toContain("[&>.knowledgeWorkspace]:flex-1");
    expect(styles.knowledgeViewStack).toContain("[&>.knowledgeGovernanceDeck]:hidden");
    expect(styles.knowledgeMain).toContain("[&_.managementPanel]:content-start");
    expect(styles.knowledgeModeTabs).toContain("grid-cols-[repeat(5,minmax(0,1fr))]");
    expect(styles.knowledgeModeTabActive).toBeTypeOf("string");
    expect(styles.knowledgeWorkspace).toContain("grid-cols-[minmax(170px,205px)_minmax(0,1.24fr)_minmax(260px,0.62fr)]");
    expect(styles.sourceGovernanceColumn).toContain("[&_.sourceGovernanceControls]:grid-cols-[minmax(240px,0.92fr)_minmax(250px,1.08fr)]");
    expect(styles.collapsedFormButton).toContain("max-h-[92px]");
    expect(styles.contractStateGrid).toContain("hidden");
    expect(styles.contractForbiddenList).toContain("hidden");
    expect(styles.stewardRecommendations).toContain("hidden");
    expect(styles.stewardWorkbench).toContain("hidden");
    expect(styles.stewardMission).toContain("[&_small]:hidden");
    expect(styles.stewardMetric).toContain("[&_small]:hidden");
    expect(styles.knowledgeGovernanceDeck).toContain("max-[900px]:grid-cols-[minmax(0,1fr)]");
  });

  it("honors Team workspace deep-link parameters for team knowledge and graph focus", () => {
    expect(routeSource).toContain('const requestedTeamId = (searchParams.get("teamId") ?? "").trim()');
    expect(routeSource).toContain('const requestedKnowledgeBaseId = (searchParams.get("knowledgeBaseId") ?? "").trim()');
    expect(routeSource).toContain('const requestedGraphNodeId = (searchParams.get("nodeId") ?? "").trim()');
    expect(routeSource).toContain("requestedTeamKnowledgeBase");
    expect(routeSource).toContain("setActiveKnowledgeBaseId(knowledgeBaseRequestId(requestedTeamKnowledgeBase))");
    expect(routeSource).toContain("useState(() => requestedGraphNodeId)");
    expect(routeSource).toContain('queryKeys.memoryKnowledgeGraph(fallbackKnowledgeActorAgentId, "officialResearchGraph", requestedTeamId)');
    expect(routeSource).toContain('new URLSearchParams({ include: "officialResearchGraph" })');
    expect(routeSource).toContain('params.set("teamId", requestedTeamId)');
  });

  it("routes Memory controls through VUI primitives", () => {
    expect(routeSource).toContain('from "../components/vui"');
    expect(routeSource).toContain("<VButton");
    expect(routeSource).toContain("<VNativeInput");
    expect(routeSource).toContain("<VNativeSelect");
    expect(routeSource).toContain("<VNativeTextarea");
    expect(routeSource).not.toMatch(/<button\b/);
    expect(routeSource).not.toMatch(/<input\b/);
    expect(routeSource).not.toMatch(/<select\b/);
    expect(routeSource).not.toMatch(/<textarea\b/);
  });
});
