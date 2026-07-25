import { describe, expect, it } from "vitest";

import styles from "./RuntimeScenesPane.styles";
import stylesSource from "./RuntimeScenesPane.styles.ts?raw";
import paneSource from "./RuntimeScenesPane.tsx?raw";

const backgroundTokens = (className: string) =>
  className.split(/\s+/).filter((token) =>
    token.startsWith("bg-[")
    || token.startsWith("!bg-[")
    || token.startsWith("bg-vui-")
    || token.startsWith("!bg-vui-")
    || token.startsWith("[background:"),
  );

const expectBackgroundAware = (className: string) => {
  const tokens = backgroundTokens(className);

  expect(tokens.length).toBeGreaterThan(0);
  expect(tokens.some((token) => token.includes("vui-surface") || (token.includes("color-mix") && token.includes("transparent")))).toBe(true);
  expect(className).not.toContain("bg-[var(--vui-surface-glass)]");
  expect(className).not.toContain("shadow-[var(--vui-shadow-hairline)]");
};

const expectControlOnlyAction = (className: string) => {
  expect(className).toContain("inline-flex");
  expect(className).toContain("w-fit");
  expect(className).toContain("max-w-full");
  expect(className).toContain("min-w-0");
  expect(className).toContain("rounded-[var(--radius-control)]");
  expect(className).toContain("bg-[var(--vui-control-muted)]");
  expect(className).not.toContain("rounded-[var(--radius-panel)]");
  expect(className).not.toMatch(/bg-vui-surface-panel|var\(--vui-surface-panel\)/);
  expect(className).not.toContain("var(--vui-surface-row)");
};

