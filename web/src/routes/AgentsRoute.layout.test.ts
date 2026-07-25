import { isValidElement, type ReactElement, type ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import {
  AgentListStatePanel,
  resolveAgentListPresentation,
} from "./AgentListStatePanel";
import {
  agentSummaryMetricValue,
  resolveAgentWorkspaceQueryState,
  resolveAgentWorkspaceSource,
} from "./AgentsRoute";

// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { readFileSync } from "node:fs";
import routeSource from "./AgentsRoute.tsx?raw";
import agentStatusPresentationSource from "./agents/agentStatusPresentation.ts?raw";
import agentManagementNavSource from "./AgentManagementNav.tsx?raw";
import agentManagementModuleBarSource from "./AgentManagementModuleBar.tsx?raw";
import agentWorkspaceCacheSource from "./agentWorkspaceCache.ts?raw";
import styles from "./AgentsRoute.styles";
import stylesSource from "./AgentsRoute.styles.ts?raw";
import archiveZoneStyles from "./AgentArchiveZonePanel.styles";
import avatarEditorStyles from "./AgentAvatarEditorPanel.styles";
import bulkConfigStyles from "./AgentBulkConfigPanel.styles";
import bulkOperationsStyles from "./AgentBulkOperationsPanel.styles";
import contextCompressionStyles from "./AgentContextCompressionPanel.styles";
import coreConfigStyles from "./AgentCoreConfigPanel.styles";
import createPanelStyles from "./AgentCreatePanel.styles";
import debugResetStyles from "./AgentDebugResetPanel.styles";
import detailHeaderStyles from "./AgentDetailHeaderPanel.styles";
import detailWorkspaceStyles from "./AgentDetailWorkspacePanel.styles";
import emptySelectionStyles from "./AgentEmptySelectionPanel.styles";
import activityHistoryStyles from "./AgentActivityHistoryPanel.styles";
import healthMaintenanceStyles from "./AgentHealthMaintenancePanel.styles";
import listWorkspaceStyles from "./AgentListWorkspacePanel.styles";
import managementNavStyles from "./AgentManagementNav.styles";
import managementModuleBarStyles from "./AgentManagementModuleBar.styles";
import managementBriefStyles from "./AgentManagementBriefPanel.styles";
import memoryPolicyStyles from "./AgentMemoryPolicyPanel.styles";
import modeMembershipStyles from "./AgentModeMembershipPanel.styles";
import personaProfileStyles from "./AgentPersonaProfilePanel.styles";
import referencesPanelStyles from "./AgentReferencesPanel.styles";
import overviewStyles from "./AgentOverviewPanel.styles";
import overviewOperationsStyles from "./AgentOverviewOperationsPanel.styles";
import overviewResourcesStyles from "./AgentOverviewResourcesPanel.styles";
import runtimeFocusStyles from "./AgentRuntimeFocusPanel.styles";
import runtimePolicyStyles from "./AgentRuntimePolicyPanel.styles";
import taskProfileStyles from "./AgentTaskProfilePanel.styles";
import toolGovernanceStyles from "./AgentToolGovernancePanel.styles";
import toolSummaryStyles from "./AgentToolSummaryPanel.styles";
import returnBannerStyles from "./AgentReturnBannerPanel.styles";
import selectedDetailContentStyles from "./AgentSelectedDetailContentPanel.styles";
import effectiveConfigurationStyles from "./AgentEffectiveConfigurationPanel.styles";
import workspaceLayoutStyles from "./AgentWorkspaceLayoutPanel.styles";
import agentCreateDialogStyles from "./agent-create/AgentCreateWizardDialog.styles";
import routerSource from "../app/router.tsx?raw";
import shellSource from "../app/AppShell.tsx?raw";

const bulkActionBarSource = readFileSync(
  new URL("../components/vui/product/agent-management/AgentBulkActionBar.tsx", import.meta.url),
  "utf-8",
);
const bulkConfigPanelSource = readFileSync(
  new URL("./AgentBulkConfigPanel.tsx", import.meta.url),
  "utf-8",
);
const bulkOperationsPanelSource = readFileSync(
  new URL("./AgentBulkOperationsPanel.tsx", import.meta.url),
  "utf-8",
);
const contextCompressionPanelSource = readFileSync(
  new URL("./AgentContextCompressionPanel.tsx", import.meta.url),
  "utf-8",
);
const coreConfigPanelSource = readFileSync(
  new URL("./AgentCoreConfigPanel.tsx", import.meta.url),
  "utf-8",
);
const modelPickerSource = readFileSync(
  new URL("./AgentModelPicker.tsx", import.meta.url),
  "utf-8",
);
const configPrimaryPanePanelSource = readFileSync(
  new URL("./AgentConfigPrimaryPanePanel.tsx", import.meta.url),
  "utf-8",
);
const configPolicyPanePanelSource = readFileSync(
  new URL("./AgentConfigPolicyPanePanel.tsx", import.meta.url),
  "utf-8",
);
const configReferencesPanePanelSource = readFileSync(
  new URL("./AgentConfigReferencesPanePanel.tsx", import.meta.url),
  "utf-8",
);
const createPanelSource = readFileSync(
  new URL("./AgentCreatePanel.tsx", import.meta.url),
  "utf-8",
);
const agentCreateDialogSource = readFileSync(
  new URL("./agent-create/AgentCreateWizardDialog.tsx", import.meta.url),
  "utf-8",
);
const agentCreateContractSource = readFileSync(
  new URL("./agent-create/agentCreateContract.ts", import.meta.url),
  "utf-8",
);
const archiveZonePanelSource = readFileSync(
  new URL("./AgentArchiveZonePanel.tsx", import.meta.url),
  "utf-8",
);
const debugResetPanelSource = readFileSync(
  new URL("./AgentDebugResetPanel.tsx", import.meta.url),
  "utf-8",
);
const healthMaintenancePanelSource = readFileSync(
  new URL("./AgentHealthMaintenancePanel.tsx", import.meta.url),
  "utf-8",
);
const modeMembershipPanelSource = readFileSync(
  new URL("./AgentModeMembershipPanel.tsx", import.meta.url),
  "utf-8",
);
const personaProfilePanelSource = readFileSync(
  new URL("./AgentPersonaProfilePanel.tsx", import.meta.url),
  "utf-8",
);
const taskProfilePanelSource = readFileSync(
  new URL("./AgentTaskProfilePanel.tsx", import.meta.url),
  "utf-8",
);
const toolGovernancePanelSource = readFileSync(
  new URL("./AgentToolGovernancePanel.tsx", import.meta.url),
  "utf-8",
);
const memoryPolicyPanelSource = readFileSync(
  new URL("./AgentMemoryPolicyPanel.tsx", import.meta.url),
  "utf-8",
);
const filterRailSource = readFileSync(
  new URL("../components/vui/product/agent-management/AgentFilterRail.tsx", import.meta.url),
  "utf-8",
);
const denseListSource = readFileSync(
  new URL("../components/vui/product/agent-management/AgentDenseList.tsx", import.meta.url),
  "utf-8",
);
const runtimeFocusPanelSource = readFileSync(
  new URL("./AgentRuntimeFocusPanel.tsx", import.meta.url),
  "utf-8",
);
const runtimePolicyPanelSource = readFileSync(
  new URL("./AgentRuntimePolicyPanel.tsx", import.meta.url),
  "utf-8",
);
const activityPanePanelSource = readFileSync(
  new URL("./AgentActivityPanePanel.tsx", import.meta.url),
  "utf-8",
);
const managementHeaderPanelSource = readFileSync(
  new URL("./AgentManagementHeaderPanel.tsx", import.meta.url),
  "utf-8",
);
const managementBriefPanelSource = readFileSync(
  new URL("./AgentManagementBriefPanel.tsx", import.meta.url),
  "utf-8",
);
const activityHistoryPanelSource = readFileSync(
  new URL("./AgentActivityHistoryPanel.tsx", import.meta.url),
  "utf-8",
);
const avatarEditorPanelSource = readFileSync(
  new URL("./AgentAvatarEditorPanel.tsx", import.meta.url),
  "utf-8",
);
const detailHeaderPanelSource = readFileSync(
  new URL("./AgentDetailHeaderPanel.tsx", import.meta.url),
  "utf-8",
);
const detailWorkspacePanelSource = readFileSync(
  new URL("./AgentDetailWorkspacePanel.tsx", import.meta.url),
  "utf-8",
);
const selectedDetailContentPanelSource = readFileSync(
  new URL("./AgentSelectedDetailContentPanel.tsx", import.meta.url),
  "utf-8",
);
const effectiveConfigurationPanelSource = readFileSync(
  new URL("./AgentEffectiveConfigurationPanel.tsx", import.meta.url),
  "utf-8",
);
const overviewPanelSource = readFileSync(
  new URL("./AgentOverviewPanel.tsx", import.meta.url),
  "utf-8",
);
const overviewOperationsPanelSource = readFileSync(
  new URL("./AgentOverviewOperationsPanel.tsx", import.meta.url),
  "utf-8",
);
const overviewResourcesPanelSource = readFileSync(
  new URL("./AgentOverviewResourcesPanel.tsx", import.meta.url),
  "utf-8",
);
const emptySelectionPanelSource = readFileSync(
  new URL("./AgentEmptySelectionPanel.tsx", import.meta.url),
  "utf-8",
);
const listStatePanelSource = readFileSync(
  new URL("./AgentListStatePanel.tsx", import.meta.url),
  "utf-8",
);
const listWorkspacePanelSource = readFileSync(
  new URL("./AgentListWorkspacePanel.tsx", import.meta.url),
  "utf-8",
);
const workspaceLayoutPanelSource = readFileSync(
  new URL("./AgentWorkspaceLayoutPanel.tsx", import.meta.url),
  "utf-8",
);
const returnBannerPanelSource = readFileSync(
  new URL("./AgentReturnBannerPanel.tsx", import.meta.url),
  "utf-8",
);
const referencesPanelSource = readFileSync(
  new URL("./AgentReferencesPanel.tsx", import.meta.url),
  "utf-8",
);
const toolSummaryPanelSource = readFileSync(
  new URL("./AgentToolSummaryPanel.tsx", import.meta.url),
  "utf-8",
);

function sourceBlocksForStyle(styleName: string, source = routeSource): string[] {
  const marker = `className={styles.${styleName}}`;
  const blocks: string[] = [];
  let offset = 0;

  while (offset < source.length) {
    const markerIndex = source.indexOf(marker, offset);
    if (markerIndex < 0) {
      break;
    }

    const blockStart = source.lastIndexOf("<div", markerIndex);
    const blockEnd = source.indexOf("</div>", markerIndex);

    expect(blockStart).toBeGreaterThanOrEqual(0);
    expect(blockEnd).toBeGreaterThan(markerIndex);

    blocks.push(source.slice(blockStart, blockEnd));
    offset = blockEnd + "</div>".length;
  }

  return blocks;
}

function expectBackgroundAwareSurface(styleName: keyof typeof styles): void {
  const className = styles[styleName];

  // Structural surfaces are now opaque VUI recipes (wallpaper no longer shows through).
  const usesOpaqueRecipe =
    className.includes("!bg-[var(--vui-surface-row)]")
    || className.includes("!bg-[var(--vui-surface-panel)]")
    || className.includes("!bg-vui-surface-row")
    || className.includes("!bg-vui-surface-panel")
    || className.includes("[background:var(--vui-surface-row)]")
    || className.includes("[background:var(--vui-surface-panel)]");
  if (usesOpaqueRecipe) {
    expect(
      className,
      `${String(styleName)} should use an opaque semantic surface after recipe migration`,
    ).toMatch(/vui-surface-(row|panel)/);
  } else {
    expect(className, `${String(styleName)} should keep a transparent, background-aware surface`).toMatch(/vui-surface-|color-mix\(in_srgb/);
  }
  expect(className, `${String(styleName)} should not restack an opaque surface-card wall`).not.toContain("var(--surface-card)");
  expect(className, `${String(styleName)} should not restack an opaque strong panel wall`).not.toContain("var(--surface-panel-strong)");
  expect(className, `${String(styleName)} should not own route-level elevation`).not.toContain("box-shadow:var(--shadow");
  expect(className, `${String(styleName)} should keep a hairline border`).toMatch(/border/);
}

function expectContentSizedAction(styleName: keyof typeof styles): void {
  const className = styles[styleName];
  const tokens = className.split(/\s+/);

  expect(tokens, `${String(styleName)} should keep short actions content-sized`).toContain("w-fit");
  expect(tokens, `${String(styleName)} should cap long labels inside the viewport`).toContain("max-w-full");
  expect(tokens, `${String(styleName)} should not force compact actions across the full row`).not.toContain("w-full");
  expect(tokens, `${String(styleName)} should not force compact actions across the full row`).not.toContain("[width:100%]");
}

function expectResponsiveActionRow(styleName: keyof typeof styles): void {
  const className = styles[styleName];

  expect(className, `${String(styleName)} should wrap dense action controls before overflowing`).toContain("[flex-wrap:wrap]");
  expect(className, `${String(styleName)} should allow action rows to shrink in narrow panels`).toContain("min-w-0");
  expect(className, `${String(styleName)} should keep VUI buttons inside the row`).toContain("[&_[data-vui=\"button\"]]:[max-width:100%]");
  expect(className, `${String(styleName)} should keep VUI buttons content-sized`).toContain("[&_[data-vui=\"button\"]]:w-fit");
}

function expectBackgroundAwareClass(className: string, label: string): void {
  const usesOpaqueRecipe =
    className.includes("!bg-[var(--vui-surface-row)]")
    || className.includes("!bg-[var(--vui-surface-panel)]")
    || className.includes("!bg-vui-surface-row")
    || className.includes("!bg-vui-surface-panel")
    || className.includes("var(--vui-surface-row)")
    || className.includes("var(--vui-surface-panel)")
    || className.includes("bg-vui-surface-row")
    || className.includes("bg-vui-surface-panel");
  if (usesOpaqueRecipe) {
    expect(className, `${label} should use an opaque semantic surface after recipe migration`).toMatch(
      /vui-surface-(row|panel)/,
    );
  } else {
    expect(className, `${label} should use a lightweight background-aware token`).toMatch(/vui-surface-|color-mix\(in_srgb/);
  }
  expect(className, `${label} should avoid restacking surface-card walls inside Agent detail`).not.toContain("var(--surface-card)");
  expect(className, `${label} should avoid strong opaque panel walls inside Agent detail`).not.toContain("var(--surface-panel-strong)");
  expect(className, `${label} should not own route-level elevation`).not.toContain("box-shadow:var(--shadow");
  expect(className, `${label} should keep a hairline border`).toMatch(/border/);
}

function expectOpaqueSemanticSurface(className: string, label: string, token: string): void {
  const accepted = [token];
  if (token.includes("surface-panel") || token.includes("vui-surface-panel")) {
    accepted.push("!bg-[var(--vui-surface-panel)]", "!bg-vui-surface-panel", "bg-vui-surface-panel");
  }
  if (token.includes("surface-row") || token.includes("vui-surface-row")) {
    accepted.push("!bg-[var(--vui-surface-row)]", "!bg-vui-surface-row", "bg-vui-surface-row");
  }
  if (token.includes("surface-workspace") || token.includes("vui-surface-workspace")) {
    accepted.push(
      "!bg-[var(--vui-surface-workspace)]",
      "!bg-vui-surface-workspace",
      "bg-vui-surface-workspace",
      "bg-[var(--vui-surface-workspace)]",
    );
  }
  if (token.includes("surface-rail") || token.includes("vui-surface-rail")) {
    accepted.push(
      "!bg-[var(--vui-surface-rail)]",
      "!bg-vui-surface-rail",
      "bg-vui-surface-rail",
      "bg-[var(--vui-surface-rail)]",
    );
  }
  expect(
    accepted.some((part) => className.includes(part)),
    `${label} should use its semantic VUI surface token (${token})`,
  ).toBe(true);
  expect(className, `${label} should not restore the legacy wallpaper-through background mix`).not.toContain(
    "color-mix(in_srgb,_var(--vui-surface",
  );
  expect(className, `${label} should not restack a legacy card wall`).not.toContain("var(--surface-card)");
  expect(className, `${label} should not own route-level elevation`).not.toContain("box-shadow:var(--shadow");
}

function expectContentSizedVuiButtons(className: string, label: string): void {
  const tokens = className.split(/\s+/);

  expect(className, `${label} should keep VUI buttons within narrow Agent detail panels`).toContain("[&_[data-vui=\"button\"]]:[max-width:100%]");
  expect(className, `${label} should keep VUI buttons content-sized by default`).toContain("[&_[data-vui=\"button\"]]:w-fit");
  expect(tokens, `${label} should not stretch compact VUI actions across the row`).not.toContain("[&_[data-vui=\"button\"]]:w-full");
  expect(tokens, `${label} should not stretch compact VUI actions across the row`).not.toContain("[&_[data-vui=\"button\"]]:[width:100%]");
}

function expectLongTextWraps(className: string, label: string): void {
  expect(className, `${label} should allow long Chinese and English labels to wrap`).toContain("[overflow-wrap:anywhere]");
  expect(className, `${label} should not hide primary text behind ellipsis`).not.toContain("[text-overflow:ellipsis]");
  expect(className, `${label} should not force long labels onto one line`).not.toContain("[white-space:nowrap]");
}

function expectNoLegacySurfaceDebt(styleMap: Record<string, string>, label: string): void {
  for (const [key, className] of Object.entries(styleMap)) {
    expect(className, `${label}.${key} should not restack opaque card backgrounds`).not.toContain("var(--surface-card)");
    expect(className, `${label}.${key} should not restack strong panel backgrounds`).not.toContain("var(--surface-panel-strong)");
    expect(className, `${label}.${key} should not carry route-level shadow tokens`).not.toContain("var(--shadow");
    expect(className, `${label}.${key} should not use decorative route gradients`).not.toContain("var(--vui-gradient");
    expect(className, `${label}.${key} should not use decorative Tailwind shadow utilities`).not.toContain("shadow-[");
  }
}

function findElement(
  node: ReactNode,
  predicate: (element: ReactElement<Record<string, unknown>>) => boolean,
): ReactElement<Record<string, unknown>> | null {
  if (!isValidElement<Record<string, unknown>>(node)) {
    return null;
  }
  if (predicate(node)) {
    return node;
  }
  const children = node.props.children;
  const childList = Array.isArray(children) ? children : [children];
  for (const child of childList) {
    const match = findElement(child as ReactNode, predicate);
    if (match) {
      return match;
    }
  }
  return null;
}

describe("AgentsRoute layout contract", () => {
  it("does not present failed empty summary metrics as nine real zeroes", () => {
    const failedValues = Array.from({ length: 9 }, () => agentSummaryMetricValue("error-empty", undefined, "不可用"));

    expect(failedValues).toEqual(Array(9).fill("不可用"));
    expect(failedValues).not.toContain(0);
    expect(agentSummaryMetricValue("ready", 0, "不可用")).toBe(0);
  });

  it("keeps summary ownership by default while accepting a successful deep-link workspace", () => {
    const summary = { source: "summary" };
    const full = { source: "full" };

    expect(resolveAgentWorkspaceSource({ summary, full, fullWorkspaceNeeded: false })).toBe(summary);
    expect(resolveAgentWorkspaceSource({ summary, full, fullWorkspaceNeeded: true })).toBe(full);
    expect(resolveAgentWorkspaceSource({ summary: undefined, full, fullWorkspaceNeeded: true })).toBe(full);
    expect(resolveAgentWorkspaceSource({ summary, full: undefined, fullWorkspaceNeeded: true })).toBe(summary);
  });

  it("keeps summary rows visible while surfacing a failed required full workspace", () => {
    expect(resolveAgentWorkspaceQueryState({
      hasSummary: true,
      hasFull: false,
      fullWorkspaceNeeded: true,
      summaryError: false,
      fullError: true,
    })).toEqual({ hasWorkspace: true, initialError: false, backgroundError: true, errorOwner: "full" });
  });

  it("keeps stale Agent data visible during refresh and background errors", () => {
    expect(resolveAgentListPresentation({ hasWorkspace: true, isPending: false, isFetching: true, isError: false })).toBe("refreshing");
    expect(resolveAgentListPresentation({ hasWorkspace: true, isPending: false, isFetching: false, isError: true })).toBe("error-with-data");
  });

  it("keeps background status visible when the retained Agent list is empty", () => {
    const baseProps = {
      copy: {
        loadFailed: "加载失败",
        loading: "加载中",
        noAgents: "暂无 Agent",
        retry: "重试",
        refreshing: "正在更新",
        staleError: "更新失败，继续显示已有数据",
        model: "模型",
        prompt: "提示词",
        runtimeStatus: "运行状态",
        modeMembership: "模式",
        statusReminders: "提醒",
      },
      columns: [],
      visibleAgentCount: 0,
      error: new Error("full workspace failed"),
      isPending: false,
      hasWorkspace: true,
      onRetry: vi.fn(),
      onSelectRow: vi.fn(),
      onToggleBulk: vi.fn(),
    };
    const trees = [
      AgentListStatePanel({ ...baseProps, isError: true, isFetching: false }),
      AgentListStatePanel({ ...baseProps, isError: false, isFetching: true }),
    ];

    for (const tree of trees) {
      expect(findElement(tree, (element) => element.props.role === "status")).toBeTruthy();
      expect(findElement(tree, (element) => element.props.title === "暂无 Agent")).toBeTruthy();
    }
  });

  it("wires the Agent list error retry control to the supplied callback", () => {
    const onRetry = vi.fn();
    const tree = AgentListStatePanel({
      copy: {
        loadFailed: "加载失败",
        loading: "加载中",
        noAgents: "暂无 Agent",
        retry: "重试",
        refreshing: "正在更新",
        staleError: "更新失败，继续显示已有数据",
        model: "模型",
        prompt: "提示词",
        runtimeStatus: "运行状态",
        modeMembership: "模式",
        statusReminders: "提醒",
      },
      columns: [],
      visibleAgentCount: 0,
      isError: true,
      error: new Error("network down"),
      isPending: false,
      isFetching: false,
      hasWorkspace: false,
      onRetry,
      onSelectRow: vi.fn(),
      onToggleBulk: vi.fn(),
    });
    const retryButton = findElement(tree, (element) => element.props.onPress === onRetry);

    expect(retryButton).toBeTruthy();
    retryButton?.props.onPress();
    expect(onRetry).toHaveBeenCalledOnce();
  });
  it("loads the read-only Agent config workspace endpoint", () => {
    expect(routeSource).toContain("fetchJson<AgentConfigWorkspaceWithTeamIndexes>(\"/api/agents/config-workspace?includeRuntime=false\")");
    expect(routeSource).toContain("fetchJson<AgentConfigWorkspaceAgent[]>(\"/api/agents?includeArchived=true&detail=summary\")");
    expect(routeSource).toContain("queryKeys.agentSummary(true)");
    expect(routeSource).toContain("queryKeys.agentConfigWorkspace()");
    expect(routeSource).toContain("const workspace = resolveAgentWorkspaceSource({");
    expect(routeSource).toContain('searchParams.get("create") === "1"');
    expect(routeSource).toContain("const createOpen = requestedCreate");
    expect(routeSource).toContain("setCreateWizardOpen(false)");
    expect(routeSource).toContain('const fullWorkspaceNeeded = Boolean(activePane === "effective" || activePane === "relations" || activePane === "config" || activePane === "activity" || requestedAgentId)');
    expect(routeSource).toContain("<AgentCreateWizardDialog");
    expect(routeSource).toContain("triggerRef={agentCreateTriggerRef}");
    expect(agentCreateDialogSource).toContain('enabled: open');
    expect(agentCreateDialogSource).toContain('queryKeys.agentConfigWorkspace()');
    expect(agentCreateDialogSource).toContain('queryKeys.tools()');
    expect(routeSource).toContain("enabled: fullWorkspaceNeeded");
    expect(routeSource).toContain("staleTime: 10_000");
  });

  it("binds the initial Agent list to the active summary/full-workspace data sources", () => {
    expect(routeSource).toContain("agentWorkspaceInitialLoading");
    expect(routeSource).toContain("agentWorkspaceInitialError");
    expect(routeSource).toContain("agentSummaryQuery.isError");
    expect(routeSource).toContain("agentSummaryQuery.isPending");
    expect(routeSource).not.toContain("<VLoadingValue");
    expect(managementHeaderPanelSource).not.toContain("AgentSummaryStrip");
    expect(routeSource).not.toContain("isError: workspaceQuery.isError,");
    expect(routeSource).not.toContain("isPending: workspaceQuery.isPending,");
  });

  it("keeps real zero distinct from an unresolved Agent summary", () => {
    expect(routeSource).not.toContain("agentSummaryInitialLoading");
    expect(routeSource).not.toContain("loadingAgentMetricValue");
    expect(agentSummaryMetricValue("ready", 0, "不可用")).toBe(0);
  });

  it("uses the lightweight shell language source instead of the full app dictionary", () => {
    expect(routeSource).toContain("useShellI18n");
    expect(routeSource).toContain("const { lang } = useShellI18n()");
    expect(routeSource).not.toContain("useAppI18n");
    expect(agentManagementNavSource).toContain("useShellI18n");
    expect(agentManagementNavSource).not.toContain("useAppI18n");
  });

  it("keeps Agent management as a first-class top navigation route", () => {
    expect(routerSource).toContain('path: "agents"');
    expect(routerSource).toContain("<AgentsRoute />");
    expect(shellSource).toContain('to="/agents"');
    expect(shellSource).toContain('t("navAgents")');
    expect(routeSource).toContain("<AgentManagementHeaderPanel");
    expect(managementHeaderPanelSource).not.toContain("AgentsRoute.styles");
    expect(managementHeaderPanelSource).toContain("<AgentManagementModuleBar");
    expect(managementHeaderPanelSource).toContain('active="agents"');
    expect(agentManagementModuleBarSource).toContain('<AgentManagementNav active={active} className={styles.managementNav} />');
    expect(agentManagementModuleBarSource).toContain('data-agent-management="module-bar"');
    expect(managementHeaderPanelSource).not.toContain("<AgentPageHeader");
    expect(managementHeaderPanelSource).not.toContain("<AgentSummaryStrip");
    expect(managementModuleBarStyles.managementNav).toBeTruthy();
    expect(managementModuleBarStyles.moduleBar).toBeTruthy();
    expect(managementModuleBarStyles.moduleBar).toMatch(/bg-vui-surface-toolbar|bg-\[var\(--vui-surface-toolbar\)\]/);
    expect(managementModuleBarStyles.moduleBar).not.toContain("transparent");
  });

  it("uses a compact VUI module bar with the primary Agent action", () => {
    expect(managementHeaderPanelSource).toContain("VIconButton");
    expect(managementHeaderPanelSource).toContain("VButton");
    expect(managementHeaderPanelSource).toContain("onCreateAgent");
    expect(routeSource).not.toContain("agentSummaryMetrics");
    expect(routeSource).not.toContain("styles.summaryCard");
    expect(routeSource).not.toContain("styles.refreshButton");
    expect(routeSource).not.toContain(['import { Button } from "', "@hero", "ui/react", '"'].join(""));
    expect(routeSource).not.toContain("disabled: workspaceQuery.isFetching");
  });

  it("uses the VUI product panel surface for the Agent workspace columns", () => {
    expect(routeSource).toContain("<AgentWorkspaceLayoutPanel");
    expect(workspaceLayoutPanelSource).toContain("AgentFilterRail");
    expect(workspaceLayoutPanelSource).toContain("AgentListWorkspacePanel");
    expect(workspaceLayoutPanelSource).toContain("AgentDetailWorkspacePanel");
    expect(detailWorkspacePanelSource).toContain("AgentWorkspacePanel");
    expect(routeSource).toContain("ariaLabel: copy.agentFilters");
    expect(filterRailSource).toContain('as="aside"');
    expect(listWorkspacePanelSource).toContain('as="main"');
    expect(detailWorkspacePanelSource).toContain('as="aside"');
    expect(routeSource).toContain("ariaLabel: activeGroupLabel");
    expect(routeSource).toContain("ariaLabel: selectedAgent ? agentLabel(selectedAgent) : copy.title");
    expect(stylesSource).not.toContain("0 14px 34px");
  });

  it("opens deep-linked Agent configuration and offers a governed return action", () => {
    expect(routeSource).toContain("useSearchParams");
    expect(routeSource).toContain("normalizeAgentConfigPane(searchParams.get(\"pane\"))");
    expect(routeSource).toContain("safeAgentCenterReturnTo(searchParams.get(\"returnTo\"))");
    expect(routeSource).toContain("agentCenterReturnLabel(searchParams.get(\"returnLabel\"), lang)");
    expect(routeSource).toContain('normalized === "config" || normalized === "changes" || normalized === "activity" || normalized === "overview"');
    expect(routeSource).toContain("safeReturnToPath");
    expect(routeSource).toContain("return safeReturnToPath(value)");
    expect(routeSource).toContain("const routeTargetKey = requestedAgentId ? `${requestedAgentId}:${requestedPane}` : \"\"");
    expect(routeSource).toContain("workspace.agents.find((agent) => agent.agentId === requestedAgentId)");
    expect(routeSource).toContain("if (requestedAgentId && !workspaceQuery.data)");
    expect(routeSource).toContain("setSelectedAgentId(targetAgent.agentId)");
    expect(routeSource).toContain("setActivePane(requestedPane)");
    expect(routeSource).toContain('setActiveFilter(targetAgent.status === "archived" ? "archived" : "active")');
    expect(routeSource).toContain('normalized === "supervised_evolution"');
    expect(routeSource).toContain("返回监督进化");
    expect(routeSource).toContain('normalized === "self_evolution"');
    expect(routeSource).toContain("返回自进化");
    expect(routeSource).toContain('normalized === "tools"');
    expect(routeSource).toContain("返回工具配置");
    expect(routeSource).toContain('normalized === "teams"');
    expect(routeSource).toContain("返回团队");
    expect(routeSource).toContain('normalized === "chat"');
    expect(routeSource).toContain("返回会话");
    expect(routeSource).toContain('normalized === "memory"');
    expect(routeSource).toContain("返回记忆库");
    expect(routeSource).toContain('normalized === "research_flow"');
    expect(routeSource).toContain("返回科研流程画布");
    expect(routeSource).toContain("returnBannerTitle: \"返回跳转前页面\"");
    expect(detailWorkspacePanelSource).toContain("AgentReturnBannerPanel");
    expect(routeSource).toContain("onReturn: () => navigate(returnToPath)");
    expect(returnBannerPanelSource).toContain('from "./AgentReturnBannerPanel.styles"');
    expect(returnBannerPanelSource).not.toContain("AgentsRoute.styles");
    expect(returnBannerPanelSource).toContain("className={styles.returnBanner}");
    expect(returnBannerPanelSource).toContain("className={styles.returnBannerButton}");
    expect(routeSource).toContain("if (requestedAgentId && selectedAgent?.agentId === requestedAgentId)");
    expect(routeSource).not.toContain("className={styles.returnButton}");
    expect(returnBannerStyles.returnBanner).toBeTruthy();
    expect(returnBannerStyles.returnBannerCopy).toBeTruthy();
    expect(returnBannerStyles.returnBannerButton).toBeTruthy();
  });

  it("uses filter, table, and detail panels instead of a card wall", () => {
    expect(workspaceLayoutPanelSource).toContain("<AgentFilterRail");
    expect(workspaceLayoutPanelSource).toContain("<AgentListWorkspacePanel");
    expect(routeSource).not.toContain("<AgentFilterRail");
    expect(routeSource).not.toContain("<AgentListWorkspacePanel");
    expect(listWorkspacePanelSource).toContain("styles.agentPanel");
    expect(detailWorkspacePanelSource).toContain("styles.detailPanel");
    expect(listWorkspacePanelSource).toContain('from "./AgentListWorkspacePanel.styles"');
    expect(listWorkspacePanelSource).not.toContain("AgentsRoute.styles");
    expect(detailWorkspacePanelSource).toContain('from "./AgentDetailWorkspacePanel.styles"');
    expect(detailWorkspacePanelSource).not.toContain("AgentsRoute.styles");
    expect(listWorkspacePanelSource).toContain("<AgentListStatePanel");
    expect(listStatePanelSource).toContain("<AgentDenseList");
    expect(routeSource).toContain("agent.avatarImageUrl");
    expect(routeSource).toContain("<AgentSelectedDetailContentPanel");
    expect(selectedDetailContentPanelSource).toContain("<AgentDetailHeaderPanel");
    expect(routeSource).not.toContain("<AgentDetailHeaderPanel");
    expect(detailHeaderPanelSource).toContain('from "./AgentDetailHeaderPanel.styles"');
    expect(detailHeaderPanelSource).not.toContain("AgentsRoute.styles");
    expect(detailHeaderPanelSource).toContain("function issueToneClass");
    expect(detailHeaderPanelSource).toContain("onToggleInspector");
    expect(detailHeaderPanelSource).toContain("onRun");
    expect(selectedDetailContentPanelSource).toContain('activePane === "overview"');
    expect(selectedDetailContentPanelSource).toContain('activePane === "config"');
    expect(selectedDetailContentPanelSource).toContain('activePane === "activity"');
    expect(routeSource).not.toContain('activePane === "overview" ? (');
    expect(routeSource).not.toContain('activePane === "config" ? (');
    expect(routeSource).not.toContain('activePane === "activity" ? (');
    expect(detailHeaderPanelSource).toContain("AgentAvatarEditorPanel");
    expect(avatarEditorPanelSource).toContain('from "./AgentAvatarEditorPanel.styles"');
    expect(avatarEditorPanelSource).not.toContain("AgentsRoute.styles");
    expect(avatarEditorPanelSource).toContain("styles.agentAvatarImage");
    expect(routeSource).toContain("/api/agents/avatar-options");
    expect(routeSource).toContain("/avatar-image");
    expect(routeSource).toContain("/avatar");
    expect(routeSource).not.toContain("styles.avatarEditorPanel");
    expect(avatarEditorPanelSource).toContain("styles.avatarEditorPanel");
    expect(avatarEditorStyles.avatarEditorPanel).toBeTruthy();
    expect(avatarEditorStyles.contextLine).toBeTruthy();
    expect(avatarEditorPanelSource).not.toContain("useQuery");
    expect(avatarEditorPanelSource).not.toContain("useMutation");
    expect(avatarEditorPanelSource).not.toContain("fetchJson");
    expect(routeSource).not.toContain("agentCardGrid");
  });

  it("keeps common Agent filters prominent and folds low-frequency filters away", () => {
    expect(routeSource).toContain('useState<FilterId>("active")');
    expect(routeSource).toContain("groupedFilters");
    expect(routeSource).toContain("advancedGroupedFilters");
    expect(routeSource).toContain("teamIndexes");
    expect(routeSource).toContain("copy.filterSections");
    expect(routeSource).toContain("copy.groupLabels");
    expect(routeSource).toContain('const sectionOrder = ["status", "boundary", "team_index"] as const;');
    expect(routeSource).toContain('const sectionOrder = ["source_scope", "mode", "reference"] as const;');
    expect(routeSource).toContain("workspaceTeamIndexes(workspace)");
    expect(routeSource).toContain('section === "team_index"');
    expect(routeSource).toContain('section === "source_scope"');
    expect(routeSource).toContain('team_index: "团队索引"');
    expect(routeSource).toContain('source_scope: "来源范围"');
    expect(routeSource).toContain('team_index: "Team indexes"');
    expect(routeSource).toContain('source_scope: "Source scope"');
    expect(routeSource).toContain('moreFilters: "更多筛选"');
    expect(routeSource).toContain('moreFilters: "More filters"');
    expect(agentWorkspaceCacheSource).toContain("sourceScopeGroupId");
    expect(agentWorkspaceCacheSource).toContain("teamIndexesWithoutAgentIds");
    expect(routeSource).toContain('section === "boundary"');
    expect(routeSource).toContain("managementSection,");
    expect(routeSource).toContain("sections: filterSections");
    expect(routeSource).toContain("advancedSections: advancedFilterSections");
    expect(routeSource).toContain("groupDisplayLabel(group, copy)");
    expect(filterRailSource).toContain("<details");
    expect(filterRailSource).toContain("agent-filter-more");
    expect(filterRailSource).toContain("STATUS_BUTTON_BASE");
    expect(filterRailSource).toContain("secondarySections");
    expect(filterRailSource).not.toContain("agent-filter-queue");
    expect(filterRailSource).not.toContain("agent-filter-storage");
    expect(filterRailSource).not.toContain("queueCount");
  });

  it("keeps Agent filter explanations in accessible VUI tooltips", () => {
    expect(filterRailSource).toContain("VTooltip");
    expect(filterRailSource).toContain("content={group.title}");
    expect(filterRailSource).toContain('width="wide"');
    expect(filterRailSource).toContain("aria-label={group.ariaLabel}");
    expect(filterRailSource).not.toContain("title={group.title}");
  });

  it("keeps archived Agents out of lightweight mode filter counts", () => {
    expect(routeSource).toContain('lightweightAgentGroup("active", "可用 Agent", "status"');
    expect(routeSource).toContain('lightweightAgentGroup("archived", "已归档", "status"');
    expect(routeSource).toContain('lightweightAgentGroup("chat", "会话模式", "mode", "属于 Chat 运行模式或会话可用池的 Agent。", activeAgents');
    expect(routeSource).toContain('lightweightAgentGroup("research", "科研模式", "mode", "属于 Research 运行模式或科研池的 Agent。", activeAgents');
    expect(routeSource).toContain('lightweightAgentGroup("self_evolution", "自进化模式", "mode", "占用自进化模式引用的 Agent。", activeAgents');
  });

  it("labels Agent filter health counts instead of concatenating bare numbers", () => {
    expect(routeSource).toContain("function groupAriaLabel");
    expect(routeSource).toContain("groupAriaLabel(displayLabel, group, copy, lang)");
    expect(routeSource).toContain('group.id === "setup:inbox" ? copy.statusReminderShort : copy.healthIssueShort');
    expect(routeSource).not.toContain("{group.healthCount ? <em>{group.healthCount}</em> : null}");
  });

  it("localizes the workspace health badge and names the avatar editor trigger", () => {
    expect(routeSource).not.toContain("workspaceHealthStatusLabel(healthStatus, lang)");
    expect(routeSource).not.toContain("workspaceHealthStatusDescription(healthStatus, summary, lang)");
    expect(routeSource).toContain("healthTitle: issueSummary(selectedAgent.health, lang)");
    expect(detailHeaderPanelSource).toContain("content={healthTitle}");
    expect(detailHeaderPanelSource).toContain("styles.detailHealthStatus");
    expect(avatarEditorPanelSource).toContain("aria-label={copy.editAvatar}");
  });

  it("shows the unified Agent card sections needed by later editing phases", () => {
    expect(routeSource).toContain("copy.model");
    expect(routeSource).toContain("agentModelLabel");
    expect(routeSource).toContain("buildAgentModelChoices");
    expect(routeSource).not.toContain("modelProfileSelectValue");
    expect(routeSource).toContain("copy.prompt");
    expect(routeSource).toContain("promptTemplateDisplayName(agent.promptTemplate, agent.promptTemplateId, lang)");
    expect(routeSource).toContain("promptTemplateDisplayName(selectedAgent.promptTemplate, selectedAgent.promptTemplateId, lang)");
    expect(routeSource).toContain("promptTemplateOptionLabel(template, lang)");
    expect(routeSource).toContain('"research ceo": "科研负责人"');
    expect(routeSource).not.toContain("<span>{agent.promptTemplate?.name || agent.promptTemplateId || \"-\"}</span>");
    expect(routeSource).toContain("copy.tools");
    expect(routeSource).toContain("copy.memory");
    expect(routeSource).toContain("copy.runtimeStatus");
    expect(routeSource).toContain("runtimeStatusLabel");
    expect(routeSource).toContain("runtimeStatusTone");
    expect(routeSource).toContain("runtimeNextStep");
    expect(routeSource).toContain("copy.territory");
    expect(routeSource).toContain("workspaceTerritory");
    expect(routeSource).toContain("copy.context");
    expect(routeSource).toContain("copy.communication");
    expect(routeSource).toContain("copy.delegation");
    expect(routeSource).toContain("copy.modeMembership");
    expect(routeSource).toContain("copy.references");
    expect(overviewPanelSource).toContain('from "./AgentOverviewPanel.styles"');
    expect(overviewPanelSource).not.toContain("AgentsRoute.styles");
    expect(overviewStyles.factGrid).toContain("[grid-template-columns:repeat(2,_minmax(0,_1fr))]");
    expect(overviewStyles.factGrid).toContain("[&_section]:[grid-template-columns:18px_minmax(0,_1fr)]");
    expect(overviewStyles.factGrid).toContain("[&_strong]:[text-overflow:ellipsis]");
  });

  it("lets each Agent inherit or override its context compression policy", () => {
    expect(routeSource).toContain("AgentContextCompressionPolicy");
    expect(coreConfigPanelSource).toContain("contextCompressionPolicy: AgentContextCompressionPolicyDraft");
    expect(routeSource).toContain("function contextCompressionDraftFromAgent");
    expect(routeSource).toContain("function contextCompressionPolicyFromDraft");
    expect(routeSource).toContain("contextCompressionPolicy: contextCompressionPolicyFromDraft(payload.draft.contextCompressionPolicy)");
    expect(routeSource).toContain("updateContextCompressionDraft");
    expect(selectedDetailContentPanelSource).toContain("<AgentConfigPrimaryPanePanel");
    expect(configPrimaryPanePanelSource).toContain("<AgentCoreConfigPanel");
    expect(routeSource).toContain("onContextCompressionChange: updateContextCompressionDraft");
    expect(coreConfigPanelSource).toContain("<AgentContextCompressionPanel");
    expect(coreConfigPanelSource).toContain('<details className={styles.advancedConfig}>');
    expect(coreConfigPanelSource).toContain("const primaryLlmSlot");
    expect(coreConfigPanelSource).toContain("const advancedLlmSlots");
    expect(coreConfigPanelSource).toContain("policy={draft.contextCompressionPolicy}");
    expect(coreConfigPanelSource).toContain("onPolicyChange={onContextCompressionChange}");
    expect(contextCompressionPanelSource).toContain("copy.contextCompressionPolicy");
    expect(contextCompressionPanelSource).toContain("copy.contextCompressionInherit");
    expect(contextCompressionPanelSource).toContain("copy.contextCompressionCustom");
    expect(routeSource).toContain("contextCompressionPolicyLine");
    expect(routeSource).toContain("compressionTriggerTokenLimit");
    expect(routeSource).toContain("modelContextWindowLimit");
    expect(contextCompressionPanelSource).toContain("styles.compressionPolicyGrid");
    expect(contextCompressionPanelSource).toContain("styles.compressionPolicySubgrid");
    expect(contextCompressionPanelSource).toContain("styles.compressionPolicyFooter");
    expect(contextCompressionPanelSource).toContain("VTooltip");
    expect(contextCompressionPanelSource).toContain('<VTooltip content={title} width="wide">');
    expect(contextCompressionPanelSource).not.toContain('className={styles.fieldWide} title={title}');
    expect(contextCompressionPanelSource).toContain('aria-label={`${copy.contextCompressionPolicy} · ${title}`}');
    expect(contextCompressionPanelSource).toContain('from "./AgentContextCompressionPanel.styles"');
    expect(contextCompressionPanelSource).not.toContain("AgentsRoute.styles");
    expect(contextCompressionStyles.compressionPolicyGrid).toBeTruthy();
    expect(contextCompressionStyles.compressionPolicySubgrid).toBeTruthy();
    expect(contextCompressionStyles.compressionPolicyFooter).toBeTruthy();
  });

  it("shows LLM names in model selectors instead of role-prefixed profile labels", () => {
    expect(routeSource).toContain("AgentModelChoice");
    expect(routeSource).toContain("model.model");
    expect(routeSource).toContain("model.modelId");
    expect(routeSource).toContain("function agentModelChoiceAllowed");
    expect(routeSource).toContain("!text.includes(\"image2\")");
    expect(routeSource).toContain("buildAgentModelChoices(workspace?.agentModelChoices ?? [])");
    expect(routeSource).toContain(
      ".filter((model) => model.runtimeSelectable && agentModelChoiceAllowed(model))",
    );
    expect(routeSource).toContain("coreConfigLlmSlots");
    expect(routeSource).toContain("selectedModelId");
    expect(routeSource).toContain("agentLlmSlots(workspace)");
    expect(routeSource).toContain("workspace?.agentLlmSlots?.length");
    expect(routeSource).toContain("key: model.modelId");
    expect(routeSource).toContain("agentDialogueModelDisplay(agent, lang)");
    expect(routeSource).toContain("unresolved_model_reference_dialogue");
    expect(routeSource).toContain("模型库未注册");
    expect(modelPickerSource).toContain("模型与当前 Agent 槽位不兼容");
    expect(modelPickerSource).toContain("上游模型当前不可用");
    expect(modelPickerSource).toContain("请先保存或放弃未保存修改");
    expect(createPanelSource).toContain("const modelSelectOptions = providerModels.map((model)");
    expect(agentCreateDialogSource).toContain("selectedModelId={selectedModelId}");
    expect(createPanelSource).toContain("value={selectedModelId}");
    expect(coreConfigPanelSource).toContain("<AgentModelPicker");
    expect(routeSource).toContain(
      "/llm-bindings/${encodeURIComponent(payload.slot.slot)}/promote",
    );
    expect(routeSource).toContain("expectedBaseHash");
    expect(routeSource).toContain("expectedAgentUpdatedAt");
    expect(routeSource).toContain("confirmed: true");
    expect(coreConfigPanelSource).toContain("styles.llmSlotGrid");
    expect(coreConfigPanelSource).toContain('from "./AgentCoreConfigPanel.styles"');
    expect(coreConfigPanelSource).not.toContain("AgentsRoute.styles");
    expect(coreConfigPanelSource).toContain("function healthGuideToneClass");
    expect(coreConfigPanelSource).toContain("copy.llmSlotsHint");
    expect(routeSource).toContain("按 Agent 自己配置对话、心智模型、摘要、子 Agent 和视觉等 LLM 槽位");
    expect(routeSource).toContain("设置页只维护模型库资产");
    expect(createPanelSource).toContain("label: model.label");
    expect(createPanelSource).not.toContain("title={model.modelLabel || model.modelId}");
    expect(createPanelSource).toContain('from "./AgentCreatePanel.styles"');
    expect(createPanelSource).not.toContain("AgentsRoute.styles");
    expect(createPanelSource).toContain("options={modelSelectOptions}");
    expect(routeSource).toContain("candidates: workspace?.agentModelChoices ?? []");
    expect(coreConfigPanelSource).toContain("candidates={candidates}");
    expect(routeSource).not.toContain("buildModelProfileChoices(workspace?.modelProfiles ?? [])");
    expect(routeSource).not.toContain("modelProfileChoices.map((profile)");
    expect(routeSource).not.toContain("value={createDraft.profileId}");
    expect(routeSource).not.toContain("value={configDraft.profileId}");
    expect(routeSource).not.toContain("profileByModel");
    expect(routeSource).not.toContain("profileByLabel");
    expect(routeSource).not.toContain("choices.has(labelKey)");
    expect(routeSource).not.toContain("profileIds: [profile.profileId]");
    expect(routeSource).not.toContain("title={profile.detail || profile.modelId}");
    expect(routeSource).not.toContain("{agent.modelProfile?.label || agent.profileId || \"-\"}");
    expect(routeSource).not.toContain("{profile.label || profile.profileId} · {profile.model || profile.providerKind || \"-\"}");
  });

  it("shows GPT reasoning effort only for Agent slots whose bound model supports it", () => {
    expect(coreConfigPanelSource).toContain("reasoningEffortBySlot: Record<string, string>");
    expect(routeSource).toContain("agentModelSupportsReasoningEffort");
    expect(routeSource).toContain("supportsReasoningEffort");
    expect(routeSource).toContain("metadata.llmReasoningEffort = pruned");
    expect(routeSource).toContain("pruneAgentReasoningEffortBySlot");
    expect(coreConfigPanelSource).toContain("copy.reasoningEffort");
    expect(routeSource).toContain("reasoningEffortOptions");
    expect(routeSource).toContain("agentModelReasoningEffortValues");
    expect(coreConfigPanelSource).toContain("value={reasoningEffort}");
    expect(coreConfigPanelSource).toContain("reasoningEffortOptions.map");
  });

  it("guides Agent creation through defaults, provider-model linkage, and a final review", () => {
    expect(routeSource).toContain('import { AgentCreateWizardDialog } from "./agent-create/AgentCreateWizardDialog"');
    expect(agentCreateContractSource).toContain('id: "recommended"');
    expect(agentCreateContractSource).toContain('id: "coding"');
    expect(agentCreateContractSource).toContain('id: "research"');
    expect(agentCreateContractSource).toContain('providerId: model.providerId');
    expect(agentCreateContractSource).toContain('providerLabel: model.providerLabel');
    expect(agentCreateContractSource).toContain('selectedToolBundleIds: selectAvailableToolBundles');
    expect(createPanelSource).toContain("const [activeStep, setActiveStep] = useState(0)");
    expect(createPanelSource).toContain('aria-current={index === activeStep ? "step" : undefined}');
    expect(createPanelSource).toContain("const providerChoices = useMemo");
    expect(createPanelSource).toContain("firstAvailableModelId(modelChoices, providerId)");
    expect(createPanelSource).toContain("onApplyPreset(preset.draft)");
    expect(createPanelSource).toContain("setActiveStep(1)");
    expect(createPanelSource).toContain("stepReady.slice(0, index).every(Boolean)");
    expect(createPanelSource).toContain("isDisabled={!stepReady[activeStep] || pending}");
    expect(createPanelSource).toContain("isDisabled={!canCreate || pending}");
    expect(createPanelSource).toContain("summaryItems.map");
    expect(createPanelStyles).toHaveProperty("quickFill");
    expect(createPanelStyles).toHaveProperty("wizardSteps");
    expect(createPanelStyles).toHaveProperty("createSummary");
    expect(agentCreateDialogSource).toContain("<AgentCreatePanel");
    expect(agentCreateDialogSource).toContain('role="dialog"');
    expect(agentCreateDialogSource).toContain("createPortal(");
    expect(agentCreateDialogStyles.overlay).toContain("fixed inset-0");
    expect(agentCreateDialogStyles.dialog).toContain("min(880px");
    expect(listWorkspacePanelSource).not.toContain("AgentCreatePanel");
    expect(listWorkspacePanelSource).not.toContain("createOpen");
    expect(workspaceLayoutPanelSource).not.toContain("AgentCreatePanel");
    expect(workspaceLayoutPanelSource).not.toContain("workspaceCreating");
    expect(createPanelStyles.createAgentPanel).not.toContain("[overflow:auto]");
    expect(createPanelStyles.createToolBundleGrid).not.toContain("[max-height:184px]");
    expect(createPanelStyles.createToolBundleGrid).not.toContain("[overflow:auto]");
    expect(createPanelStyles.finalStepLayout).toContain("[grid-template-columns:minmax(0,_1.7fr)_minmax(260px,_0.8fr)]");
    expect(createPanelStyles.finalStepLayout).toContain("max-[980px]:[grid-template-columns:1fr]");
    expect(createPanelStyles.createSummary).toContain("[position:sticky]");
    expect(createPanelStyles.createSummary).toContain("max-[980px]:[position:static]");
    expect(createPanelStyles.editorActions).toContain("[position:sticky]");
    expect(createPanelStyles.editorActions).toContain("[bottom:0]");
  });

  it("keeps permanent Agent deletion behind the archived-state safety gate", () => {
    expect(routeSource).toContain('const canPurgeAgent = Boolean(selectedAgent?.agentId && selectedAgent.status === "archived" && !selectedAgentProtected)');
    expect(routeSource).toContain('agent.status !== "archived"');
    expect(routeSource).toContain("copy.bulkSkippedActive");
    expect(routeSource).toContain("onArchive: archiveSelectedAgent");
    expect(routeSource).toContain("onPurge: purgeSelectedAgent");
    expect(routeSource).toContain("agentName: agentLabel(selectedAgent)");
    expect(archiveZonePanelSource).toContain("!isArchived ? (");
    expect(archiveZonePanelSource).toContain('setConfirmKind("archive")');
    expect(archiveZonePanelSource).toContain('setConfirmKind("purge")');
    expect(archiveZonePanelSource).toContain("VConfirmDialog");
    expect(archiveZonePanelSource).toContain("onConfirm={() => {");
    expect(archiveZonePanelSource).toContain("onPurge()");
    expect(archiveZonePanelSource).toContain("onArchive()");
    expect(archiveZonePanelSource).toContain('variant="danger"');
    expect(archiveZonePanelSource).toContain("VTooltip");
    expect(archiveZonePanelSource).toContain('<VTooltip content={title} width="wide">');
    expect(archiveZonePanelSource).not.toContain('title={title}');
    expect(archiveZonePanelSource).toContain('aria-label={`${heading} · ${title}`}');
    expect(archiveZonePanelSource).toContain('from "./AgentArchiveZonePanel.styles"');
    expect(archiveZonePanelSource).not.toContain("AgentsRoute.styles");
    expect(archiveZonePanelSource).not.toContain("window.confirm");
    expect(routeSource).not.toContain("window.confirm(copy.purgeConfirm");
    expect(routeSource).not.toContain("window.confirm(copy.archiveConfirm");
    expect(archiveZoneStyles.dangerZone).toBeTruthy();
    expect(routeSource).toContain("已彻底删除归档 Agent");
    expect(routeSource).not.toContain("const canPurgeAgent = Boolean(selectedAgent?.agentId && !selectedAgentProtected)");
  });

  it("updates mode membership locally after saving so bindings stay aligned", () => {
    expect(routeSource).toContain("fetchJson<AgentModeBindings>");
    expect(routeSource).toContain("queryClient.setQueryData<AgentConfigWorkspace | undefined>");
    expect(routeSource).toContain("modeBindings: payload.modes ?? current.modeBindings");
    expect(routeSource).toContain("setMembershipDraft(variables.draft)");
  });

  it("routes membership guidance to the team surface and not just the config pane", () => {
    expect(routeSource).toContain("route: agent?.agentId ? `/teams?agent=${encodeURIComponent(agent.agentId)}` : \"/teams\"");
    expect(routeSource).toContain("void navigate(route)");
    expect(managementBriefPanelSource).toContain("onOpenRoute(action.route)");
    expect(routeSource).toContain("onSelectPane: setActivePane");
    expect(selectedDetailContentPanelSource).toContain("<AgentManagementBriefPanel");
    expect(managementBriefPanelSource).toContain("onSelectPane(action.pane)");
    expect(routeSource).toContain("copy.nextSetupMembership");
  });

  it("keeps tool and runtime completeness strict enough to avoid false positives", () => {
    expect(routeSource).toContain("function hasToolPolicyConfiguration(agent: AgentConfigWorkspaceAgent | null | undefined)");
    expect(routeSource).toContain("policy?.blockedTools?.length");
    expect(routeSource).toContain("function agentHasRuntimeSignal(agent: AgentConfigWorkspaceAgent | null | undefined)");
    expect(routeSource).toContain("const runtimeState = String(agent?.runtimeStatus?.state || \"\").trim()");
    expect(routeSource).toContain("runtimeState && runtimeState !== \"idle\"");
    expect(routeSource).toContain("function hasActionableHealthIssue(agent: AgentConfigWorkspaceAgent | null | undefined)");
    expect(routeSource).toContain('issue.severity === "blocking" || issue.severity === "warning"');
    expect(routeSource).toContain("count(hasActionableHealthIssue)");
  });

  it("creates Agents through tool bundle presets instead of raw tool strings", () => {
    expect(agentCreateContractSource).toContain("DEFAULT_SESSION_AGENT_ALLOWED_TOOLS");
    expect(agentCreateContractSource).toContain("preferredTools");
    expect(agentCreateContractSource).toContain("\"conversation_log_inspect_tool\"");
    expect(agentCreateContractSource).not.toContain("\"read_file_tool\",");
    expect(agentCreateContractSource).toContain("\"grep_search_tool\"");
    expect(agentCreateContractSource).toContain("\"glob_tool\"");
    expect(agentCreateContractSource).not.toContain("\"cli_agent_run_tool\"");
    expect(agentCreateContractSource).not.toContain("\"image2_generate_tool\"");
    expect(agentCreateContractSource).toContain("DEFAULT_SESSION_AGENT_ALLOWED_TOOLS.join(\", \")");
    expect(agentCreateContractSource).toContain("const fallbackAllowedTools = bundles.length ? [] : expertiseFromDraft(draft.allowedTools)");
    expect(agentCreateContractSource).toContain("const allowedTools = sortedIds([...selectedAllowedTools, ...requiredAllowedTools])");
    expect(agentCreateContractSource).toContain("const selectedPreferredTools = selectedToolPolicy.preferredTools.length");
    expect(agentCreateContractSource).toContain("const preferredTools = sortedIds(");
    expect(agentCreateContractSource).toContain("[...selectedPreferredTools, ...requiredPreferredTools].filter((tool) => allowedTools.includes(tool))");
    expect(agentCreateContractSource).toContain("REQUIRED_SESSION_AGENT_ALLOWED_TOOLS");
    expect(agentCreateContractSource).toContain("REQUIRED_SESSION_AGENT_PREFERRED_TOOLS");
    expect(agentCreateContractSource).not.toContain("const sessionDefaultAllowedTools = workSession ? DEFAULT_SESSION_AGENT_ALLOWED_TOOLS : []");
    expect(agentCreateContractSource).not.toContain("const allowedTools = sortedIds([...sessionDefaultAllowedTools, ...selectedAllowedTools])");
    expect(agentCreateContractSource).toContain("selectedToolBundleIds: string[]");
    expect(agentCreateContractSource).toContain("function defaultCreateToolBundleIds");
    expect(agentCreateContractSource).toContain('const preferred = workSession ? ["core"] : ["core", "research", "collaboration"]');
    expect(agentCreateContractSource).toContain("return selected.length ? selected : bundles[0]?.bundleId ? [bundles[0].bundleId] : []");
    expect(agentCreateContractSource).toContain("const hasToolPolicyChoice = selectedPolicy.selectedBundles.length > 0 || fallbackAllowedTools.length > 0");
    expect(agentCreateContractSource).toContain("&& (workSession ? hasToolPolicyChoice : configuredToolCount > 0)");
    expect(agentCreateContractSource).toContain("function toolBundleIdsForModeChange");
    expect(agentCreateContractSource).toContain("const hasCustomSelection = draft.selectedToolBundleIds.length > 0 && !sameStringSet(draft.selectedToolBundleIds, currentDefaults)");
    expect(agentCreateContractSource).toContain("function toolBundleSelectionToPolicy");
    expect(agentCreateContractSource).toContain("function createToolBundleSummary");
    expect(createPanelSource).toContain("copy.createAgentToolBundles");
    expect(createPanelSource).toContain("toolBundlesLabel");
    expect(createPanelSource).not.toContain("copy.createAgentToolBundlePreview");
    expect(agentCreateContractSource).toContain("creationToolBundleIds: sortedIds(draft.selectedToolBundleIds)");
    expect(agentCreateContractSource).toContain("toolPolicy: {");
    expect(workspaceLayoutPanelSource).not.toContain("styles.workspaceCreating");
    expect(routeSource).not.toContain("toolPolicy: workSession ? {} : {");
    expect(styles.createToolBundleGrid).toBeTruthy();
    expect(styles.createToolBundleOption).toBeTruthy();
    expect(styles.createToolBundleSelected).toBeTruthy();
    expect(createPanelStyles).not.toHaveProperty("createToolBundlePreview");
    expect(workspaceLayoutStyles.workspace).toBeTruthy();
  });

  it("keeps disabled tool-query fallbacks referentially stable so Agent navigation can settle", () => {
    expect(routeSource).toContain("const EMPTY_TOOL_BUNDLES: ToolBundle[] = []");
    expect(routeSource).toContain("const EMPTY_TOOL_REGISTRY_ITEMS: ToolRegistryItem[] = []");
    expect(routeSource).toContain("const EMPTY_AGENT_CONFIG_GROUPS: AgentConfigWorkspaceGroup[] = []");
    expect(routeSource).toContain("const toolBundles = toolsQuery.data?.toolBundles ?? EMPTY_TOOL_BUNDLES");
    expect(routeSource).toContain("const tools = toolsQuery.data?.tools ?? EMPTY_TOOL_REGISTRY_ITEMS");
    expect(routeSource).toContain("const groups = workspace?.groups ?? EMPTY_AGENT_CONFIG_GROUPS");
    expect(routeSource).not.toContain("const toolBundles = toolsQuery.data?.toolBundles ?? []");
    expect(routeSource).not.toContain("const tools = toolsQuery.data?.tools ?? []");
    expect(routeSource).not.toContain("const groups = workspace?.groups ?? []");
  });

  it("uses user-facing Chinese labels instead of internal workspace terms", () => {
    expect(routeSource).toContain("系统编号");
    expect(routeSource).toContain("工具能力");
    expect(routeSource).toContain("记忆设置");
    expect(routeSource).toContain("工作空间");
    expect(routeSource).toContain("私人工作区");
    expect(routeSource).toContain("共享资料区");
    expect(routeSource).toContain("默认保存位置");
    expect(routeSource).toContain("使用位置");
    expect(routeSource).toContain("协作助手");
    expect(routeSource).toContain("工具能力模板");
    expect(routeSource).toContain("记忆范围模板");
    expect(routeSource).not.toContain("后台编号");
    expect(routeSource).not.toContain("工具权限");
    expect(routeSource).not.toContain("记忆策略");
    expect(routeSource).not.toContain("工作领地");
    expect(routeSource).not.toContain("私有写入根");
    expect(routeSource).not.toContain("共享读取区");
    expect(routeSource).not.toContain("默认写入边界");
    expect(routeSource).not.toContain("模式归属");
    expect(routeSource).not.toContain("策略注册表待接入");
    expect(routeSource).not.toContain("记忆边界模板");
    expect(routeSource).not.toContain("工具权限模板");
  });

  it("edits the minimal Agent card fields through the Agent PATCH endpoint", () => {
    expect(routeSource).toContain("AgentConfigDraft");
    expect(routeSource).toContain("useMutation");
    expect(coreConfigPanelSource).toContain("copy.configTitle");
    expect(routeSource).toContain("copy.toolPolicyPickerHint");
    expect(routeSource).toContain("copy.memoryPolicyPickerHint");
    expect(routeSource).not.toContain("copy.configGuideTitle");
    expect(routeSource).not.toContain("copy.configGuideBoundaryHint");
    expect(routeSource).not.toContain("styles.configGuidePanel");
    expect(routeSource).not.toContain("这页先回答三个问题");
    expect(coreConfigPanelSource).toContain("VContextualHint");
    expect(coreConfigPanelSource).toContain("const slotHint");
    expect(coreConfigPanelSource).toContain("content={slotHint}");
    expect(coreConfigPanelSource).toContain("content={title}");
    expect(coreConfigPanelSource).toContain("content={copy.llmSlotsHint}");
    expect(coreConfigPanelSource).not.toContain("title={copy.llmSlotsHint}");
    expect(coreConfigPanelSource).not.toContain("title={`${slot.required ? copy.requiredSlot : copy.optionalSlot} · ${slot.description}`}");
    expect(coreConfigPanelSource).not.toContain("className={styles.configEditor} title={title}");
    expect(routeSource).toContain("memoryPolicyTooltip: copy.memoryPolicyPickerHint");
    expect(coreConfigPanelSource).toContain("tooltip={memoryPolicyTooltip}");
    expect(routeSource).toContain("displayName: payload.draft.displayName");
    expect(routeSource).toContain("llmBindings: normalizeAgentLlmBindings(payload.draft.llmBindings)");
    expect(routeSource).toContain("promptTemplateId: payload.draft.promptTemplateId");
    expect(routeSource).toContain("toolPolicyId: payload.draft.toolPolicyId");
    expect(routeSource).toContain("memoryPolicyId: payload.draft.memoryPolicyId");
    expect(routeSource).toContain("status: payload.draft.status");
    expect(routeSource).toContain("method: \"PATCH\"");
    expect(routeSource).toContain("queryKeys.agentConfigWorkspace()");
    expect(coreConfigStyles.healthGuidePanel).toBeTruthy();
    expect(coreConfigStyles.healthGuide_warning).toBeTruthy();
  });

  it("keeps Agent Center helper copy in hover text instead of permanent explanatory blocks", () => {
    expect(managementHeaderPanelSource).not.toContain("copy.subtitle");
    expect(managementHeaderPanelSource).not.toContain("AgentPageHeader");
    expect(routeSource).not.toContain("<p className={styles.subtitle}>{copy.subtitle}</p>");
    expect(routeSource).toContain("issueSummary: issueSummary(agent.health, lang)");
    expect(denseListSource).toContain("VTooltip");
    expect(denseListSource).toContain("const rowTooltip");
    expect(denseListSource).toContain("content={rowTooltip}");
    expect(denseListSource).toContain("content={row.selectLabel}");
    expect(denseListSource).not.toContain("title={row.issueSummary}");
    expect(denseListSource).not.toContain("title={row.modelDetail}");
    expect(denseListSource).not.toContain("title={row.selectLabel}");
    expect(routeSource).not.toContain("<small>{issueSummary(agent.health, lang)}</small>");
    expect(denseListSource).toContain("title={column.description}");
    expect(routeSource).not.toContain("<span>{column.description}</span>");
    expect(createPanelSource).not.toContain("content={toolBundleSummary.meta || copy.createAgentToolBundleEmpty}");
    expect(routeSource).not.toContain("<small>{createToolBundleSummaryValue.meta || copy.createAgentToolBundleEmpty}</small>");
    expect(routeSource).not.toContain("<small>{toolBundleMeta(bundle, lang)}</small>");
    expect(routeSource).toContain("healthTitle: issueSummary(selectedAgent.health, lang)");
    expect(detailHeaderPanelSource).toContain("className={styles.detailHealthStatus}");
    expect(detailHeaderPanelSource).toContain("VTooltip");
    expect(detailHeaderPanelSource).toContain('<VTooltip content={healthTitle} width="wide">');
    expect(detailHeaderPanelSource).not.toContain('title={healthTitle}');
    expect(detailHeaderPanelSource).toContain('aria-label={`${healthLabel} · ${healthTitle}`}');
    expect(routeSource).not.toContain("<small>{issueSummary(selectedAgent.health, lang)}</small>");
    expect(coreConfigPanelSource).toContain("content={slotHint}");
    expect(coreConfigPanelSource).not.toContain("title={`${slot.required ? copy.requiredSlot : copy.optionalSlot} · ${slot.description}`}");
    expect(routeSource).not.toContain("<small>{slot.required ? copy.requiredSlot : copy.optionalSlot}</small>");
    expect(routeSource).toContain("const coreConfigToolPolicyTooltip = [");
    expect(coreConfigPanelSource).toContain("tooltip={toolPolicyTooltip}");
    expect(routeSource).not.toContain("<small>{toolPolicySourceLine}</small>");
    expect(agentCreateDialogSource).toContain('"3 步完成；当前对话会保留在背景中。"');
    expect(createPanelSource).toContain("content={copy.createAgentToolBundlesHint}");
    expect(createPanelSource).not.toContain("title={copy.createAgentHint}");
    expect(createPanelSource).not.toContain("title={copy.createAgentToolBundlesHint}");
    expect(createPanelSource).toContain("const bundleHint = [toolBundleMeta(bundle), bundle.description].filter(Boolean).join");
    expect(createPanelSource).toContain('label={`${bundle.label} ${lang === "zh" ? "说明" : "details"}`}');
    expect(createPanelSource).not.toContain("title={[bundle.label, toolBundleMeta(bundle), bundle.description]");
    expect(toolSummaryPanelSource).toContain("VContextualHint");
    expect(toolSummaryPanelSource).toContain('label={lang === "zh" ? "工具能力摘要说明" : "Tool capability summary details"}');
    expect(toolSummaryPanelSource).not.toContain('<section className={styles.configEditor} title={title}>');
    expect(toolGovernancePanelSource).toContain("VContextualHint");
    expect(toolGovernancePanelSource).toContain('label={lang === "zh" ? "工具治理说明" : "Tool governance details"}');
    expect(toolGovernancePanelSource).not.toContain('className={styles.configEditor}\n      title=');
    expect(returnBannerPanelSource).toContain("content={copy.returnBannerHint}");
    expect(avatarEditorPanelSource).toContain("content={copy.avatarEditorHint}");
    expect(routeSource).toContain("title: copy.routeHint");
    expect(detailHeaderPanelSource).toContain("className={styles.detailHeader}");
    expect(managementBriefPanelSource).toContain("content={copy.managementBriefHint}");
    expect(routeSource).toContain("title: copy.personaHint");
    expect(taskProfilePanelSource).toContain("content={copy.taskHint}");
    expect(healthMaintenancePanelSource).toContain("content={copy.maintenanceHint}");
    expect(debugResetPanelSource).toContain("content={copy.resetAgentHint}");
    expect(returnBannerPanelSource).not.toContain("title={copy.returnBannerHint}");
    expect(avatarEditorPanelSource).not.toContain("title={copy.avatarEditorHint}");
    expect(managementBriefPanelSource).not.toContain("title={copy.managementBriefHint}");
    expect(taskProfilePanelSource).not.toContain("title={copy.taskHint}");
    expect(healthMaintenancePanelSource).not.toContain("title={copy.maintenanceHint}");
    expect(debugResetPanelSource).not.toContain("title={copy.resetAgentHint}");
    expect(routeSource).not.toContain("<p>{copy.createAgentHint}</p>");
    expect(routeSource).not.toContain("<span>{copy.returnBannerHint}</span>");
    expect(routeSource).not.toContain("<p>{copy.avatarEditorHint}</p>");
    expect(routeSource).not.toContain("<p>{copy.routeHint}</p>");
    expect(routeSource).not.toContain("<p className={styles.contextLine}>{copy.personaHint}</p>");
    expect(routeSource).not.toContain("<p className={styles.contextLine}>{copy.taskHint}</p>");
    expect(routeSource).not.toContain("<p>{copy.maintenanceHint}</p>");
    expect(routeSource).not.toContain("<p>{copy.resetAgentHint}</p>");
    expect(stylesSource).not.toContain(".subtitle");
    expect(stylesSource).not.toContain(".healthCell small");
    expect(stylesSource).not.toContain(".detailHealthStatus small");
    expect(stylesSource).not.toContain(".createToolBundleOption small");
    expect(stylesSource).not.toContain(".llmSlotField span small");
  });

  it("explains Agent health states with reason and next action instead of a bare hint pill", () => {
    expect(agentStatusPresentationSource).toContain('return lang === "zh" ? "提醒" : "Notice"');
    expect(agentStatusPresentationSource).toContain("function issueSummary");
    expect(agentStatusPresentationSource).toContain("function issueNextStep");
    expect(agentStatusPresentationSource).toContain("function issuePanelLabel");
    expect(agentStatusPresentationSource).toContain("function issueDisplayTitle");
    expect(agentStatusPresentationSource).toContain("Inbox 有待处理消息");
    expect(agentStatusPresentationSource).toContain("这是 Inbox 待办提醒，不代表配置坏了");
    expect(routeSource).toContain("issueTone: issueTone(agent.health)");
    expect(detailHeaderPanelSource).toContain("styles.detailHealthStatus");
    expect(routeSource).toContain("copy.healthNextStep");
    expect(routeSource).toContain("copy.statusReminders");
    expect(routeSource).toContain("issueSummary(agent.health, lang)");
    expect(routeSource).toContain("issueNextStep(selectedAgent.health, lang)");
    expect(configPrimaryPanePanelSource).toContain("<AgentHealthMaintenancePanel");
    expect(healthMaintenancePanelSource).toContain("styles.issueList");
    expect(healthMaintenancePanelSource).toContain("function issueItemToneClass");
    expect(healthMaintenancePanelSource).toContain("issueItemToneClass(issue.severity)");
    expect(healthMaintenancePanelSource).toContain("issue.showInboxAction");
    expect(healthMaintenancePanelSource).toContain('from "./AgentHealthMaintenancePanel.styles"');
    expect(healthMaintenancePanelSource).not.toContain("AgentsRoute.styles");
    expect(healthMaintenanceStyles.issueList).toBeTruthy();
    expect(healthMaintenanceStyles.issueItem_warning).toBeTruthy();
    expect(styles.healthCell).toBeTruthy();
    expect(detailHeaderStyles.detailHealthStatus).toBeTruthy();
  });

  it("edits Agent persona profile from AgentDirectory without recommendation automation", () => {
    expect(routeSource).toContain("AgentPersonaDraft");
    expect(routeSource).toContain("personaProfileFromDraft");
    expect(routeSource).toContain("personaProfile: personaProfileFromDraft(payload.draft)");
    expect(routeSource).toContain("updatedAgentWorkspaceCache");
    expect(routeSource).toContain("setPersonaDraft(personaDraftFromAgent(agent))");
    expect(routeSource).toContain("draftSyncSourceRef.current = draftSyncSourceFromAgent(workspace, agent)");
    expect(configPrimaryPanePanelSource).toContain("<AgentPersonaProfilePanel");
    expect(routeSource).toContain("summary: personaProfileSummary(selectedAgent, lang)");
    expect(routeSource).toContain("draft: personaDraft");
    expect(routeSource).toContain("dirty: personaDirty");
    expect(routeSource).toContain("canSave: canSavePersona");
    expect(routeSource).toContain("pending: selectedAgentPersonaPending");
    expect(routeSource).toContain("onDraftChange: updatePersonaDraft");
    expect(routeSource).toContain("onSave: savePersonaProfile");
    expect(personaProfilePanelSource).toContain("copy.personaTitle");
    expect(personaProfilePanelSource).toContain("copy.gender");
    expect(personaProfilePanelSource).toContain("copy.age");
    expect(personaProfilePanelSource).toContain("copy.communicationStyle");
    expect(personaProfilePanelSource).toContain("copy.collaborationPreference");
    expect(personaProfilePanelSource).toContain("copy.identityNotes");
    expect(personaProfilePanelSource).toContain('from "./AgentPersonaProfilePanel.styles"');
    expect(personaProfilePanelSource).not.toContain("AgentsRoute.styles");
    expect(personaProfileStyles.configEditor).toBeTruthy();
    expect(personaProfileStyles.editorGrid).toBeTruthy();
    expect(personaProfileStyles.editorActions).toBeTruthy();
    expect(coreConfigPanelSource).toContain("styles.fieldWide");
    expect(coreConfigStyles.fieldWide).toBeTruthy();
    expect(routeSource).toContain("updatePersonaMutation");
    expect(routeSource).not.toContain("recommendAgents");
  });

  it("protects unsaved Agent drafts from workspace polling refreshes", () => {
    expect(routeSource).toContain("AgentDraftSyncSource");
    expect(routeSource).toContain("draftSyncSourceRef");
    expect(routeSource).toContain("draftSyncSourceFromAgent(workspace, selectedAgent)");
    expect(routeSource).toContain("const agentChanged = previousSource?.agentId !== nextSource.agentId");
    expect(routeSource).toContain("configDraftEqualsDraft(current, previousSource.config) ? nextSource.config : current");
    expect(routeSource).toContain("personaDraftEqualsDraft(current, previousSource.persona) ? nextSource.persona : current");
    expect(routeSource).toContain("taskDraftEqualsDraft(current, previousSource.task) ? nextSource.task : current");
    expect(routeSource).toContain("toolPolicyDraftEqualsDraft(current, previousSource.toolPolicy) ? nextSource.toolPolicy : current");
    expect(routeSource).toContain("memoryPolicyDraftEqualsDraft(current, previousSource.memoryPolicy) ? nextSource.memoryPolicy : current");
    expect(routeSource).toContain("delegationPolicyDraftEqualsDraft(current, previousSource.delegationPolicy) ? nextSource.delegationPolicy : current");
    expect(routeSource).toContain("supervisionPolicyDraftEqualsDraft(current, previousSource.supervisionPolicy) ? nextSource.supervisionPolicy : current");
    expect(routeSource).not.toContain("}, [selectedAgent?.agentId, workspace?.generatedAt]);");
  });

  it("edits Agent task profile from AgentDirectory without automatic routing", () => {
    expect(routeSource).toContain("AgentTaskDraft");
    expect(routeSource).toContain("taskProfileFromDraft");
    expect(routeSource).toContain("taskProfile: taskProfileFromDraft(payload.draft)");
    expect(configPrimaryPanePanelSource).toContain("<AgentTaskProfilePanel");
    expect(routeSource).toContain("summary: taskProfileSummary(selectedAgent, lang)");
    expect(routeSource).toContain("draft: taskDraft");
    expect(routeSource).toContain("dirty: taskDirty");
    expect(routeSource).toContain("canSave: canSaveTask");
    expect(routeSource).toContain("pending: selectedAgentTaskPending");
    expect(routeSource).toContain("onDraftChange: updateTaskDraft");
    expect(routeSource).toContain("onSave: saveTaskProfile");
    expect(taskProfilePanelSource).toContain("copy.taskTitle");
    expect(taskProfilePanelSource).toContain("copy.mission");
    expect(taskProfilePanelSource).toContain("copy.taskTypes");
    expect(taskProfilePanelSource).toContain("copy.responsibilities");
    expect(taskProfilePanelSource).toContain("copy.preferredTasks");
    expect(taskProfilePanelSource).toContain("copy.successCriteria");
    expect(taskProfilePanelSource).toContain("copy.handoffNotes");
    expect(taskProfilePanelSource).toContain('from "./AgentTaskProfilePanel.styles"');
    expect(taskProfilePanelSource).not.toContain("AgentsRoute.styles");
    expect(taskProfileStyles.configEditor).toBeTruthy();
    expect(taskProfileStyles.fieldWide).toBeTruthy();
    expect(taskProfileStyles.editorActions).toBeTruthy();
    expect(routeSource).toContain("updateTaskMutation");
    expect(routeSource).not.toContain("autoRouteAgent");
  });

  it("edits Agent mode membership from the same detail card", () => {
    expect(routeSource).toContain("AgentModeMembershipDraft");
    expect(routeSource).toContain("membershipDraftFromWorkspace");
    expect(routeSource).toContain("/mode-membership");
    expect(selectedDetailContentPanelSource).toContain("<AgentConfigReferencesPanePanel");
    expect(configReferencesPanePanelSource).toContain("<AgentModeMembershipPanel");
    expect(modeMembershipPanelSource).toContain('from "./AgentModeMembershipPanel.styles"');
    expect(modeMembershipPanelSource).not.toContain("AgentsRoute.styles");
    expect(routeSource).toContain("draft: membershipDraft");
    expect(routeSource).toContain("dirty: membershipDirty");
    expect(routeSource).toContain("canSave: canSaveMembership");
    expect(routeSource).toContain("pending: selectedAgentMembershipPending");
    expect(routeSource).toContain("onDraftChange: updateMembershipDraft");
    expect(routeSource).toContain("onSave: saveModeMembership");
    expect(modeMembershipPanelSource).toContain("chatDefault: value");
    expect(modeMembershipPanelSource).toContain("copy.researchPool");
    expect(modeMembershipPanelSource).toContain("copy.supervisedSlot");
    expect(modeMembershipPanelSource).toContain("copy.selfEvolutionSlot");
    expect(routeSource).toContain("chatWorkspaceCache.afterAgentWorkspaceChanged()");
    expect(modeMembershipPanelSource).toContain("styles.toggleGrid");
    expect(modeMembershipStyles.configEditor).toBeTruthy();
    expect(modeMembershipStyles.toggleGrid).toBeTruthy();
    expect(modeMembershipStyles.editorGrid).toBeTruthy();
  });

  it("shows Agent group room membership as read-only references", () => {
    expect(routeSource).toContain("copy.chatRoomMembership");
    expect(routeSource).toContain("只读引用");
    expect(routeSource).toContain("Read-only");
    expect(routeSource).toContain("selectedAgent.references.filter((reference) => reference.kind === \"chat_room\").length");
    expect(configReferencesPanePanelSource).toContain("AgentReferencesPanel");
    expect(referencesPanelSource).toContain('from "./AgentReferencesPanel.styles"');
    expect(referencesPanelSource).not.toContain("AgentsRoute.styles");
    expect(routeSource).not.toContain("className={styles.roomMembershipList}");
    expect(routeSource).not.toContain("className={styles.roomCheckField}");
    expect(referencesPanelStyles.roomMembershipList).toBeTruthy();
    expect(referencesPanelStyles.roomCheckField).toBeTruthy();
    expect(routeSource).toContain("compactProjectionRoute(room");
    expect(routeSource).toContain("`/chat?room=${encodeURIComponent(room.roomId)}`");
    expect(routeSource).toContain("打开群聊");
    expect(routeSource).toContain("群聊成员关系在对话页的群设置中维护；团队关联群聊由团队页同步。");
    expect(routeSource).not.toContain("AgentChatRoomMembershipDraft");
    expect(routeSource).not.toContain("chatRoomDraftFromWorkspace");
    expect(routeSource).not.toContain("updateChatRoomsMutation");
    expect(routeSource).not.toContain("chatWorkspaceCache.afterAgentChatRoomsChanged()");
    expect(routeSource).not.toContain("copy.saveChatRooms");
  });

  it("surfaces Team references as first-class Agent Center relationships", () => {
    expect(routeSource).toContain('team: "团队"');
    expect(routeSource).toContain('team: "Team"');
    expect(routeSource).not.toContain("summary?.teamCount");
    expect(routeSource).toContain("referenceRoute(reference)");
    expect(routeSource).toContain("reference.projectionEdit?.canonicalEditRoute || reference.sourceRef?.canonicalEditRoute");
    expect(routeSource).toContain("compactProjectionRoute(room");
    expect(routeSource).toContain('`/teams?team=${encodeURIComponent(reference.sourceId)}`');
    expect(routeSource).toContain("onOpenRoute: (route: string) => navigate(route)");
    expect(routeSource).not.toContain("className={styles.referenceList}");
    expect(referencesPanelStyles.referenceList).toBeTruthy();
    expect(referencesPanelStyles.referenceItem).toBeTruthy();
    expect(referencesPanelStyles.referenceStatusActive).toBeTruthy();
    expect(referencesPanelStyles.referenceStatusStale).toBeTruthy();
  });

  it("routes detailed Agent tool permissions to the Tools page", () => {
    expect(routeSource).toContain("agentCenterToolsRoute");
    expect(routeSource).toContain("const selectedAgentReturnRoute = selectedAgent?.agentId");
    expect(routeSource).toContain("const selectedAgentToolConfigRoute = useMemo(");
    expect(routeSource).toContain('returnLabel: "agents"');
    expect(routeSource).toContain("returnTo: selectedAgentReturnRoute");
    expect(toolSummaryPanelSource).toContain("copy.toolPolicyTitle");
    expect(routeSource).toContain("toolPolicySourceLine");
    expect(routeSource).toContain("toolPolicySource?.description");
    expect(selectedDetailContentPanelSource).toContain("<AgentConfigPolicyPanePanel");
    expect(configPolicyPanePanelSource).toContain("<AgentToolSummaryPanel");
    expect(routeSource).toContain("onConfigure: () => navigate(selectedAgentToolConfigRoute)");
    expect(toolSummaryPanelSource).toContain("工具能力已迁移到 Agent 管理的工具页集中配置");
    expect(toolSummaryPanelSource).toContain("配置工具能力");
    expect(toolSummaryPanelSource).toContain("onPress={onConfigure}");
    expect(toolGovernancePanelSource).toContain("去工具页配置");
    expect(toolSummaryPanelSource).toContain("copy.toolCategoryCount");
    expect(toolSummaryPanelSource).toContain('from "./AgentToolSummaryPanel.styles"');
    expect(toolSummaryPanelSource).not.toContain("AgentsRoute.styles");
    expect(toolSummaryStyles.policySummaryGrid).toBeTruthy();
    expect(toolSummaryStyles.editorActions).toBeTruthy();
  });

  it("routes Agent prompt configuration to the Prompt Center", () => {
    expect(routeSource).toContain("agentCenterPromptsRoute");
    expect(routeSource).toContain("const selectedAgentPromptConfigRoute = useMemo(");
    expect(routeSource).toContain("templateId: configDraft.promptTemplateId || selectedAgent.promptTemplateId");
    expect(routeSource).toContain('focus: "editor"');
    expect(routeSource).toContain('returnLabel: "agents"');
    expect(routeSource).toContain("returnTo: selectedAgentReturnRoute");
    expect(coreConfigPanelSource).toContain("styles.promptConfigRow");
    expect(routeSource).toContain("onOpenPromptConfig: () => navigate(selectedAgentPromptConfigRoute)");
    expect(coreConfigPanelSource).toContain("配置提示词");
  });

  it("adds cross-center links for model, context, and memory configuration", () => {
    expect(routeSource).toContain("agentCenterModelsRoute");
    expect(routeSource).toContain("agentCenterMemoryRoute");
    expect(routeSource).toContain("const selectedAgentModelConfigRoute = useMemo(");
    expect(routeSource).toContain("const selectedAgentContextConfigRoute = useMemo(");
    expect(routeSource).toContain("const selectedAgentMemoryConfigRoute = useMemo(");
    expect(routeSource).toContain('section: "models-profiles"');
    expect(routeSource).toContain('section: "runtime-context"');
    expect(routeSource).toContain('view: "agents"');
    expect(routeSource).toContain("returnTo: selectedAgentReturnRoute");
    expect(coreConfigPanelSource).toContain("styles.configDeepLinkRow");
    expect(routeSource).toContain("onOpenModelConfig: () => navigate(selectedAgentModelConfigRoute)");
    expect(coreConfigPanelSource).toContain("onPress={onOpenModelConfig}");
    expect(routeSource).toContain("onOpenContextConfig: () => navigate(selectedAgentContextConfigRoute)");
    expect(routeSource).toContain("onOpenMemoryPage: () => navigate(selectedAgentMemoryConfigRoute)");
    expect(coreConfigPanelSource).toContain("去模型库配置");
    expect(contextCompressionPanelSource).toContain("去上下文配置");
    expect(memoryPolicyPanelSource).toContain("去记忆页配置");
    expect(styles.configDeepLinkRow).toBeTruthy();
  });

  it("surfaces advisor tool-governance requests without bypassing ToolPolicy", () => {
    expect(routeSource).toContain("AgentToolGovernanceRequest");
    expect(routeSource).toContain("toolGovernanceDraftFromAgent");
    expect(routeSource).toContain("toolPolicyDeltaFromDraft");
    expect(routeSource).toContain("/tool-governance-requests");
    expect(configPrimaryPanePanelSource).toContain("<AgentToolGovernancePanel");
    expect(routeSource).toContain("requests: selectedAgent.toolGovernanceRequests ?? []");
    expect(routeSource).toContain("pendingRequestId:");
    expect(routeSource).toContain("onResolve: resolveToolGovernanceRequest");
    expect(routeSource).toContain("onConfigure: () => navigate(selectedAgentToolConfigRoute)");
    expect(toolGovernancePanelSource).toContain("copy.toolGovernanceTitle");
    expect(toolGovernancePanelSource).toContain("copy.toolGovernancePending");
    expect(toolGovernancePanelSource).toContain("copy.toolGovernanceApprove");
    expect(toolGovernancePanelSource).toContain("copy.toolGovernanceReject");
    expect(toolGovernancePanelSource).toContain('from "./AgentToolGovernancePanel.styles"');
    expect(toolGovernancePanelSource).not.toContain("AgentsRoute.styles");
    expect(routeSource).toContain("createToolGovernanceMutation");
    expect(routeSource).toContain("resolveToolGovernanceMutation");
    expect(toolGovernancePanelSource).toContain("styles.toolGovernanceList");
    expect(toolGovernancePanelSource).toContain("styles.toolGovernanceItem");
    expect(toolGovernanceStyles.toolGovernanceList).toBeTruthy();
    expect(toolGovernanceStyles.toolGovernanceItem).toBeTruthy();
    expect(toolGovernanceStyles.governanceActions).toBeTruthy();
  });

  it("edits Agent memory policy from the same detail card", () => {
    expect(routeSource).toContain("AgentMemoryPolicyDraft");
    expect(configPolicyPanePanelSource).toContain("<AgentMemoryPolicyPanel");
    expect(routeSource).toContain("draft: memoryPolicyDraft");
    expect(routeSource).toContain("memoryGroupOptions,");
    expect(routeSource).toContain("onDraftChange: updateMemoryDraftField");
    expect(routeSource).toContain("onAddMemoryGroup: addMemoryGroup");
    expect(routeSource).toContain("onAddKnowledgeBaseId: addKnowledgeBaseId");
    expect(routeSource).toContain("onSave: saveMemoryPolicy");
    expect(memoryPolicyPanelSource).toContain("copy.memoryPolicyTitle");
    expect(routeSource).toContain("memoryPolicy: {");
    expect(routeSource).toContain("readSharedGroups: sortedIds(payload.draft.readSharedGroups)");
    expect(routeSource).toContain("writeSharedGroups: sortedIds(payload.draft.writeSharedGroups)");
    expect(routeSource).toContain("readKnowledgeBaseIds: sortedIds(payload.draft.readKnowledgeBaseIds)");
    expect(routeSource).toContain("proposeKnowledgeBaseIds: sortedIds(payload.draft.proposeKnowledgeBaseIds)");
    expect(routeSource).toContain("reviewKnowledgeBaseIds: sortedIds(payload.draft.reviewKnowledgeBaseIds)");
    expect(routeSource).toContain("rateKnowledgeBaseIds: sortedIds(payload.draft.rateKnowledgeBaseIds)");
    expect(memoryPolicyPanelSource).toContain("copy.readKnowledgeBaseIds");
    expect(memoryPolicyPanelSource).toContain("copy.proposeKnowledgeBaseIds");
    expect(memoryPolicyPanelSource).toContain("copy.reviewKnowledgeBaseIds");
    expect(memoryPolicyPanelSource).toContain("copy.rateKnowledgeBaseIds");
    expect(memoryPolicyPanelSource).toContain('from "./AgentMemoryPolicyPanel.styles"');
    expect(memoryPolicyPanelSource).not.toContain("AgentsRoute.styles");
    expect(memoryPolicyPanelSource).toContain("styles.memoryPolicyGrid");
    expect(memoryPolicyPanelSource).toContain("styles.tagList");
    expect(memoryPolicyPanelSource).toContain("styles.inlineAdd");
    expect(memoryPolicyStyles.memoryPolicyGrid).toBeTruthy();
    expect(memoryPolicyStyles.tagList).toBeTruthy();
    expect(memoryPolicyStyles.inlineAdd).toBeTruthy();
  });

  it("organizes the Agent card into switchable operational panes with run history", () => {
    expect(routeSource).toContain("AgentConfigPaneId");
    expect(routeSource).toContain('type AgentConfigPaneId = "overview" | "effective" | "relations" | "config" | "changes" | "activity"');
    expect(routeSource).toContain("agentConfigPanes(copy, selectedAgent)");
    expect(routeSource).toContain("AgentManagementBrief");
    expect(routeSource).toContain("buildAgentManagementBrief(selectedAgent, copy, lang)");
    expect(selectedDetailContentPanelSource).toContain("AgentManagementBriefPanel");
    expect(selectedDetailContentPanelSource).toContain("AgentOverviewPanel");
    expect(selectedDetailContentPanelSource).toContain("AgentEffectiveConfigurationPanel");
    expect(selectedDetailContentPanelSource).toContain('activePane === "effective"');
    expect(selectedDetailContentPanelSource).toContain("AgentTeamRelationsPanel");
    expect(selectedDetailContentPanelSource).toContain('activePane === "relations"');
    expect(selectedDetailContentPanelSource).toContain("AgentConfigChangeHistoryPanel");
    expect(selectedDetailContentPanelSource).toContain('activePane === "changes"');
    expect(routeSource).toContain("config-changes");
    expect(routeSource).toContain("copy.managementBriefTitle");
    expect(routeSource).toContain("copy.nextActionsTitle");
    expect(routeSource).not.toContain("className={styles.managementBriefPanel}");
    expect(routeSource).not.toContain("className={styles.factGrid}");
    expect(routeSource).not.toContain("className={styles.boundarySummaryGrid}");
    expect(routeSource).not.toContain("className={styles.policyGrid}");
    expect(managementBriefPanelSource).toContain('from "./AgentManagementBriefPanel.styles"');
    expect(managementBriefPanelSource).not.toContain("AgentsRoute.styles");
    expect(managementBriefPanelSource).toContain("styles.managementBriefPanel");
    expect(managementBriefPanelSource).toContain("styles.nextActionList");
    expect(managementBriefPanelSource).toContain("styles.nextActionButton");
    expect(managementBriefPanelSource).not.toContain('className="w-full"');
    expect(detailHeaderPanelSource).toContain("styles.detailTabs");
    expect(selectedDetailContentPanelSource).toContain("activePane === \"overview\"");
    expect(selectedDetailContentPanelSource).toContain("activePane === \"config\"");
    expect(routeSource).not.toContain("activePane === \"policies\"");
    expect(routeSource).not.toContain("activePane === \"membership\"");
    expect(toolSummaryPanelSource).toContain("copy.toolPolicyTitle");
    expect(memoryPolicyPanelSource).toContain("copy.memoryPolicyTitle");
    expect(modeMembershipPanelSource).toContain("copy.membershipTitle");
    expect(selectedDetailContentPanelSource).toContain("activePane === \"activity\"");
    expect(routeSource).toContain("fetchJson<AgentRunHistory>");
    expect(routeSource).toContain("queryKeys.agentRuns");
    expect(routeSource).not.toContain("summary?.runningAgentCount");
    expect(routeSource).not.toContain("summary?.blockedAgentCount");
    expect(routeSource).toContain("inspectorOpen");
    expect(routeSource).toContain("AgentEffectiveConfigurationInspectorPanel");
    expect(routeSource).toContain("expectedUpdatedAt: payload.agent.updatedAt");
    expect(runtimeFocusPanelSource).toContain("styles.runtimePill");
    expect(runtimeFocusPanelSource).toContain("styles.runtimeFocusPanel");
    expect(activityHistoryPanelSource).toContain("styles.runHistoryList");
    expect(managementBriefStyles.managementBriefPanel).toBeTruthy();
    expect(managementBriefStyles.managementChecklist).toBeTruthy();
    expect(managementBriefStyles.nextActionList).toBeTruthy();
    expect(managementBriefStyles.managementChecklist).toContain("[flex-wrap:wrap]");
    expect(managementBriefStyles.managementChecklistDone).not.toContain("w-full");
    expect(managementBriefStyles.nextActionButton).toContain("w-fit");
    expect(managementBriefStyles.nextActionButton.split(/\s+/)).not.toContain("w-full");
    expect(overviewStyles.boundarySummaryGrid).toBeTruthy();
    expect(detailHeaderStyles.detailTabs).toBeTruthy();
    expect(selectedDetailContentStyles.selectedDetailFrame).toContain("w-full");
    expect(selectedDetailContentStyles.selectedDetailFrame).not.toContain("max-w-[1280px]");
    expect(selectedDetailContentStyles.overviewLayout).toContain("[overflow:auto]");
    expect(selectedDetailContentStyles.overviewAside).toContain("hidden");
    expect(workspaceLayoutPanelSource).toContain("AgentInspectorRailPanel");
    expect(workspaceLayoutPanelSource).toContain("inspectorRail");
    expect(overviewStyles.factGrid).toContain("min-[1540px]:[grid-template-columns:repeat(3,_minmax(0,_1fr))]");
    expect(overviewStyles.policyGrid).toContain("min-[1540px]:[grid-template-columns:repeat(4,_minmax(0,_1fr))]");
    expect(selectedDetailContentPanelSource).toContain("styles.overviewMain");
    expect(selectedDetailContentPanelSource).toContain("styles.overviewAside");
    expect(effectiveConfigurationPanelSource).toContain("当前有效配置");
    expect(effectiveConfigurationPanelSource).toContain("inheritanceChain");
    expect(effectiveConfigurationStyles.configurationTable).toContain("max-[860px]");
  });

  it("includes work-session Agent setup copy for model instructions and workspace boundaries", () => {
    expect(agentCreateContractSource).toContain("function isWorkSessionCreateDraft");
    expect(agentCreateDialogSource).toContain("isWorkSession={isWorkSessionCreateDraft(draft)}");
    expect(agentCreateContractSource).toContain("const workSession = isWorkSessionCreateDraft(draft)");
    expect(routeSource).toContain("const sectionOrder = [\"status\", \"boundary\", \"team_index\"] as const");
    expect(routeSource).toContain("const sectionOrder = [\"source_scope\", \"mode\", \"reference\"] as const");
    expect(routeSource).toContain("copy.managementModelPrompt");
    expect(routeSource).toContain("copy.managementWorkspace");
    expect(routeSource).toContain("copy.nextSetupModelPrompt");
    expect(routeSource).toContain("copy.nextSetupWorkspace");
    expect(routeSource).toContain("Model / instructions");
    expect(routeSource).toContain("Check workspace boundary");
    expect(routeSource).toContain("配置模型与项目指令");
    expect(routeSource).toContain("检查工作区边界");
    expect(routeSource).toContain("Session entry Agents");
    expect(routeSource).toContain("Team / research role Agents");
    expect(routeSource).toContain("会话入口 Agent");
    expect(routeSource).toContain("团队/科研角色 Agent");
    expect(routeSource).toContain("function buildVisibleAgentColumns");
    expect(routeSource).toContain("teamIndexGroups: AgentTeamIndexGroup[]");
    expect(routeSource).toContain("group.section === \"team_index\"");
    expect(routeSource).toContain("id: `team_agents:${group.id}`");
    expect(routeSource).toContain("unassignedNonSessionAgents");
    expect(routeSource).toContain("copy.nonSessionAgentColumn");
    expect(routeSource).toContain("nonSessionAgents = agents.filter((agent) => !isWorkSessionAgent(agent))");
    expect(routeSource).toContain("buildVisibleAgentColumns(visibleAgents, copy, teamIndexGroups)");
    expect(listStatePanelSource).toContain("<AgentDenseList");
    expect(denseListSource).toContain('data-vui-product="agent-dense-list"');
    expect(routeSource).toContain("非会话 Agent");
    expect(routeSource).toContain("Non-session Agents");
  });

  it("keeps persona, task, and membership configuration out of work-session Agents", () => {
    expect(routeSource).toContain("selectedAgentRequiresPersona");
    expect(routeSource).toContain("selectedAgentRequiresTask");
    expect(routeSource).toContain("selectedAgentRequiresTeamMembership");
    expect(routeSource).toContain("personaProfile: selectedAgentRequiresPersona ? {");
    expect(routeSource).toContain("taskProfile: selectedAgentRequiresTask ? {");
    expect(routeSource).toContain("modeMembership: selectedAgentRequiresTeamMembership ? {");
    expect(agentCreateDialogSource).toContain("isWorkSession={isWorkSessionCreateDraft(draft)}");
    expect(createPanelSource).toContain("{!isWorkSession ? (");
    expect(agentCreateContractSource).toContain("const roleKey = workSession ? \"\" : draft.roleKey.trim()");
    expect(agentCreateContractSource).toContain("const personaProfile = workSession");
    expect(agentCreateContractSource).toContain("const taskProfile = workSession");
  });

  it("adds task-oriented Agent management filters for configuration gaps", () => {
    expect(routeSource).toContain("buildManagementFilterGroups");
    expect(routeSource).toContain("managementFilterMatches");
    expect(routeSource).toContain("activeFilter.startsWith(\"setup:\")");
    expect(routeSource).toContain("copy.filterSections.management");
    expect(routeSource).toContain("copy.managementFilterMissingPersona");
    expect(routeSource).toContain("copy.managementFilterMissingTask");
    expect(routeSource).toContain("copy.managementFilterMissingTools");
    expect(routeSource).toContain("copy.managementFilterNoTeam");
    expect(routeSource).toContain("copy.managementFilterPendingInbox");
    expect(routeSource).toContain("copy.managementFilterMaintenance");
  });

  it("surfaces pending Agent inbox messages from the activity pane", () => {
    expect(routeSource).toContain("AgentInboxMessage");
    expect(routeSource).toContain("queryKeys.agentMessages");
    expect(routeSource).toContain("/messages?status=pending&limit=8");
    expect(routeSource).toContain("/consume");
    expect(routeSource).toContain("consumeMessageMutation");
    expect(routeSource).toContain("consumeAllMessagesMutation");
    expect(routeSource).toContain("/messages/consume-all");
    expect(routeSource).toContain("copy.handleInboxNow");
    expect(routeSource).toContain("copy.consumeAllMessages");
    expect(routeSource).toContain("copy.inboxTitle");
    expect(routeSource).toContain("const selectedAgentInboxPendingCount = selectedAgent?.agentInboxPendingCount ?? agentMessagesQuery.data?.length ?? 0");
    expect(selectedDetailContentPanelSource).toContain("AgentActivityPanePanel");
    expect(activityPanePanelSource).toContain("AgentActivityHistoryPanel");
    expect(routeSource).toContain("showInboxAction: issue.code === \"pending_inbox_messages\"");
    expect(healthMaintenancePanelSource).toContain("copy.handleInboxNow");
    expect(routeSource).not.toContain("<h3>{copy.inboxTitle}: {selectedAgentInboxPendingCount}</h3>");
    expect(activityHistoryPanelSource).toContain("<h3>{copy.inboxTitle}: {inboxPendingCount}</h3>");
    expect(activityHistoryPanelSource).toContain("styles.inboxMessageList");
    expect(activityHistoryPanelSource).toContain("styles.inboxMessageItem");
    expect(activityHistoryPanelSource).toContain('from "./AgentActivityHistoryPanel.styles"');
    expect(activityHistoryPanelSource).not.toContain("AgentsRoute.styles");
    expect(activityHistoryStyles.inboxMessageList).toBeTruthy();
    expect(activityHistoryStyles.inboxMessageItemFocused).toBeTruthy();
  });

  it("summarizes runs, inbox messages, and context events in one activity timeline", () => {
    expect(routeSource).toContain("AgentActivityTimelineItem");
    expect(routeSource).toContain("buildActivityTimeline");
    expect(routeSource).toContain("activityTimeline");
    expect(activityPanePanelSource).toContain("AgentRuntimeFocusPanel");
    expect(routeSource).toContain("copy.activityTimeline");
    expect(routeSource).toContain("copy.runtimeFocus");
    expect(routeSource).toContain("copy.runtimeNextStep");
    expect(routeSource).toContain("copy.runtimeEvidence");
    expect(routeSource).not.toContain("className={styles.runtimeFocusPanel}");
    expect(runtimeFocusPanelSource).toContain("styles.runtimeFocusPanel");
    expect(runtimeFocusPanelSource).toContain("styles.runtimeNextStep");
    expect(runtimeFocusPanelSource).toContain("styles.runtimeEvidenceHint");
    expect(runtimeFocusPanelSource).toContain('from "./AgentRuntimeFocusPanel.styles"');
    expect(runtimeFocusPanelSource).not.toContain("AgentsRoute.styles");
    expect(runtimeFocusStyles.runtimeEvidenceHint).toBeTruthy();
    expect(runtimeFocusStyles.runtime_running).toBeTruthy();
    expect(routeSource).toContain("RuntimeFocusEvidenceResult");
    expect(routeSource).toContain("findRuntimeFocusEvidence");
    expect(routeSource).toContain("runtimeFocusEvidence");
    expect(routeSource).toContain("runtimeFocusEvidence.match?.runtimeSceneId");
    expect(routeSource).toContain("selectedAgent.runtimeStatus?.runId");
    expect(routeSource).toContain("selectedAgent?.runtimeStatus?.sessionId");
    expect(routeSource).toContain("runtimeEvidenceReasonLabel");
    expect(routeSource).toContain("openAgentLogs(runtimeFocusEvidence.match)");
    expect(routeSource).toContain("openAgentSession");
    expect(routeSource).toContain("openAgentLogs");
    expect(routeSource).toContain("focusInboxMessage");
    expect(routeSource).toContain("/chat?session=");
    expect(routeSource).toContain('root: "runtime_scenes"');
    expect(routeSource).toContain("scene: evidence.runtimeSceneId");
    expect(routeSource).toContain("navigate(\"/logs\")");
    expect(activityHistoryPanelSource).toContain("styles.activityTimelineList");
    expect(activityHistoryPanelSource).toContain("styles.activityTimelineItem");
    expect(activityHistoryPanelSource).toContain("styles.timelineActions");
    expect(activityHistoryPanelSource).toContain("styles.runHistoryList");
    expect(activityHistoryPanelSource).toContain("styles.inboxMessageItemFocused");
    expect(activityHistoryPanelSource).toContain("activityTimelineItem_${item.kind}");
  });

  it("keeps a compact operational preview in the overview while Activity owns live polling", () => {
    expect(routeSource).toContain('activePane === "overview" || activePane === "activity"');
    expect(routeSource).toContain('refetchInterval: activePane === "activity" ? resolvePollingInterval(pageVisible, 12_000) : false');
    expect(routeSource).toContain('refetchInterval: activePane === "activity" ? resolvePollingInterval(pageVisible, 20_000) : false');
    expect(routeSource).toContain("overviewOperations");
    expect(selectedDetailContentPanelSource).toContain('from "./AgentOverviewOperationsPanel"');
    expect(selectedDetailContentPanelSource).toContain("<AgentOverviewOperationsPanel");
    expect(selectedDetailContentPanelSource).toContain('from "./AgentOverviewResourcesPanel"');
    expect(selectedDetailContentPanelSource).toContain("<AgentOverviewResourcesPanel");
    expect(overviewOperationsPanelSource).toContain("copy.noActivity");
    expect(overviewOperationsPanelSource).toContain('role="alert"');
    expect(overviewOperationsStyles.state).toContain("min-h-[132px]");
    expect(overviewResourcesPanelSource).toContain("resources.slice(0, 4)");
    expect(overviewResourcesStyles.item).toBeTruthy();
  });

  it("edits Agent runtime delegation and supervision policies from the activity pane", () => {
    expect(routeSource).toContain("AgentDelegationPolicyDraft");
    expect(routeSource).toContain("AgentSupervisionPolicyDraft");
    expect(routeSource).toContain("delegationPolicy: {");
    expect(routeSource).toContain("supervisionPolicy: {");
    expect(routeSource).toContain("copy.delegationPolicyTitle");
    expect(routeSource).toContain("copy.supervisionPolicyTitle");
    expect(routeSource).toContain("copy.saveRuntimePolicy");
    expect(routeSource).toContain("updateRuntimePolicyMutation");
    expect(activityPanePanelSource).toContain("AgentRuntimePolicyPanel");
    expect(runtimePolicyPanelSource).toContain('from "./AgentRuntimePolicyPanel.styles"');
    expect(runtimePolicyPanelSource).not.toContain("AgentsRoute.styles");
    expect(routeSource).not.toContain("className={styles.runtimePolicyGrid}");
    expect(routeSource).not.toContain("className={styles.contextModeGrid}");
    expect(runtimePolicyStyles.runtimePolicyGrid).toBeTruthy();
    expect(runtimePolicyStyles.contextModeGrid).toBeTruthy();
    expect(runtimePolicyStyles.editorActions).toBeTruthy();
  });

  it("creates Agents through the shared dialog and safely archives them", () => {
    expect(routeSource).toContain("<AgentCreateWizardDialog");
    expect(agentCreateDialogSource).toContain('fetchJson<AgentConfigWorkspaceAgent>("/api/agents"');
    expect(agentCreateDialogSource).toContain('method: "POST"');
    expect(agentCreateDialogSource).toContain("createMutation");
    expect(routeSource).toContain("copy.createAgent");
    expect(agentCreateDialogSource).toContain("<AgentCreatePanel");
    expect(agentCreateDialogSource).toContain("onCreate={() => createMutation.mutate(draft)}");
    expect(createPanelSource).toContain("styles.createAgentPanel");
    expect(createPanelSource).toContain("styles.createAgentGrid");
    expect(createPanelStyles.createAgentPanel).toBeTruthy();
    expect(createPanelStyles.createAgentGrid).toBeTruthy();
    expect(routeSource).toContain("archiveAgentMutation");
    expect(routeSource).toContain("method: \"DELETE\"");
    expect(routeSource).not.toContain("window.confirm");
    expect(archiveZonePanelSource).toContain("copy.archiveAgent");
    expect(routeSource).toContain("archivedWorkspaceCache");
    expect(routeSource).toContain("purgedWorkspaceCache");
    expect(routeSource).toContain("queryClient.setQueryData<AgentConfigWorkspace | undefined>");
    expect(routeSource).toContain("purgeAgentMutation");
    expect(routeSource).toContain("/purge");
    expect(archiveZonePanelSource).toContain("copy.purgeAgent");
    expect(routeSource).toContain("copy.maintenanceTitle");
    expect(healthMaintenancePanelSource).toContain("styles.maintenanceIntro");
    expect(routeSource).toContain("selectedAgent.status === \"archived\"");
    expect(configPrimaryPanePanelSource).toContain("<AgentArchiveZonePanel");
    expect(archiveZonePanelSource).toContain("styles.dangerZone");
    expect(archiveZonePanelSource).toContain('variant="danger"');
    expect(healthMaintenanceStyles.maintenanceIntro).toBeTruthy();
  });

  it("optimistically removes single-Agent archive and purge actions before backend confirmation", () => {
    expect(routeSource).toContain("function optimisticArchivedAgent(agent: AgentConfigWorkspaceAgent)");
    expect(routeSource).toContain("queryClient.cancelQueries({ queryKey: queryKeys.agentConfigWorkspace() })");
    expect(routeSource).toContain("const previousSelectedAgentId = selectedAgentId");
    expect(routeSource).toContain("const previousActivePane = activePane");
    expect(routeSource).toContain("archivedWorkspaceCache(current, optimisticArchivedAgent(optimisticAgent))");
    expect(routeSource).toContain("purgedWorkspaceCache(current, payload.agentId)");
    expect(routeSource).toContain("return { previousWorkspace, previousSelectedAgentId, previousActivePane }");
    expect(routeSource).toContain("queryClient.setQueryData(queryKeys.agentConfigWorkspace(), context.previousWorkspace)");
    expect(routeSource).toContain("setSelectedAgentId(context?.previousSelectedAgentId ?? \"\")");
    expect(routeSource).toContain("setActivePane(context?.previousActivePane ?? \"overview\")");
  });

  it("offers a governed per-Agent debug reset without archive or membership cleanup", () => {
    expect(routeSource).toContain("AgentResetOptions");
    expect(routeSource).toContain("resetAgentMutation");
    expect(routeSource).toContain("resettingAgentIds");
    expect(routeSource).toContain("selectedAgentResetPending");
    expect(routeSource).toContain("new Set(current)");
    expect(routeSource).toContain("next.add(payload.agentId)");
    expect(routeSource).toContain("next.delete(payload.agentId)");
    expect(routeSource).toContain("/reset");
    expect(routeSource).toContain("method: \"POST\"");
    expect(configPrimaryPanePanelSource).toContain("<AgentDebugResetPanel");
    expect(routeSource).toContain("options: resetOptions");
    expect(routeSource).toContain("canReset: canResetAgent");
    expect(routeSource).toContain("pending: selectedAgentResetPending");
    expect(routeSource).toContain("onOptionChange: updateResetOption");
    expect(routeSource).toContain("onReset: resetSelectedAgent");
    expect(routeSource).toContain("agentName: agentLabel(selectedAgent)");
    expect(routeSource).not.toContain("window.confirm(copy.resetAgentConfirm");
    expect(debugResetPanelSource).toContain("VConfirmDialog");
    expect(debugResetPanelSource).toContain("setConfirmOpen(true)");
    expect(debugResetPanelSource).toContain("copy.resetAgentConfirm");
    expect(debugResetPanelSource).toContain("copy.resetAgent");
    expect(debugResetPanelSource).toContain("resetClearRuntimeState");
    expect(debugResetPanelSource).toContain("resetClearRuntimeStateHint");
    expect(debugResetPanelSource).toContain("resetDirectSession");
    expect(debugResetPanelSource).toContain("resetDirectSessionHint");
    expect(debugResetPanelSource).toContain("resetPersonaProfile");
    expect(debugResetPanelSource).toContain("resetPersonaProfileHint");
    expect(debugResetPanelSource).toContain("resetTaskProfile");
    expect(debugResetPanelSource).toContain("resetTaskProfileHint");
    expect(debugResetPanelSource).toContain("resetToolPolicy");
    expect(debugResetPanelSource).toContain("resetToolPolicyHint");
    expect(debugResetPanelSource).toContain("resetMemoryPolicy");
    expect(debugResetPanelSource).toContain("resetMemoryPolicyHint");
    expect(debugResetPanelSource).toContain("resetRuntimePolicy");
    expect(debugResetPanelSource).toContain("resetRuntimePolicyHint");
    expect(debugResetPanelSource).toContain("styles.resetOptionField");
    expect(debugResetPanelSource).toContain('from "./AgentDebugResetPanel.styles"');
    expect(debugResetPanelSource).not.toContain("AgentsRoute.styles");
    expect(routeSource).toContain("queryKeys.agentRuntimeEvidence(agent.agentId)");
    expect(routeSource).toContain("selectedAgent.status !== \"archived\"");
    expect(debugResetPanelSource).toContain("isDisabled={!canReset || pending}");
    expect(debugResetPanelSource).toContain("pending ? copy.resettingAgent : copy.resetAgent");
    expect(routeSource).not.toContain("!canResetAgent || resetAgentMutation.isPending");
    expect(debugResetStyles.resetZone).toBeTruthy();
    expect(debugResetStyles.resetOptionGrid).toBeTruthy();
    expect(debugResetStyles.resetOptionField).toBeTruthy();
  });

  it("reconciles stale direct-session caches after resetting an Agent session", () => {
    expect(routeSource).toContain("type AgentResetSummary");
    expect(routeSource).toContain("function reconcileResetDirectSession");
    expect(routeSource).toContain("previousDirectSessionId");
    expect(routeSource).toContain("replacementDirectSessionId");
    expect(routeSource).toContain("reconcileResetDirectSession(result.resetSummary)");
    expect(routeSource).toContain("queryClient.removeQueries({ queryKey: queryKeys.session(previousDirectSessionId), exact: true })");
    expect(routeSource).toContain("chatWorkspaceCache.afterChatWorkspaceReset()");
  });

  it("keeps per-Agent avatar, governance, and inbox actions scoped to their target object", () => {
    expect(routeSource).toContain("selectedAgentAvatarUpdatePending");
    expect(routeSource).toContain("selectedAgentAvatarUploadPending");
    expect(routeSource).toContain("selectedAgentConsumeAllPending");
    expect(routeSource).toContain("updateAvatarMutation.variables?.agentId === selectedAgent?.agentId");
    expect(routeSource).toContain("uploadAvatarMutation.variables?.agentId === selectedAgent?.agentId");
    expect(routeSource).toContain("(current) => updatedAgentWorkspaceCache(current, agent)");
    expect(routeSource).toContain("(current) => updatedAgentWorkspaceCache(current, result.agent)");
    expect(routeSource).toContain("consumeAllMessagesMutation.variables?.agentId === selectedAgent?.agentId");
    expect(routeSource).toContain("resolveToolGovernanceMutation.variables?.requestId === request.requestId");
    expect(routeSource).toContain("consumeMessageMutation.variables?.messageId === messageId");
    expect(routeSource).toContain("queryKeys.agentMessages(variables.agentId, \"pending\")");
    expect(routeSource).not.toContain("if (selectedAgent?.agentId) {\n        void queryClient.invalidateQueries({ queryKey: queryKeys.agentMessages(selectedAgent.agentId, \"pending\") });");
  });

  it("keeps archived Agents out of non-archived filter lists immediately", () => {
    expect(routeSource).toContain('if (activeFilter === "archived")');
    expect(routeSource).toContain('} else if (archived) {');
    expect(routeSource).toContain("fallbackAgents.filter((agent) => agent.status !== \"archived\")");
    expect(routeSource).toContain("selectedAgentFromList(visibleAgents, selectedAgentId, workspace?.agents ?? [], activeFilter)");
  });

  it("separates protected core Agents from the destructive archive zone", () => {
    expect(archiveZonePanelSource).toContain("copy.archiveProtection");
    expect(archiveZonePanelSource).toContain("copy.archiveProtectionHint");
    expect(archiveZonePanelSource).toContain("isProtected ? styles.protectedZone : styles.dangerZone");
    expect(archiveZonePanelSource).toContain("isProtected ? <ShieldCheck");
    expect(routeSource).not.toContain("summary?.archivedAgentCount");
    expect(archiveZoneStyles.protectedZone).toBeTruthy();
  });

  it("keeps the desktop workspace as a directory and detail split", () => {
    expect(routeSource).toContain("<AgentWorkspaceLayoutPanel");
    expect(routeSource).not.toContain("styles.workspace");
    expect(workspaceLayoutPanelSource).toContain("styles.workspace");
    expect(denseListSource).toContain("grid-cols-[minmax(0,1fr)_auto]");
    expect(denseListSource).toContain('data-vui="agent-row"');
    expect(detailWorkspacePanelSource).toContain("styles.detailPanel");
    expect(workspaceLayoutStyles.workspace).toBeTruthy();
    expect(workspaceLayoutPanelSource).toContain("styles.directory");
    expect(workspaceLayoutStyles.workspace).toContain("flex h-full");
    expect(workspaceLayoutStyles.workspace).toContain("overflow-hidden");
    expect(workspaceLayoutStyles.directory).toContain("grid-rows-[auto_minmax(0,1fr)]");
    expect(workspaceLayoutPanelSource).toContain("PaneResizeHandle");
    expect(workspaceLayoutPanelSource).toContain("usePersistedPaneResize");
    expect(workspaceLayoutPanelSource).toContain("data-agent-workspace=\"resizable\"");
    expect(routeSource).toContain('data-vui-recipe="agents-management-workbench"');
    expect(workspaceLayoutPanelSource).toContain('data-vui-recipe="agents-workspace-shell"');
    expect(workspaceLayoutPanelSource).toContain('data-vui-region="agents-directory"');
    expect(workspaceLayoutPanelSource).toContain('data-vui-region="agents-detail"');
    expect(workspaceLayoutPanelSource).toContain('label="调整目录栏宽度"');
    expect(workspaceLayoutStyles.workspace).toContain("max-[860px]:flex-col");
    expect(workspaceLayoutStyles.inspector).toContain("max-[1180px]:absolute");
    expect(workspaceLayoutStyles.inspectorBackdrop).toContain("max-[1180px]:block");
    expect(listWorkspaceStyles.agentPanelIdle).toContain("[grid-template-rows:auto_minmax(0,_1fr)]");
    expect(listWorkspaceStyles.agentPanelSelecting).toContain("[grid-template-rows:auto_auto_minmax(0,_1fr)]");
    expect(detailWorkspaceStyles.detailPanel).toContain("[overflow:auto]");
    expect(detailWorkspaceStyles.detailPanel).toContain("max-[860px]:[min-height:420px]");
    expect(detailWorkspaceStyles.detailPanel).not.toContain("max-[860px]:hidden");
    expect(detailWorkspacePanelSource).not.toContain("detailPanelCreating");
    expect(selectedDetailContentPanelSource).toContain("styles.overviewLayout");
    expect(selectedDetailContentPanelSource).toContain("<aside className={styles.overviewAside}>");
  });

  it("uses semantic opaque workspace and rail surfaces without legacy card walls", () => {
    expect(styles.route).toContain("max-w-full");
    expect(styles.route).toContain("[overflow:hidden]");
    expect(styles.route).not.toContain("[background:var(--bg-canvas)]");
    expect(styles.route).not.toContain("[background:var(--surface-page)]");
    expect(styles.route).not.toContain("[background:var(--surface-card)]");
    expect(styles.route).not.toContain("var(--surface-panel-strong)");

    expect(workspaceLayoutStyles.workspace).toMatch(/bg-vui-surface-workspace|bg-\[var\(--vui-surface-workspace\)\]/);
    expect(workspaceLayoutStyles.directory).toMatch(/bg-vui-surface-rail|bg-\[var\(--vui-surface-rail\)\]/);
    expect(workspaceLayoutStyles.main).toMatch(/!bg-vui-surface-workspace|!bg-\[var\(--vui-surface-workspace\)\]/);
    expect(workspaceLayoutStyles.inspector).toMatch(/bg-vui-surface-rail|bg-\[var\(--vui-surface-rail\)\]/);
    expect(workspaceLayoutStyles.workspace).not.toContain("bg-transparent");
    expect(workspaceLayoutStyles.workspace).not.toContain("var(--surface-card)");
    expect(workspaceLayoutStyles.workspace).not.toContain("var(--surface-panel-strong)");
    expect(workspaceLayoutStyles.workspace).not.toContain("box-shadow");
    expect(workspaceLayoutStyles.workspace).toContain("max-[860px]:flex-col");
    expect(workspaceLayoutStyles.workspace).toContain("max-[860px]:overflow-auto");
  });

  it("uses route-level VUI density guards for Agent workspace panels and actions", () => {
    expect(styles.route).toContain("[--agent-density-gap:0px]");
    expect(styles.route).toContain("[--agent-panel-pad:8px]");
    expect(styles.route).toContain("[--agent-row-pad-y:6px]");
    expect(styles.route).toContain("[--agent-control-height:24px]");
    expect(styles.route).toContain("[&_[data-vui-product=\"agent-workspace-panel\"]]:max-w-full");
    expect(styles.route).toContain("[&_[data-vui-product=\"agent-workspace-panel\"]]:overflow-hidden");
    expect(styles.route).toContain("[&_[data-vui-product=\"agent-workspace-panel\"]]:[scrollbar-gutter:stable]");
    expect(styles.route).toContain("[&_[data-vui-product=\"agent-workspace-panel\"]]:[overflow-wrap:anywhere]");
    expect(styles.route).toContain("max-[860px]:[&_[data-vui-product=\"agent-workspace-panel\"]]:overflow-visible");
    expect(styles.route).toContain("[&_[data-vui=\"button\"]]:w-fit");
    expect(styles.route).toContain("[&_[data-vui=\"button\"]]:[max-width:100%]");
    expect(styles.route).toContain("[&_[data-vui=\"button\"]]:[white-space:nowrap]");
    expect(styles.route).not.toContain("[&_[data-vui=\"button\"]]:w-full");
    expect(styles.route).not.toContain("[&_[data-vui=\"button\"]]:[width:100%]");
  });

  it("keeps legacy lightweight items hairline-only while core Agent surfaces remain opaque", () => {
    const repeatedSurfaceStyles: Array<keyof typeof styles> = [
      "activityTimelineItem",
      "advancedFilterSummary",
      "avatarEditorPanel",
      "boundarySummaryGrid",
      "checkField",
      "configEditor",
      "inboxMessageItem",
      "policySummaryGrid",
      "roomCheckField",
      "runHistoryItem",
      "runtimeEvidenceHint",
      "runtimePolicyGrid",
      "segmentedControl",
      "storagePanel",
      "toolBundleItem",
      "toolGovernanceItem",
      "toolPermissionGroup",
      "toolPermissionRow",
      "workspaceScopePanel",
    ];

    for (const styleName of repeatedSurfaceStyles) {
      expectBackgroundAwareSurface(styleName);
    }

    expectOpaqueSemanticSurface(styles.agentRow, "agentRow", "!bg-[var(--vui-surface-row)]");
    expect(styles.agentRow).toMatch(/hover:bg-vui-surface-row-hover|hover:bg-\[var\(--vui-surface-row-hover\)\]/);
    expectOpaqueSemanticSurface(styles.detailSection, "detailSection", "!bg-[var(--vui-surface-panel)]");
    expectOpaqueSemanticSurface(styles.groupButton, "groupButton", "!bg-[var(--vui-surface-row)]");
    expect(styles.groupButton).toMatch(/hover:bg-vui-surface-row-hover|hover:bg-\[var\(--vui-surface-row-hover\)\]/);

    expect(styles.agentRowActive).not.toContain("var(--surface-panel-strong)");
    expect(styles.agentRowBulkSelected).not.toContain("var(--surface-panel-strong)");
    expect(styles.groupButtonActive).not.toContain("var(--surface-panel-strong)");
    expect(styles.inboxMessageItemFocused).not.toContain("var(--surface-panel-strong)");
  });

  it("keeps the Agent Center convergence maps free of legacy card walls and decorative chrome", () => {
    expectNoLegacySurfaceDebt(styles, "AgentsRoute");

    for (const [styleMap, label] of [
      [activityHistoryStyles, "AgentActivityHistory"],
      [archiveZoneStyles, "AgentArchiveZone"],
      [avatarEditorStyles, "AgentAvatarEditor"],
      [managementBriefStyles, "AgentManagementBrief"],
      [managementNavStyles, "AgentManagementNav"],
      [managementModuleBarStyles, "AgentManagementModuleBar"],
      [memoryPolicyStyles, "AgentMemoryPolicy"],
      [modeMembershipStyles, "AgentModeMembership"],
      [personaProfileStyles, "AgentPersonaProfile"],
      [returnBannerStyles, "AgentReturnBanner"],
      [runtimeFocusStyles, "AgentRuntimeFocus"],
      [runtimePolicyStyles, "AgentRuntimePolicy"],
      [taskProfileStyles, "AgentTaskProfile"],
    ] as const) {
      expectNoLegacySurfaceDebt(styleMap, label);
    }

    expect(returnBannerStyles.returnBannerButton).toContain("max-[860px]:w-fit");
    expect(returnBannerStyles.returnBannerButton).not.toContain("max-[860px]:w-full");
    expect(returnBannerStyles.returnBannerButton).not.toContain("max-[860px]:[width:100%]");
  });

  it("keeps lightweight controls restrained while extracted Agent detail surfaces stay opaque", () => {
    const detailSurfaceStyles = [
      [createPanelStyles.createAgentPanel, "AgentCreate.createAgentPanel"],
      [createPanelStyles.createToolBundleOption, "AgentCreate.createToolBundleOption"],
      [createPanelStyles.createToolBundleSelected, "AgentCreate.createToolBundleSelected"],
      [debugResetStyles.resetZone, "AgentDebugReset.resetZone"],
      [debugResetStyles.resetOptionField, "AgentDebugReset.resetOptionField"],
      [coreConfigStyles.configEditor, "AgentCoreConfig.configEditor"],
      [coreConfigStyles.healthGuidePanel, "AgentCoreConfig.healthGuidePanel"],
      [coreConfigStyles.llmSlotField, "AgentCoreConfig.llmSlotField"],
      [healthMaintenanceStyles.detailSection, "AgentHealthMaintenance.detailSection"],
      [toolSummaryStyles.configEditor, "AgentToolSummary.configEditor"],
      [toolGovernanceStyles.configEditor, "AgentToolGovernance.configEditor"],
      [toolGovernanceStyles.toolGovernanceItem, "AgentToolGovernance.toolGovernanceItem"],
      [bulkConfigStyles.configEditor, "AgentBulkConfig.configEditor"],
      [bulkConfigStyles.bulkSelectionList, "AgentBulkConfig.bulkSelectionList"],
      [referencesPanelStyles.configEditor, "AgentReferences.configEditor"],
      [referencesPanelStyles.detailSection, "AgentReferences.detailSection"],
      [referencesPanelStyles.referenceItem, "AgentReferences.referenceItem"],
      [referencesPanelStyles.roomCheckField, "AgentReferences.roomCheckField"],
    ] as const;

    for (const [className, label] of detailSurfaceStyles) {
      expectBackgroundAwareClass(className, label);
    }

    expectOpaqueSemanticSurface(
      detailHeaderStyles.detailTabs,
      "AgentDetailHeader.detailTabs",
      "bg-[var(--vui-surface-workspace)]",
    );
    expectOpaqueSemanticSurface(overviewStyles.factGrid, "AgentOverview.factGrid", "[background:var(--vui-surface-row)]");
    expectOpaqueSemanticSurface(
      overviewStyles.detailSection,
      "AgentOverview.detailSection",
      "[background:var(--vui-surface-panel)]",
    );
    expectOpaqueSemanticSurface(
      overviewStyles.boundarySummaryGrid,
      "AgentOverview.boundarySummaryGrid",
      "[background:var(--vui-surface-row)]",
    );
    expectOpaqueSemanticSurface(overviewStyles.policyGrid, "AgentOverview.policyGrid", "[background:var(--vui-surface-row)]");
  });

  it("keeps short route-level actions content-sized and mobile-safe", () => {
    for (const styleName of ["primaryButton", "secondaryButton", "dangerButton", "returnBannerButton"] as const) {
      expectContentSizedAction(styleName);
    }

    for (const styleName of ["avatarEditorActions", "configDeepLinkRow", "editorActions", "timelineActions"] as const) {
      expectResponsiveActionRow(styleName);
    }

    expect(styles.returnBannerButton).toContain("max-[860px]:w-fit");
    expect(styles.returnBannerButton).not.toContain("max-[860px]:w-full");
    expect(styles.returnBannerButton).not.toContain("max-[860px]:[width:100%]");
  });

  it("keeps Agent detail actions content-sized while preserving bounded tabs", () => {
    expect(detailHeaderStyles.detailTabs).toContain("overflow-x-auto");
    expect(detailHeaderStyles.detailHeaderActions).toContain("[&_[data-vui=button]]:w-fit");
    expect(detailHeaderStyles.detailTab.split(/\s+/)).toContain("w-fit");
    expect(detailHeaderStyles.detailTabActive.split(/\s+/)).toContain("w-fit");

    for (const [className, label] of [
      [createPanelStyles.editorActions, "AgentCreate.editorActions"],
      [debugResetStyles.editorActions, "AgentDebugReset.editorActions"],
      [coreConfigStyles.configDeepLinkRow, "AgentCoreConfig.configDeepLinkRow"],
      [coreConfigStyles.promptConfigRow, "AgentCoreConfig.promptConfigRow"],
      [coreConfigStyles.editorActions, "AgentCoreConfig.editorActions"],
      [toolSummaryStyles.editorActions, "AgentToolSummary.editorActions"],
      [toolGovernanceStyles.editorActions, "AgentToolGovernance.editorActions"],
      [toolGovernanceStyles.governanceActions, "AgentToolGovernance.governanceActions"],
      [bulkConfigStyles.editorActions, "AgentBulkConfig.editorActions"],
      [referencesPanelStyles.referenceMetaRow, "AgentReferences.referenceMetaRow"],
      [referencesPanelStyles.roomCheckField, "AgentReferences.roomCheckField"],
    ] as const) {
      expectContentSizedVuiButtons(className, label);
    }
  });

  it("keeps Agent detail form rows and long labels mobile-safe", () => {
    for (const [className, label] of [
      [createPanelStyles.createAgentPanel, "AgentCreate.createAgentPanel"],
      [createPanelStyles.createAgentGrid, "AgentCreate.createAgentGrid"],
      [createPanelStyles.fieldWide, "AgentCreate.fieldWide"],
      [debugResetStyles.resetZone, "AgentDebugReset.resetZone"],
      [debugResetStyles.resetOptionGrid, "AgentDebugReset.resetOptionGrid"],
      [coreConfigStyles.configEditor, "AgentCoreConfig.configEditor"],
      [coreConfigStyles.editorGrid, "AgentCoreConfig.editorGrid"],
      [coreConfigStyles.llmSlotGrid, "AgentCoreConfig.llmSlotGrid"],
      [healthMaintenanceStyles.maintenanceIntro, "AgentHealthMaintenance.maintenanceIntro"],
      [toolSummaryStyles.policySummaryGrid, "AgentToolSummary.policySummaryGrid"],
      [toolGovernanceStyles.toolGovernanceList, "AgentToolGovernance.toolGovernanceList"],
      [toolGovernanceStyles.toolGovernanceItem, "AgentToolGovernance.toolGovernanceItem"],
      [bulkConfigStyles.configEditor, "AgentBulkConfig.configEditor"],
      [bulkConfigStyles.editorGrid, "AgentBulkConfig.editorGrid"],
      [referencesPanelStyles.configEditor, "AgentReferences.configEditor"],
      [referencesPanelStyles.detailSection, "AgentReferences.detailSection"],
      [referencesPanelStyles.roomMembershipList, "AgentReferences.roomMembershipList"],
      [referencesPanelStyles.referenceList, "AgentReferences.referenceList"],
    ] as const) {
      expect(className, `${label} should be shrinkable inside mobile Agent detail panes`).toContain("min-w-0");
    }

    for (const [className, label] of [
      [createPanelStyles.createToolBundleOption, "AgentCreate.createToolBundleOption"],
      [createPanelStyles.createToolBundleSelected, "AgentCreate.createToolBundleSelected"],
      [debugResetStyles.resetOptionField, "AgentDebugReset.resetOptionField"],
      [healthMaintenanceStyles.issueItem, "AgentHealthMaintenance.issueItem"],
      [healthMaintenanceStyles.maintenanceIntro, "AgentHealthMaintenance.maintenanceIntro"],
      [toolSummaryStyles.policySummaryGrid, "AgentToolSummary.policySummaryGrid"],
      [toolGovernanceStyles.toolGovernanceItem, "AgentToolGovernance.toolGovernanceItem"],
      [bulkConfigStyles.bulkSelectionList, "AgentBulkConfig.bulkSelectionList"],
      [referencesPanelStyles.roomCheckField, "AgentReferences.roomCheckField"],
      [referencesPanelStyles.referenceItem, "AgentReferences.referenceItem"],
      [overviewStyles.boundarySummaryGrid, "AgentOverview.boundarySummaryGrid"],
      [overviewStyles.policyGrid, "AgentOverview.policyGrid"],
      [overviewStyles.factGrid, "AgentOverview.factGrid"],
    ] as const) {
      expect(className, `${label} should allow long Agent labels to wrap instead of forcing horizontal overflow`).toContain("[overflow-wrap:anywhere]");
    }

    expect(coreConfigStyles.llmSlotGrid).toContain("max-[860px]:[grid-template-columns:1fr]");
    expect(healthMaintenanceStyles.maintenanceIntro).toContain("max-[860px]:[grid-template-columns:1fr]");
    expect(toolSummaryStyles.policySummaryGrid).toContain("max-[860px]:[grid-template-columns:1fr]");
    expect(toolGovernanceStyles.toolGovernanceItem).toContain("max-[860px]:[grid-template-columns:1fr]");
    expect(bulkConfigStyles.editorGrid).toContain("max-[860px]:[grid-template-columns:1fr]");
    expect(overviewStyles.boundarySummaryGrid).toContain("max-[860px]:[grid-template-columns:1fr]");
    expect(referencesPanelStyles.referenceHeader).toContain("max-[860px]:[grid-template-columns:1fr]");
    expect(referencesPanelStyles.referenceMetaRow).toContain("max-[860px]:[grid-template-columns:1fr]");
    expect(referencesPanelStyles.roomCheckField).toContain("max-[860px]:[grid-template-columns:auto_minmax(0,_1fr)]");
  });

  it("keeps Agent operations panel text readable and short actions bounded", () => {
    for (const [className, label] of [
      [healthMaintenanceStyles.issueItem, "AgentHealthMaintenance.issueItem"],
      [healthMaintenanceStyles.maintenanceIntro, "AgentHealthMaintenance.maintenanceIntro"],
      [toolSummaryStyles.policySummaryGrid, "AgentToolSummary.policySummaryGrid"],
      [toolGovernanceStyles.toolGovernanceItem, "AgentToolGovernance.toolGovernanceItem"],
      [bulkConfigStyles.bulkSelectionList, "AgentBulkConfig.bulkSelectionList"],
    ] as const) {
      expectLongTextWraps(className, label);
    }

    for (const [className, label] of [
      [toolSummaryStyles.editorActions, "AgentToolSummary.editorActions"],
      [toolGovernanceStyles.editorActions, "AgentToolGovernance.editorActions"],
      [toolGovernanceStyles.governanceActions, "AgentToolGovernance.governanceActions"],
      [bulkConfigStyles.editorActions, "AgentBulkConfig.editorActions"],
    ] as const) {
      expectContentSizedVuiButtons(className, label);
    }

    expect(bulkOperationsStyles.bulkPromptLabel).toContain("max-w-full");
    expect(bulkOperationsStyles.bulkPromptLabel).toContain("break-words");
    expect(bulkOperationsStyles.bulkPromptLabel.split(/\s+/)).not.toContain("w-full");
    expect(bulkOperationsStyles.bulkPromptPicker).toContain("min-w-0");
    expect(bulkOperationsStyles.bulkPromptPicker).toContain("flex-wrap");
    expect(bulkOperationsStyles.bulkPromptPicker).toContain("[&_select]:min-w-0");
    expect(bulkOperationsPanelSource).toContain("className={styles.bulkPromptPicker}");
  });

  it("keeps Agent card subgrids away from invalid quoted Tailwind grid areas", () => {
    expect(overviewStyles.policyGrid).not.toContain("grid-template-areas");
    expect(overviewStyles.policyGrid).toContain("[&_div]:[grid-template-rows:auto_auto]");
    expect(overviewStyles.policyGrid).toContain("[&_svg]:[grid-column:1]");
    expect(overviewStyles.policyGrid).toContain("[&_svg]:[grid-row:1_/_3]");
    expect(overviewStyles.policyGrid).toContain("[&_span]:[grid-column:2]");
    expect(overviewStyles.policyGrid).toContain("[&_strong]:[grid-row:2]");
    expect(styles.toolBundleItem).not.toContain("grid-template-areas");
    expect(styles.toolBundleItem).toContain("[grid-template-rows:auto_auto]");
    expect(styles.toolBundleItem).toContain("[&_span]:[grid-column:1]");
    expect(styles.toolBundleItem).toContain("[&_p]:[grid-row:2]");
    expect(styles.toolBundleActions).toContain("[grid-column:2]");
    expect(styles.toolBundleActions).toContain("[grid-row:1_/_3]");
  });

  it("keeps the narrow Agent management stack compact enough to preserve list and detail context", () => {
    expect(workspaceLayoutStyles.directory).toContain("max-[860px]:min-h-[320px]");
    expect(workspaceLayoutStyles.workspace).toContain("max-[860px]:flex-col");
    expect(styles.filterPanel).toContain("max-[860px]:[min-height:150px]");
    expect(listWorkspaceStyles.agentPanel).toContain("max-[860px]:[min-height:240px]");
    expect(detailWorkspaceStyles.detailPanel).toContain("max-[860px]:[min-height:420px]");
  });

  it("fills the Agent detail empty state so the right pane does not look abandoned", () => {
    expect(emptySelectionPanelSource).toContain('from "./AgentEmptySelectionPanel.styles"');
    expect(emptySelectionPanelSource).not.toContain("AgentsRoute.styles");
    expect(emptySelectionStyles.emptyState).toBeTruthy();
    expect(detailWorkspacePanelSource).toContain("AgentEmptySelectionPanel");
    expect(emptySelectionPanelSource).toContain("className={styles.emptyState}");
    expect(emptySelectionStyles.emptyState).toContain("[place-content:center]");
    expect(emptySelectionStyles.emptyState).toContain("[place-items:center]");
    expect(emptySelectionStyles.emptyState).toContain("h-full");
    expect(emptySelectionStyles.emptyState).toContain("[text-align:center]");
  });

  it("renders every Agent as a person name plus colored functional role tag", () => {
    expect(routeSource).toContain("agentDisplayInfo(agent, lang)");
    expect(routeSource).toContain("roleTone: display.tone");
    expect(denseListSource).toContain("function roleToneClass");
    expect(routeSource).toContain("display.functionLabel");
  });

  it("supports bulk Agent selection with prompt editing and protected safe archive", () => {
    expect(routeSource).toContain("selectedBulkAgentIds");
    expect(routeSource).toContain("bulkSelectionAnchorAgentId");
    expect(routeSource).toContain("event.ctrlKey || event.metaKey || event.shiftKey");
    expect(routeSource).toContain("visibleAgents.slice(start, end + 1)");
    expect(routeSource).toContain("bulkConfigDraftFromAgents");
    expect(routeSource).toContain("bulkApplyAgentConfig");
    expect(routeSource).toContain("bulkApplyPromptTemplate");
    expect(routeSource).toContain("bulkArchiveAgents");
    expect(routeSource).toContain("bulkPurgeAgents");
    expect(routeSource).toContain("agentArchiveProtected(agent)");
    expect(routeSource).toContain('metadataFlag(agent, "fixedRole")');
    expect(routeSource).toContain('metadataString(agent, "supervisedRole")');
    expect(routeSource).toContain("copy.bulkSkippedProtected");
    expect(routeSource).toContain("bulkPurgeConfirm:");
    expect(routeSource).toContain("bulkArchiveConfirm:");
    expect(routeSource).toContain("copy.bulkPurgeResult");
    expect(bulkOperationsPanelSource).toContain("copy.bulkPurgeConfirm");
    expect(bulkOperationsPanelSource).toContain("copy.bulkArchiveConfirm");
    expect(bulkConfigPanelSource).toContain("copy.bulkEditMixed");
    expect(bulkConfigPanelSource).toContain('from "./AgentBulkConfigPanel.styles"');
    expect(bulkConfigPanelSource).not.toContain("AgentsRoute.styles");
    expect(routeSource).toContain('"/api/agents/bulk-prompt-template"');
    expect(routeSource).toContain('"/api/agents/bulk-config"');
    expect(routeSource).toContain("applyFields: bulkConfigApplyFields(bulkConfigApply)");
    expect(routeSource).toContain("patch: bulkConfigPatchFromDraft(bulkConfigDraft, bulkConfigApply)");
    expect(routeSource).toContain("body: JSON.stringify({ agentIds: selectedBulkAgents.map((agent) => agent.agentId), promptTemplateId: bulkPromptTemplateId })");
    expect(routeSource).toContain("bulkUpdatedAgentWorkspaceCache");
    expect(routeSource).toContain('"/api/agents/bulk-archive"');
    expect(routeSource).toContain('"/api/agents/bulk-purge"');
    expect(routeSource).toContain("bulkPurgeWorkspaceCache");
    expect(routeSource).toContain("bulkConfig: selectedBulkAgents.length > 1 ? {");
    expect(detailWorkspacePanelSource).toContain("<AgentBulkConfigPanel");
    expect(routeSource).toContain("onToggleApply: toggleBulkConfigApply");
    expect(routeSource).toContain("onDraftChange: updateBulkConfigDraft");
    expect(routeSource).toContain("onSave: bulkApplyAgentConfig");
    expect(listWorkspacePanelSource).toContain("AgentBulkOperationsPanel");
    expect(bulkOperationsPanelSource).toContain("AgentBulkActionBar");
    expect(routeSource).toContain("VButton");
    expect(routeSource).toContain("bulkOperations: {");
    expect(routeSource).toContain("selectedCount: selectedBulkAgents.length");
    expect(routeSource).toContain("visibleCount: visibleAgents.length");
    expect(routeSource).toContain("onSelectVisible: selectVisibleBulkAgents");
    expect(routeSource).toContain("onClearSelection: clearBulkAgents");
    expect(routeSource).toContain("onPromptTemplateChange: setBulkPromptTemplateId");
    expect(routeSource).toContain("onApplyPromptTemplate: bulkApplyPromptTemplate");
    expect(routeSource).toContain("onArchive: bulkArchiveAgents");
    expect(routeSource).toContain("onPurge: bulkPurgeAgents");
    expect(routeSource).not.toContain("const archivedAgent = await fetchJson<AgentConfigWorkspaceAgent>(`/api/agents/${encodeURIComponent(agent.agentId)}`");
    expect(routeSource).not.toContain("const updatedAgent = await fetchJson<AgentConfigWorkspaceAgent>(`/api/agents/${encodeURIComponent(agent.agentId)}`");
    expect(routeSource).not.toContain("for (const agent of selectedBulkAgents) {\n      if (agentArchiveProtected(agent))");
    expect(routeSource).not.toContain("`/api/agents/${encodeURIComponent(agent.agentId)}/purge`");
    expect(routeSource).toContain('method: "DELETE"');
    expect(routeSource).toContain("onPurge: bulkPurgeAgents");
    expect(routeSource).not.toContain("window.confirm(copy.bulkArchiveConfirm)");
    expect(routeSource).not.toContain("window.confirm(copy.bulkPurgeConfirm)");
    expect(bulkOperationsPanelSource).toContain("VConfirmDialog");
    expect(bulkOperationsPanelSource).toContain('setConfirmKind("archive")');
    expect(bulkOperationsPanelSource).toContain('setConfirmKind("purge")');
    expect(bulkOperationsPanelSource).toContain("onArchive()");
    expect(bulkOperationsPanelSource).toContain("onPurge()");
    expect(bulkConfigPanelSource).toContain("onPress={onSave}");
    expect(bulkConfigPanelSource).toContain("onPress={onReset}");
    expect(bulkConfigPanelSource).toContain("styles.bulkSelectionList");
    expect(bulkConfigPanelSource).toContain("styles.bulkFieldHeader");
    expect(bulkConfigStyles.bulkSelectionList).toBeTruthy();
    expect(bulkConfigStyles.bulkFieldHeader).toBeTruthy();
    expect(bulkConfigPanelSource).toContain("<VNativeSelect");
    expect(bulkConfigPanelSource).toContain("<VNativeInput");
    expect(routeSource).toContain("bulkSelected: selectedBulkAgentIds.has(agent.agentId)");
    expect(denseListSource).toContain("onToggleBulk");
    expect(listWorkspaceStyles.agentPanelIdle).toContain("[grid-template-rows:auto_minmax(0,_1fr)]");
    expect(listWorkspaceStyles.agentPanelSelecting).toContain("[grid-template-rows:auto_auto_minmax(0,_1fr)]");
    expect(listWorkspacePanelSource).toContain("bulkOperations.selectedCount === 0");
    expect(listWorkspacePanelSource).toContain("bulkOperations.selectedCount > 0");
    expect(bulkOperationsPanelSource).toContain("if (!hasSelection)");
    expect(bulkOperationsPanelSource).toContain("return null");
    expect(routeSource).not.toContain("styles.bulkActionBar");
    expect(stylesSource).not.toContain(".bulkActionBar {");
    expect(stylesSource).not.toContain(".bulkSummary");
    expect(stylesSource).not.toContain(".bulkPromptPicker");
    expect(styles.agentRowBulkSelected).toContain(
      "bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))]",
    );
    expect(styles.agentRowActive).toContain(
      "bg-[color-mix(in_srgb,var(--accent-warm)_9%,var(--vui-surface-row))]",
    );
    expect(styles.agentRow).toMatch(/!bg-vui-surface-row|!bg-\[var\(--vui-surface-row\)\]/);
    expect(bulkActionBarSource).toContain("!flex-nowrap items-center overflow-x-auto");
    expect(bulkActionBarSource).toContain("flex-[0_0_190px]");
    expect(bulkActionBarSource).toContain("min-h-[74px] overflow-hidden");
  });

  it("renders bulk action controls through VUI buttons instead of page-owned button CSS", () => {
    const bulkSelectionSource = bulkOperationsPanelSource.slice(
      bulkOperationsPanelSource.indexOf("const selectionActions"),
      bulkOperationsPanelSource.indexOf("const promptPicker"),
    );
    const bulkMutationSource = bulkOperationsPanelSource.slice(
      bulkOperationsPanelSource.indexOf("const mutationActions"),
      bulkOperationsPanelSource.indexOf("const destructiveActions"),
    );
    const bulkDestructiveStart = bulkOperationsPanelSource.indexOf("const destructiveActions");
    const bulkDestructiveSource = bulkOperationsPanelSource.slice(
      bulkDestructiveStart,
      bulkOperationsPanelSource.indexOf("return (", bulkDestructiveStart),
    );
    const bulkPromptSource = bulkOperationsPanelSource.slice(
      bulkOperationsPanelSource.indexOf("const promptPicker"),
      bulkOperationsPanelSource.indexOf("const mutationActions"),
    );

    expect(bulkPromptSource).toContain("<VNativeSelect");
    expect(bulkPromptSource).not.toContain("styles.bulkPromptSelect");
    expect(bulkPromptSource).not.toContain("styles.bulkPromptField");
    expect(bulkSelectionSource).toContain("<VButton");
    expect(bulkSelectionSource).toContain('variant="secondary"');
    expect(bulkSelectionSource).not.toContain("styles.secondaryButton");
    expect(bulkMutationSource).toContain("<VButton");
    expect(bulkMutationSource).toContain('variant="primary"');
    expect(bulkMutationSource).toContain('variant="secondary"');
    expect(bulkMutationSource).not.toContain("styles.primaryButton");
    expect(bulkMutationSource).not.toContain("styles.secondaryButton");
    expect(bulkDestructiveSource).toContain("<VButton");
    expect(bulkDestructiveSource).toContain('variant="danger"');
    expect(bulkDestructiveSource).not.toContain("styles.dangerButton");
  });

  it("renders Agent editor action rows through VUI buttons instead of page-owned button CSS", () => {
    const editorActionBlocks = [
      ...sourceBlocksForStyle("editorActions"),
      ...sourceBlocksForStyle("editorActions", coreConfigPanelSource),
      ...sourceBlocksForStyle("editorActions", archiveZonePanelSource),
      ...sourceBlocksForStyle("editorActions", createPanelSource),
      ...sourceBlocksForStyle("editorActions", debugResetPanelSource),
      ...sourceBlocksForStyle("editorActions", modeMembershipPanelSource),
      ...sourceBlocksForStyle("editorActions", personaProfilePanelSource),
      ...sourceBlocksForStyle("editorActions", taskProfilePanelSource),
      ...sourceBlocksForStyle("editorActions", toolGovernancePanelSource),
      ...sourceBlocksForStyle("editorActions", memoryPolicyPanelSource),
      ...sourceBlocksForStyle("editorActions", toolSummaryPanelSource),
    ];
    const deepLinkActionBlocks = [
      ...sourceBlocksForStyle("configDeepLinkRow"),
      ...sourceBlocksForStyle("configDeepLinkRow", coreConfigPanelSource),
      ...sourceBlocksForStyle("configDeepLinkRow", contextCompressionPanelSource),
    ];
    const governanceActionBlocks = sourceBlocksForStyle("governanceActions", toolGovernancePanelSource);
    const promptConfigActionBlocks = sourceBlocksForStyle("promptConfigRow", coreConfigPanelSource);
    const inboxMessageActionBlocks = sourceBlocksForStyle("inboxMessageTop");
    const panelHeaderActionBlocks = sourceBlocksForStyle("panelHeaderActions")
      .filter((block) => block.includes("copy.createAgent") || block.includes("copy.consumeAllMessages"));
    const pendingInboxIssueStart = healthMaintenancePanelSource.indexOf("issue.showInboxAction ? (");
    const pendingInboxIssueBlock = healthMaintenancePanelSource.slice(
      pendingInboxIssueStart,
      healthMaintenancePanelSource.indexOf("</article>", pendingInboxIssueStart),
    );
    const actionBlocks = [
      ...editorActionBlocks,
      ...deepLinkActionBlocks,
      ...governanceActionBlocks,
      ...promptConfigActionBlocks,
      ...inboxMessageActionBlocks,
      ...panelHeaderActionBlocks,
      pendingInboxIssueBlock,
    ];

    expect(pendingInboxIssueStart).toBeGreaterThanOrEqual(0);
    expect(editorActionBlocks.length).toBeGreaterThanOrEqual(10);
    expect(actionBlocks.length).toBeGreaterThanOrEqual(14);
    expect(actionBlocks.join("\n")).toContain('variant="primary"');
    expect(actionBlocks.join("\n")).toContain('variant="secondary"');
    expect(actionBlocks.join("\n")).toContain('variant="danger"');

    for (const block of actionBlocks) {
      expect(block).toContain("<VButton");
      expect(block).not.toContain("<button");
      expect(block).not.toContain("styles.primaryButton");
      expect(block).not.toContain("styles.secondaryButton");
      expect(block).not.toContain("styles.dangerButton");
    }
  });

  it("renders Agent micro action controls through VUI buttons instead of route-local button CSS", () => {
    const avatarActionStart = avatarEditorPanelSource.indexOf("className={styles.avatarEditorActions}");
    const avatarActionSource = avatarEditorPanelSource.slice(
      avatarActionStart,
      avatarEditorPanelSource.indexOf("className={styles.avatarLibraryHeader}", avatarActionStart),
    );
    const memoryPolicyStart = memoryPolicyPanelSource.indexOf("className={styles.memoryPolicyGrid}");
    const memoryPolicySource = memoryPolicyPanelSource.slice(
      memoryPolicyStart,
      memoryPolicyPanelSource.indexOf("<datalist", memoryPolicyStart),
    );
    const timelineActionBlocks = [
      ...sourceBlocksForStyle("timelineActions"),
      ...sourceBlocksForStyle("timelineActions", activityHistoryPanelSource),
      ...sourceBlocksForStyle("timelineActions", runtimeFocusPanelSource),
    ];

    expect(avatarActionStart).toBeGreaterThanOrEqual(0);
    expect(memoryPolicyStart).toBeGreaterThanOrEqual(0);
    expect(timelineActionBlocks.length).toBeGreaterThanOrEqual(2);

    expect(avatarActionSource).toContain("<VButton");
    expect(avatarActionSource).not.toContain("<button");
    expect(avatarActionSource).not.toContain("styles.secondaryButton");

    expect(memoryPolicySource).toContain("<VButton");
    expect(memoryPolicySource).not.toContain("<button");

    expect(routeSource).not.toContain("styles.referenceRouteButton");
    expect(configReferencesPanePanelSource).toContain("AgentReferencesPanel");
    expect(routeSource).toContain("onOpenRoute: (route: string) => navigate(route)");

    for (const block of timelineActionBlocks) {
      expect(block).toContain("<VButton");
      expect(block).not.toContain("<button");
    }
  });
});
