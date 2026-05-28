import { describe, expect, it } from "vitest";

import paneSource from "./RuntimeScenesPane.tsx?raw";

describe("RuntimeScenesPane layout contract", () => {
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

  it("keeps the runtime scene sidebar collapsible from the resize handle", () => {
    expect(paneSource).toContain("PaneCollapseHandle");
    expect(paneSource).toContain("sidebarCollapsed");
    expect(paneSource).toContain("setSidebarCollapsed");
    expect(paneSource).toContain("--logs-sidebar-width");
  });

  it("keeps the scene list on the lightweight package index", () => {
    expect(paneSource).not.toContain("packageIndex?.diagnosis");
    expect(paneSource).toContain("function runtimeSceneListSummary");
    expect(paneSource).toContain("scene.stopReason || scene.result || scene.displayName");
    expect(paneSource).toContain("item.packageIndex?.searchText");
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
});