describe("RuntimeScenesPane layout contract", () => {
  it("routes runtime scene controls through VUI primitives", () => {
    expect(paneSource).toContain("from \"../components/vui\"");
    expect(paneSource).toContain("<VButton");
    expect(paneSource).toContain("<VIconButton");
    expect(paneSource).toContain("<VNativeInput");
    expect(paneSource).not.toMatch(/<button\b/);
    expect(paneSource).not.toMatch(/<input\b/);
  });

  it("renders package diagnosis before evidence metrics and raw log sections", () => {
    const diagnosisIndex = paneSource.indexOf("{renderPackageDiagnosisPanel(scene, lang, handleOpenRawLog)}");
    const evidenceIndex = paneSource.indexOf('<div className={styles.sceneEvidenceStrip}>');
    const rawHeaderIndex = paneSource.indexOf('{t("runtimeSceneRawLogs")}');

    expect(diagnosisIndex).toBeGreaterThan(0);
    expect(evidenceIndex).toBeGreaterThan(diagnosisIndex);
    expect(rawHeaderIndex).toBeGreaterThan(evidenceIndex);
  });

  it("keeps package diagnosis compact by folding low-frequency details", () => {
    expect(paneSource).toContain("<details className={styles.packageDiagnosisDetails}>");
    expect(paneSource).toContain("{lang === \"zh\" ? \"阅读顺序与关键入口\" : \"Reading order and key entries\"}");
    expect(paneSource).toContain("const evidencePaths = diagnosis.evidencePaths?.length");
    expect(paneSource).toContain("styles.packageEvidencePaths");
    expect(paneSource).toContain("\"优先排查路径\"");
    expect(paneSource).toContain("Package-relative path");
    expect(paneSource).toContain("packageDiagnosisFoldout");
    expect(paneSource).toContain("packageDiagnosisInlineMetrics");
    expect(paneSource).toContain("handleOpenRawLog(scene.runtimeSceneId, entry.path)");
  });

  it("surfaces active, policy, historical, and control issue state near the package summary", () => {
    expect(paneSource).toContain("const issueState = diagnosis.issueState");
    expect(paneSource).toContain("signalHeading");
    expect(paneSource).toContain("\"优先信号\"");
    expect(paneSource).toContain("\"策略信号\"");
    expect(paneSource).toContain("\"历史信号\"");
    expect(paneSource).toContain("\"控制信号\"");
    expect(paneSource).toContain("styles.packageIssueStateStrip");
    expect(paneSource).toContain("issueState.activeClusterCount ?? activeSignalCount");
    expect(paneSource).toContain("issueState.policyClusterCount ?? issueState.policySignalCount ?? 0");
    expect(paneSource).toContain("issueState?.policyClusters?.[0]");
    expect(paneSource).toContain("issueState?.firstPolicyCluster");
    expect(paneSource).toContain("\"主控制/策略簇\"");
    expect(paneSource).toContain("issueState.historicalClusterCount ?? historicalSignalCount");
    expect(paneSource).toContain("issueState.controlSignalCount");
  });

  it("surfaces compact work run focus without duplicating raw work run events", () => {
    expect(paneSource).toContain("const workRunSummary = diagnosis.workRunSummary");
    expect(paneSource).toContain("const activeRuns = workRunSummary?.activeRuns ?? []");
    expect(paneSource).toContain("const highFrequencyRuns = workRunSummary?.highFrequencyRuns ?? []");
    expect(paneSource).toContain("styles.packageWorkRunPanel");
    expect(paneSource).toContain("\"运行任务摘要\"");
    expect(paneSource).toContain("workRunSummary.eventsPath");
    expect(paneSource).toContain("handleOpenRawLog(scene.runtimeSceneId, workRunSummary.eventsPath)");
    expect(paneSource).toContain("runtimeSceneWorkRunLabel(run, lang)");
    expect(paneSource).toContain("runtimeSceneWorkRunMeta(run, lang)");
  });

  it("shows a primary issue cluster before folded diagnostic details", () => {
    expect(paneSource).toContain("const primaryCluster");
    expect(paneSource).toContain("styles.packagePrimaryCluster");
    expect(paneSource).toContain("runtimeSceneIssueClusterLabel(primaryCluster, lang)");
    expect(paneSource).toContain("runtimeSceneIssueClusterMeta(primaryCluster, lang)");
    expect(paneSource).toContain("styles.packageClusterList");
    expect(paneSource).toContain("handleOpenRawLog(scene.runtimeSceneId, cluster.rawRefs[0].path)");
  });

  it("keeps the runtime scene sidebar collapsible from the shared resize contract", () => {
    expect(paneSource).toContain("PaneCollapseHandle");
    expect(paneSource).toContain("usePersistedPaneResize");
    expect(paneSource).toContain("WORKBENCH_LAYOUT_IDS.logsRuntimeScenes");
    expect(paneSource).toContain("sidebarCollapsed");
    expect(paneSource).toContain("setSidebarCollapsed");
    expect(paneSource).toContain("--logs-sidebar-width");
    expect(paneSource).toContain("data-vui-layout-id");
  });

  it("keeps the scene list on the lightweight package index", () => {
    expect(paneSource).not.toContain("packageIndex?.diagnosis");
    expect(paneSource).toContain("function runtimeSceneListSummary");
    expect(paneSource).toContain("scene.stopReason || scene.result || scene.displayName");
    expect(paneSource).toContain("item.packageIndex?.searchText");
  });

  it("uses diagnosis summaries instead of raw error counts for runtime scene list signals", () => {
    expect(paneSource).toContain("function runtimeSceneListSignal");
    expect(paneSource).toContain("if (scene.diagnosisSummary)");
    expect(paneSource).toContain("scene.diagnosisSummary.activeClusterCount");
    expect(paneSource).toContain("scene.diagnosisSummary.policyClusterCount");
    expect(paneSource).toContain("return null;");
  });

  it("uses package diagnosis issue state for detail header signals before raw counts", () => {
    expect(paneSource).toContain("function runtimeSceneSignal");
    expect(paneSource).toContain("const issueState = scene.packageDiagnosis?.issueState");
    expect(paneSource).toContain("issueState.activeClusterCount");
    expect(paneSource).toContain("issueState.historicalClusterCount");
    expect(paneSource).toContain("\"历史已恢复\"");
  });

  it("polls scene detail and raw content only while the active scene is live", () => {
    expect(paneSource).toContain("function runtimeSceneIsLive");
    expect(paneSource).toContain("const activeSceneListItem = useMemo(");
    expect(paneSource).toContain("runtimeSceneIsLive(detail ?? activeSceneListItem)");
    expect(paneSource).toContain("const activeSceneLive = runtimeSceneIsLive(sceneDetailQuery.data ?? activeSceneListItem)");
    expect(paneSource).toContain("refetchInterval: activeSceneLive ? resolvePollingInterval(pageVisible, 5_000) : false");
    expect(paneSource).not.toContain("refetchInterval: resolvePollingInterval(pageVisible, 5_000),");
  });

  it("counts research workflow logs as a separate package child section", () => {
    expect(paneSource).toContain("scene.packageSummary?.researchLogCount");
    expect(paneSource).toContain("scene.researchLogs?.length");
    expect(paneSource).toContain("research: \"科研\"");
  });

  it("can initialize and update the active runtime scene from deep-link props", () => {
    expect(paneSource).toContain("initialSceneId?: string");
    expect(paneSource).toContain("initialPath?: string");
    expect(paneSource).toContain("const [activeSceneId, setActiveSceneId] = useState(initialSceneId)");
    expect(paneSource).toContain("initialSceneId && initialPath ? { [initialSceneId]: initialPath } : {}");
    expect(paneSource).toContain("setActiveSceneId(initialSceneId)");
    expect(paneSource).toContain("[initialPath, initialSceneId]");
  });

  it("keeps repeated runtime scene panels background-aware instead of stacked glass cards", () => {
    [
      styles.diagnosticsPanel,
      styles.packageDiagnosisPanel,
      styles.packageWorkRunPanel,
      styles.panelSearch,
      styles.previewPane,
      styles.sceneCard,
      styles.sceneDetailSurface,
      styles.startupTracePanel,
    ].forEach(expectBackgroundAware);
  });

  it("keeps runtime scene surface and action tokens centralized in route-local constants", () => {
    expect(stylesSource).toContain("const panelSurface");
    expect(stylesSource).toContain("const rowSurface");
    expect(stylesSource).toContain("const buttonBase");
    expect(stylesSource).toContain("const activeTone");
    expect(stylesSource).toContain("const scrollStack");
  });

  it("keeps nested runtime rows quieter than their parent panels", () => {
    [
      styles.packageClusterItem,
      styles.packageDiagnosisSummaryRow,
      styles.packageWorkRunItem,
      styles.sceneCardHeaderRow,
      styles.scenePillRow,
      styles.timelineItem,
    ].forEach((className) => {
      expectBackgroundAware(className);
      expect(className).toContain("rounded-[var(--radius-control)]");
    });
  });

  it("keeps runtime scene actions content-sized and mobile overflow guarded", () => {
    [
      styles.copyButton,
      styles.deleteButton,
      styles.filterButton,
      styles.rawFileButton,
      styles.toolbarButton,
      styles.packageKeyEntryButton,
      styles.sceneCardButton,
    ].forEach(expectControlOnlyAction);

    [
      styles.previewPane,
      styles.packageList,
      styles.timelineList,
      styles.railText,
    ].forEach((className) => {
      expect(className).toContain("min-w-0");
      expect(className).toContain("overflow");
    });

    expect(styles.resizableLayout).toContain("min-w-0");
    expect(styles.resizableLayout).toContain("max-w-full");
    expect(styles.resizableLayout).toContain("overflow-x-hidden");
    expect(styles.resizableLayout).toContain("max-[900px]:grid-cols-[minmax(0,1fr)]");
    expect(styles.resizableLayout).toContain("max-[900px]:grid-rows-[max-content_minmax(0,1fr)]");
  });
});
