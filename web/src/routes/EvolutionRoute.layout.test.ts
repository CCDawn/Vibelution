import { describe, expect, it } from "vitest";

// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { readFileSync } from "node:fs";
import routeSource from "./EvolutionRoute.tsx?raw";
import runMutationsSource from "./evolution/useEvolutionRunMutations.ts?raw";
import activeRunMonitorPanelSource from "./EvolutionActiveRunMonitorPanel.tsx?raw";
import activeRunMonitorStyles from "./EvolutionActiveRunMonitorPanel.styles";
import activeRunMonitorStylesSource from "./EvolutionActiveRunMonitorPanel.styles.ts?raw";
import proposalActionBandsPanelSource from "./EvolutionProposalActionBandsPanel.tsx?raw";
import proposalActionBandsStyles from "./EvolutionProposalActionBandsPanel.styles";
import proposalActionBandsStylesSource from "./EvolutionProposalActionBandsPanel.styles.ts?raw";
import runRecordsPanelSource from "./EvolutionRunRecordsPanel.tsx?raw";
import runRecordsPanelStyles from "./EvolutionRunRecordsPanel.styles";
import runRecordsPanelStylesSource from "./EvolutionRunRecordsPanel.styles.ts?raw";
import selfTrackBoundarySource from "./EvolutionSelfTrackBoundary.tsx?raw";
import selfTrackBoundaryStyles from "./EvolutionSelfTrackBoundary.styles";
import selfTrackBoundaryStylesSource from "./EvolutionSelfTrackBoundary.styles.ts?raw";
import routeStyles from "./EvolutionRoute.styles";
import stylesSource from "./EvolutionRoute.styles.ts?raw";

const worktreeReviewStylesSource = readFileSync(new URL("./SupervisedWorktreeReviewPanel.styles.ts", import.meta.url), "utf-8");
const dictionarySource = readFileSync(new URL("../i18n/dictionary.ts", import.meta.url), "utf-8");
const evolutionTypesSource = readFileSync(new URL("../api/types/evolution.ts", import.meta.url), "utf-8");
const evolutionSources = [
  routeSource,
  activeRunMonitorPanelSource,
  proposalActionBandsPanelSource,
  runRecordsPanelSource,
].join("\n");

describe("EvolutionRoute library user flow contract", () => {
  it("uses VUI composition for supervised Evolution surfaces without native control wrappers", () => {
    expect(routeSource).toContain("VRouteHeader");
    expect(routeSource).toContain("VMetricStrip");
    expect(routeSource).toContain("VStateSurface");
    expect(routeSource).toContain("VStringSelect");
    expect(routeSource).toContain("onChange={setKeepWorktree}");
    expect(routeSource).toContain("hideIntro={hideSupervisedToolbarIntro}");
    expect(routeSource).not.toContain('"\\u200B"');
    expect(activeRunMonitorPanelSource).toContain("<VButton");
    expect(proposalActionBandsPanelSource).toContain("<VButton");
    expect(runRecordsPanelSource).toContain("<VButton");
    expect(evolutionSources).not.toContain("<VNativeButton");
    expect(evolutionSources).not.toContain("<VNativeInput");
    expect(evolutionSources).not.toContain("<VNativeSelect");
    expect(evolutionSources).not.toContain("<VNativeTextarea");
  });

  it("keeps complex Evolution card buttons in the VButton plain-content layout", () => {
    expect(routeSource.match(/contentLayout="plain"/g)).toHaveLength(4);
    expect(routeSource).toMatch(/contentLayout="plain"[\s\S]{0,160}styles\.caseTraceSummary/);
    expect(routeSource).toMatch(/contentLayout="plain"[\s\S]{0,160}styles\.workflowStepButton/);
    expect(routeSource.match(/contentLayout="plain"[\s\S]{0,160}styles\.proposalCardButton/g)).toHaveLength(2);
    expect(runRecordsPanelSource).toMatch(/contentLayout="plain"[\s\S]{0,160}styles\.runCardButton/);
  });

  it("shows self-evolution candidates as local pending details instead of proposal details", () => {
    expect(routeSource).toContain("selectedProposalIsSelfCandidate");
    expect(routeSource).toContain("!selectedProposalIsSelfCandidate");
    expect(routeSource).toContain("renderSelfEvolutionCandidateDetail(selectedProposalSummary)");
    expect(routeSource).toContain("function isSelfEvolutionCandidateItem");
    expect(routeSource).toContain('item?.ingestMode === "self_evolution_candidate"');
  });

  it("labels self-evolution candidate origins without opening them as supervised runs", () => {
    expect(routeSource).toContain("function proposalDisplaySourceRun");
    expect(routeSource).toContain("item.sourceSelfRunId || item.sourceRun");
    expect(routeSource).toContain("function canOpenProposalSourceRun");
    expect(routeSource).toContain("!isSelfEvolutionCandidateItem(item)");
    expect(routeSource).toContain("selectedProposalDisplaySourceRun || latestRun?.id");
    expect(routeSource).toContain("selectedProposalSummary && selectedProposalCanOpenSourceRun");
    expect(routeSource).toContain("item.riskLevel ? riskLabel(item.riskLevel) : \"--\"");
  });

  it("does not let blocked library items enter batch delete selection", () => {
    const disabledSelectionCount = routeSource.match(/isDisabled={!item\.canDelete}/g)?.length ?? 0;
    expect(disabledSelectionCount).toBeGreaterThanOrEqual(2);
    expect(routeSource).toContain("visibleLibraryEntries.filter((item) => item.canDelete).map((item) => item.sourceRun)");
    expect(routeSource).toContain("function toggleProposalSelection(item: EvolutionLibraryEntry)");
    expect(routeSource).toContain("if (!item.canDelete)");
    expect(routeSource).toContain("onChange={() => toggleProposalSelection(item)}");
  });

  it("adds collapse handles to the supervised split panes", () => {
    expect(routeSource).toContain("PaneCollapseHandle");
    expect(routeSource).toContain("liveLaunchCollapsed");
    expect(routeSource).toContain("liveRunCollapsed");
    expect(routeSource).toContain("runsQueueCollapsed");
    expect(routeSource).toContain("libraryListCollapsed");
  });

  it("routes self-evolution starts only into the reviewed worktree endpoint", () => {
    expect(routeSource).toContain("startSelfWorktreeRunMutation");
    expect(runMutationsSource).toContain('"/api/evolution/self/worktree-runs"');
    expect(runMutationsSource).toContain('mode: "manual"');
    expect(routeSource).toContain("onStartRun={() => startSelfWorktreeRunMutation.mutate()}");
    expect(routeSource).toContain("startWorktreeError={startSelfWorktreeRunMutation.error?.message ?? \"\"}");
    expect(routeSource).not.toContain('"/api/evolution/self/runs"');
    expect(routeSource).not.toContain("startSelfRunMutation");
    expect(routeSource).not.toContain("liveSelfRun");
    expect(routeSource).not.toContain("SelfEvolutionActiveRun");
  });

  it("keeps candidate worktree review out of the live left rail", () => {
    expect(routeSource).toContain("startWorktreeRunMutation");
    expect(runMutationsSource).toContain('"/api/evolution/worktree-runs"');
    expect(routeSource).not.toContain("SupervisedWorktreeReviewPanel");
    expect(routeSource).not.toContain("worktreeActionMutation");
    expect(routeSource).not.toContain("triggerWorktreeReviewApproval");
    expect(routeSource).not.toContain("triggerWorktreeAction");
    expect(routeSource).not.toContain("selectedWorktreeRunId");
    expect(routeSource).not.toContain("styles.worktreeRunPicker");
    expect(routeSource).not.toContain('t("worktreeReviewPanelTitle")');
  });

  it("routes current supervised live controls through worktree run authority", () => {
    const terminateHandler = routeSource.slice(
      routeSource.indexOf("const handleTerminateSupervisedRun"),
      routeSource.indexOf("const supervisedControlError"),
    );

    expect(routeSource).toContain("startWorktreeRunMutation");
    expect(runMutationsSource).toContain('"/api/evolution/worktree-runs"');
    expect(routeSource).toContain("approvalWorktreeActionMutation");
    expect(terminateHandler).toContain("if (supervisedWorktreeLiveRun)");
    expect(terminateHandler).toContain('action: "terminate"');
    expect(terminateHandler).toContain("approvalWorktreeActionMutation.mutate");
    expect(terminateHandler).not.toContain("terminateRunMutation.mutate");
    expect(routeSource).not.toContain("startRunMutation");
    expect(routeSource).not.toContain("supervisedStartCommand");
    expect(routeSource).not.toContain("pauseRunMutation");
    expect(routeSource).not.toContain("resumeRunMutation");
    expect(routeSource).not.toContain("retryRunMutation");
    expect(routeSource).not.toContain("terminateRunMutation");
    expect(routeSource).not.toContain("deleteRunMutation");
    expect(routeSource).not.toContain('fetchJson<EvolutionRunStartResponse>("/api/evolution/runs"');
    expect(routeSource).not.toContain("`/api/evolution/runs/${runId}/pause`");
    expect(routeSource).not.toContain("`/api/evolution/runs/${runId}/resume`");
    expect(routeSource).not.toContain("`/api/evolution/runs/${runId}/retry`");
    expect(routeSource).not.toContain("`/api/evolution/runs/${runId}/terminate`");
    expect(routeSource).not.toContain("`/api/evolution/runs/${runId}`");
  });

  it("merges supervised datasets and bundles into one source picker", () => {
    expect(routeSource).toContain("workbenchCatalogQuery");
    expect(routeSource).toContain("queryKeys.evolutionWorkbench()");
    expect(routeSource).toContain('"/api/evolution/workbench"');
    expect(routeSource).toContain("const workbenchControl = workbenchCatalogQuery.data");
    expect(routeSource).not.toContain("workbenchCatalogQuery.data ?? workspaceSnapshot?.workbench");
    expect(routeSource).toContain("workbenchCatalogLoading");
    expect(routeSource).toContain("sourceCatalogCountLabel");
    expect(routeSource).toContain("primaryDatasets");
    expect(routeSource).toContain("item.selectable !== false && item.effective");
    expect(routeSource).toContain("hiddenDatasetCount");
    expect(routeSource).toContain("supervisedSourceOptions");
    expect(routeSource).toContain('value: `dataset:${item.name}`');
    expect(routeSource).toContain('value: `bundle:${item.name}`');
    expect(routeSource).toContain("function datasetBenchmarkDetail");
    expect(routeSource).toContain("item.taskType");
    expect(routeSource).toContain("item.runBudgetClass");
    expect(routeSource).toContain("datasetBenchmarkDetail(item, lang)");
    expect(routeSource).toContain("数据集会先物化，评测包可直接运行。");
    expect(routeSource).toContain("sourceInventoryBar");
    expect(routeSource).toContain("primaryDatasets.map((item)");
  });

  it("surfaces the supervised evidence root from workbench storage metadata", () => {
    expect(evolutionTypesSource).toContain("export type EvolutionWorkbenchStorage");
    expect(evolutionTypesSource).toContain("storage?: EvolutionWorkbenchStorage");
    expect(routeSource).toContain("const workbenchStorage");
    expect(routeSource).toContain("workbenchStorage?.relativeEvidenceRoot");
    expect(routeSource).toContain("workbenchStorage?.activeEvidenceRoot");
  });

  it("keeps the runnable source picker separate from the full supervised benchmark catalog", () => {
    expect(evolutionTypesSource).toContain("datasetCatalog: EvolutionDatasetOption[]");
    expect(routeSource).toContain("const datasetCatalog = workbenchControl?.datasetCatalog");
    expect(routeSource).toContain("datasetCatalogGroups");
    expect(routeSource).toContain("selectedDatasetCatalogFilter");
    expect(routeSource).toContain("datasetCatalogPanel");
    expect(routeSource).toContain("item.visibilityReason");
    expect(routeSource).toContain("item.usabilityReason");
    expect(routeSource).toContain("datasetCatalogStatusLabel");
    expect(dictionarySource).toContain('datasetCatalog: "评测集目录"');
    expect(dictionarySource).toContain('datasetCatalogHiddenReason: "隐藏原因"');
    expect(routeStyles.datasetCatalogPanel).toContain("[max-height:min(238px,_34vh)]");
  });

  it("separates inconclusive terminal status and harness-only datasets from success wording", () => {
    expect(activeRunMonitorPanelSource).toContain('normalizedDecision === "INCONCLUSIVE"');
    expect(routeSource).toContain("<EvolutionActiveRunMonitorPanel");
    expect(routeSource).toContain("supervisedActiveRunMonitorRun");
    expect(activeRunMonitorPanelSource).toContain("function statusIcon");
    expect(activeRunMonitorPanelSource).toContain("statusIcon(run.controlSummary.status, run.controlSummary.decision)");
    expect(routeSource).toContain("monitoredStatusLabel");
    expect(routeSource).toContain("supervisedClosedLoopDecisionLabel");
    expect(routeSource).toContain("supervisedClosedLoopLedger");
    expect(activeRunMonitorPanelSource).toContain("EvolutionActiveRunClosedLoopLedgerPanel");
    expect(routeSource).toContain('status === "agent_harness_ready"');
    expect(routeSource).toContain('status === "custom_harness_ready"');
    expect(routeSource).toContain("自定义评测");
    expect(routeSource).toContain("非官方 Terminal-Bench 成绩");
    expect(routeSource).toContain("selectedSourceOfficialWarning");
    expect(routeSource).toContain('t("sourceOfficialVerifierWarning")');
    expect(routeSource).toContain("styles.sourceWarningStrip");
    expect(dictionarySource).toContain("Terminal-Bench 官方 Harbor 判分尚未接入");
    expect(routeStyles.sourceWarningStrip).toContain("var(--state-warning)");
  });

  it("keeps supervised rejection and runtime notes in governance wording instead of raw status codes", () => {
    expect(routeSource).toContain("function displaySupervisedTechnicalText");
    expect(routeSource).toContain("decision\\s*=\\s*REJECT");
    expect(routeSource).toContain("agent_judgment\\s+fail");
    expect(routeSource).toContain("风险 gate");
    expect(runRecordsPanelSource).toContain("tooltip={run.nextAction || undefined}");
    expect(runRecordsPanelSource).not.toContain('title={run.nextAction || ""}');
    expect(runRecordsPanelSource).toContain('content={selectedRun.outcomeSemantics.runtimeExplanation}');
    expect(runRecordsPanelSource).toContain('content={selectedRun.riskReasons.join(" / ")}');
    expect(runRecordsPanelSource).not.toContain('title={selectedRun.outcomeSemantics.runtimeExplanation}');
    expect(runRecordsPanelSource).not.toContain('title={selectedRun.riskReasons.join(" / ")}');
    expect(routeSource).toContain("proposalDetailQuery.data.supervised.riskReasons.join");
    expect(dictionarySource).toContain('supervisedFlowRunsHint: "同一改良 Agent 提建议并改候选"');
    expect(dictionarySource).toContain('decision: "治理结论"');
    expect(dictionarySource).toContain('diagnosis: "治理结论说明"');
    expect(dictionarySource).not.toContain('retrySupervisedRun: "重跑失败项"');
  });

  it("keeps supervised run records queue and detail composition in the extracted panel", () => {
    expect(routeSource).toContain('import { EvolutionRunRecordsPanel } from "./EvolutionRunRecordsPanel";');
    expect(routeSource).toContain("<EvolutionRunRecordsPanel");
    expect(routeSource).toContain("filteredRuns={filteredRuns}");
    expect(routeSource).toContain("selectedRun={selectedRun}");
    expect(routeSource).toContain("onRunAction={triggerRunAction}");
    expect(routeSource).toContain("onDeleteRunRecord={triggerRunRecordDelete}");
    expect(routeSource).toContain("bulkDeleteRunRecordsMutation");
    expect(routeSource).not.toContain("styles.runQueuePanel");
    expect(routeSource).not.toContain("styles.runDetailPanel");
    expect(routeSource).not.toContain("styles.runListScrollable");
    expect(routeSource).not.toContain("styles.runRecordIdentity");
    expect(routeSource).not.toContain("styles.runDetailOverview");
    expect(runRecordsPanelSource).toContain("export function EvolutionRunRecordsPanel");
    expect(runRecordsPanelSource).toContain("buildSupervisedRunRecordDisplay");
    expect(runRecordsPanelSource).toContain("styles.runQueuePanel");
    expect(runRecordsPanelSource).toContain("styles.runDetailPanel");
    expect(runRecordsPanelSource).toContain("styles.runRuntimeNote");
    expect(runRecordsPanelSource).not.toContain("useQuery");
    expect(runRecordsPanelSource).not.toContain("useMutation");
    expect(runRecordsPanelSource).not.toContain("queryClient");
    expect(runRecordsPanelStyles.runDetailOverview).toContain("grid-template-columns");
    expect(runRecordsPanelStylesSource).toContain("runQueuePanel");
    expect(runRecordsPanelStylesSource).toContain("runDetailOverview");
    expect(stylesSource).not.toContain("runQueuePanel");
    expect(stylesSource).not.toContain("runDetailOverview");
    expect(stylesSource).not.toContain("runRecordIdentity");
  });

  it("keeps run records as a dense queue/detail work surface instead of a card wall", () => {
    expect(runRecordsPanelStylesSource).not.toContain("surface-card");
    expect(runRecordsPanelStyles.surface).toContain("[border-radius:8px]");
    expect(runRecordsPanelStyles.runQueuePanel).toContain("[gap:8px]");
    expect(runRecordsPanelStyles.runDetailPanel).toContain("[gap:8px]");
    expect(runRecordsPanelStyles.runItem).toContain("[padding:7px_8px]");
    expect(runRecordsPanelStyles.runListScrollable).toContain("[max-height:min(520px,_52vh)]");
    expect(runRecordsPanelStyles.runDetailOverview).toContain("[grid-template-columns:minmax(168px,_0.36fr)_minmax(0,_1fr)]");
    expect(runRecordsPanelStyles.relatedList).toContain("repeat(2,_minmax(0,_1fr))");
    expect(runRecordsPanelStyles.inlineAction).toContain("[width:fit-content]");
    expect(runRecordsPanelStyles.inlineAction).toContain("[min-height:30px]");
  });

  it("keeps proposal action bands in the extracted panel while route owns mutations", () => {
    expect(routeSource).toContain('import { EvolutionProposalActionBandsPanel } from "./EvolutionProposalActionBandsPanel";');
    expect(routeSource).toContain("<EvolutionProposalActionBandsPanel");
    expect(routeSource).toContain("proposal={proposalDetailQuery.data}");
    expect(routeSource).toContain("actionError={actionMutation.error?.message ?? \"\"}");
    expect(routeSource).toContain("deleteProposalError={deleteProposalMutation.error?.message ?? \"\"}");
    expect(routeSource).toContain("onRunAction={triggerRunAction}");
    expect(routeSource).toContain("onDeleteProposal={triggerProposalDelete}");
    expect(routeSource).not.toContain("proposalDetailQuery.data.availableActions.map((action)");
    expect(proposalActionBandsPanelSource).toContain("export function EvolutionProposalActionBandsPanel");
    expect(proposalActionBandsPanelSource).toContain("proposal.availableActions.map((action)");
    expect(proposalActionBandsPanelSource).toContain("isDisabled={runLocked || actionPending}");
    expect(proposalActionBandsPanelSource).toContain("isDisabled={!proposal.canDelete || deleteProposalPending}");
    expect(proposalActionBandsPanelSource).not.toContain("useQuery");
    expect(proposalActionBandsPanelSource).not.toContain("useMutation");
    expect(proposalActionBandsPanelSource).not.toContain("queryClient");
    expect(proposalActionBandsStyles.detailSection).toContain("border-top");
    expect(proposalActionBandsStylesSource).toContain("relatedList");
  });

  it("keeps the latest finished supervised run out of the live monitor and into the closed-loop ledger", () => {
    expect(routeSource).toContain("queryKeys.evolutionWorkspaceSnapshot()");
    expect(routeSource).toContain('"/api/evolution/workspace-snapshot"');
    expect(routeSource).toContain("latestSupervisedRunSnapshot");
    expect(routeSource).toContain("const monitoredRun = effectiveActiveRunSnapshot");
    expect(routeSource).toContain("?? visibleLiveRunSnapshot;");
    expect(routeSource).not.toContain("const monitoredRun = effectiveActiveRunSnapshot\n    ?? visibleLiveRunSnapshot\n    ?? latestSupervisedRunSnapshot;");
    expect(routeSource).not.toContain("setLiveActiveRun(latestSupervisedRunSnapshot)");
    expect(routeSource).toContain("const supervisedMembersRun = monitoredRun");
    expect(routeSource).toContain("const currentSupervisedAgentBindings = workspaceSnapshot?.currentAgentBindings ?? EMPTY_AGENT_BINDINGS");
    expect(routeSource).toContain("const supervisedMembersBindings = supervisedMembersUseRunBindings");
    expect(routeSource).not.toContain("supervisedMembersRun = monitoredRun\n    ?? latestSupervisedRunSnapshot");
    expect(routeSource).not.toContain("latestSupervisedRunSnapshot?.agentBindings");
    expect(routeSource).toContain("const supervisedClosedLoopRecord");
    expect(routeSource).toContain("workspaceSnapshot?.latestClosedLoopRecord");
    expect(routeSource).not.toContain("styles.latestSupervisedResult");
    expect(routeSource).toContain("closedLoop: supervisedClosedLoopLedger");
    expect(routeSource).not.toContain("styles.closedLoopLedger");
    expect(activeRunMonitorPanelSource).toContain("styles.closedLoopLedger");
  });

  it("loads self-evolution history separately but current flow from worktree snapshot", () => {
    expect(routeSource).toContain("queryKeys.evolutionSelfOverview()");
    expect(routeSource).toContain('"/api/evolution/self/overview"');
    expect(routeSource).toContain("queryKeys.evolutionSelfTransactions()");
    expect(routeSource).toContain('"/api/evolution/self/transactions"');
    expect(routeSource).toContain("const selfOverview = selfOverviewQuery.data ?? workspaceSnapshot?.selfOverview");
    expect(routeSource).toContain("workspaceSnapshot?.selfWorktreeActiveRun");
    expect(routeSource).toContain("workspaceSnapshot?.selfWorktreeRuns");
    expect(routeSource).not.toContain("?? selfWorktreeRuns[0]");
    expect(routeSource).toContain("const selfTransactions = selfTransactionsQuery.data ?? workspaceSnapshot?.selfTransactions ?? []");
    expect(routeSource).toContain("const selfTrackLoading = selfTrackQueriesEnabled");
    expect(routeSource).toContain("overview={selfOverview}");
    expect(routeSource).toContain("worktreeRun={selfWorktreeRun}");
    expect(routeSource).toContain("transactions={selfTransactions}");
    expect(routeSource).toContain("loading={selfTrackLoading}");
    expect(routeSource).not.toContain("loading={workspaceSnapshotQuery.isLoading}");
    expect(routeSource).not.toContain("queryKeys.evolutionSelfLatestRun()");
    expect(routeSource).not.toContain('"/api/evolution/self/latest-run"');
    expect(routeSource).not.toContain("selfLatestRunQuery");
    expect(routeSource).not.toContain("workspaceSnapshot?.selfLatestRun");
  });

  it("keeps the latest self-observation run visible after it leaves the active slot", () => {
    expect(routeSource).toContain("selectedSelfObservationRunId");
    expect(runMutationsSource).toContain("options.setSelectedSelfObservationRunId(snapshot.runId)");
    expect(routeSource).toContain("queryKeys.evolutionSelfObservationRun(selectedSelfObservationRunId || \"__none__\")");
    expect(routeSource).toContain("`/api/evolution/self/observation-runs/${encodeURIComponent(selectedSelfObservationRunId)}`");
    expect(routeSource).toContain("const selfObservationRun = workspaceSnapshot?.selfObservationActiveRun");
    expect(routeSource).toContain("?? selectedSelfObservationRunQuery.data");
    expect(routeSource).toContain("observationRun={selfObservationRun ?? null}");
  });

  it("does not poll self-evolution detail endpoints while the supervised track is active", () => {
    expect(routeSource).toContain('const selfTrackQueriesEnabled = activeTrack === "self"');
    expect(routeSource).toContain('const supervisedTrackQueriesEnabled = activeTrack === "supervised"');
    expect(routeSource).toContain("enabled: selfTrackQueriesEnabled");
    expect(routeSource).not.toContain('const selfTrackQueriesEnabled = forcedTrack === "self" || forcedTrack === undefined');
  });

  it("loads the self-evolution track only after that track is shown", () => {
    expect(routeSource).toContain('import { EvolutionSelfTrackBoundary } from "./EvolutionSelfTrackBoundary";');
    expect(routeSource).toContain("<EvolutionSelfTrackBoundary");
    expect(routeSource).not.toContain("LazySelfEvolutionTrack");
    expect(routeSource).not.toContain('import("./SelfEvolutionTrack")');
    expect(routeSource).not.toContain("<Suspense");
    expect(routeSource).not.toContain('import { SelfEvolutionTrack } from "./SelfEvolutionTrack";');
    expect(selfTrackBoundarySource).toContain("LazySelfEvolutionTrack");
    expect(selfTrackBoundarySource).toContain('import("./SelfEvolutionTrack")');
    expect(selfTrackBoundarySource).toContain("<Suspense");
    expect(selfTrackBoundarySource).toContain("正在加载自进化工作台");
    expect(selfTrackBoundarySource).not.toContain("useQuery");
    expect(selfTrackBoundarySource).not.toContain("useMutation");
    expect(selfTrackBoundarySource).not.toContain("queryClient");
  });

  it("lets the self-evolution workspace fill the remaining viewport height", () => {
    expect(routeSource).toContain('const showRouteToolbar = activeTrack !== "self";');
    expect(routeSource).toContain('activeTrack === "self" ? `${styles.page} ${styles.selfPage}` : styles.page');
    expect(routeSource).toContain("{showRouteToolbar ? (");
    expect(routeStyles.page).toContain("[height:calc(100dvh_-_var(--shell-topbar-height))]");
    expect(routeStyles.page).toContain("[max-height:calc(100dvh_-_var(--shell-topbar-height))]");
    expect(routeStyles.selfPage).toMatch(/grid-template-rows:minmax\(0,?_?1fr\)/);
    expect(routeStyles.selfPage).toContain("[gap:0]");
    expect(selfTrackBoundaryStyles.selfModeStack).toMatch(/grid-rows-\[minmax\(0,1fr\)\]|grid-template-rows:minmax\(0,?_?1fr\)/);
    expect(selfTrackBoundaryStyles.selfModeStack).toMatch(/overflow-hidden|\[overflow:hidden\]/);
    expect(selfTrackBoundaryStyles.selfModeStack).not.toContain("auto_minmax(0,1fr)");
    expect(routeStyles.page).not.toContain("max-[900px]:[height:auto]");
    expect(routeStyles.page).not.toContain("max-[900px]:[overflow:visible]");
    expect(routeStyles.selfPage).toMatch(/max-\[900px\]:\[grid-template-rows:minmax\(0,?_?1fr\)\]/);
    expect(routeStyles.selfPage).toContain("max-[900px]:[gap:0]");
    expect(selfTrackBoundaryStyles.selfModeStack).toMatch(/max-\[900px\]:h-full|max-\[900px\]:\[height:100%\]/);
    expect(selfTrackBoundaryStyles.selfModeStack).toMatch(/max-\[900px\]:overflow-auto|max-\[900px\]:\[overflow:auto\]/);
    expect(selfTrackBoundaryStylesSource).toContain("structuredEmptyState");
  });

  it("keeps evolution tracks from duplicating their fixed agents as system Team canvases", () => {
    expect(routeSource).not.toContain("SELF_EVOLUTION_SYSTEM_TEAM_ID");
    expect(routeSource).not.toContain("SUPERVISED_EVOLUTION_SYSTEM_TEAM_ID");
    expect(routeSource).not.toContain('"self-evolution-team"');
    expect(routeSource).not.toContain('"supervised-evolution-team"');
    expect(routeSource).not.toContain("fetchEvolutionSystemTeam");
    expect(routeSource).not.toContain('fetchJson<TeamListPayload>("/api/teams")');
    expect(routeSource).not.toContain("fetchJson<Team>(`/api/teams/${encodeURIComponent(teamId)}`)");
    expect(routeSource).not.toContain("modeSystemTeamQuery");
    expect(routeSource).not.toContain("teamOrganizationCanvas(modeSystemTeam)");
    expect(routeSource).not.toContain("function renderModeTeamCanvasPanel()");
    expect(routeSource).not.toContain("renderModeTeamCanvasPanel()");
    expect(selfTrackBoundarySource).toContain("styles.selfModeStack");
    expect(routeSource).not.toContain("系统团队画布");
    expect(routeSource).not.toContain("自进化系统团队");
    expect(routeSource).not.toContain("监督进化系统团队");
  });

  it("keeps legacy supervised retry out of the current live controls", () => {
    expect(routeSource).not.toContain("retryRunMutation");
    expect(routeSource).not.toContain("`/api/evolution/runs/${runId}/retry`");
    expect(routeSource).not.toContain('t("retrySupervisedRun")');
  });

  it("routes active supervised worktree termination through worktree actions", () => {
    expect(routeSource).toContain("const supervisedWorktreeLiveRun = activeWorktreeRun && !isSelfEvolutionWorktreeRun(activeWorktreeRun)");
    expect(routeSource).toContain("const terminateWorktreeAction = supervisedWorktreeLiveRun?.actionStates?.terminate;");
    expect(routeSource).toContain('approvalWorktreeActionMutation.mutate({ runId: supervisedWorktreeLiveRun.runId, action: "terminate" });');
    expect(routeSource).toContain("const terminateSupervisedPending = approvalWorktreeActionMutation.isPending;");
    expect(routeSource).toContain("disabled: !canTerminateSupervisedRun");
    expect(routeSource).toContain("pending: terminateSupervisedPending");
    expect(activeRunMonitorPanelSource).toContain("isDisabled={run.termination.disabled || run.termination.pending}");
    expect(routeSource).not.toContain("terminateRunMutation.mutate(monitoredRun.runId);");
    expect(routeSource).not.toContain("legacyTerminateSupervisedAction");
  });

  it("keeps the supervised launch panel compact", () => {
    expect(routeSource).toContain("styles.supervisedRunConsole");
    expect(routeSource).toContain("styles.supervisedRunConsoleGrid");
    expect(routeSource).toContain("styles.supervisedRunSetup");
    expect(routeSource).toContain("styles.supervisedRunOptions");
    expect(routeSource).toContain("sourceMetaSide");
    expect(routeSource).toContain("数据集会先物化，评测包可直接运行。");
    expect(routeSource).toContain("startWorktreeRunMutation");
    expect(routeSource).toContain("SupervisedMentalModelMode");
    expect(routeSource).toContain("supervisedMentalModelMode");
    expect(routeSource).toContain("mentalModelMode: supervisedMentalModelMode");
    expect(routeSource).toContain('ariaLabel={t("supervisedMentalMode")}');
    expect(dictionarySource).toContain('supervisedMentalMode: "心智模式"');
  });

  it("uses action-oriented supervised section labels instead of internal system terms", () => {
    expect(dictionarySource).toContain('supervisedControl: "发起评测"');
    expect(dictionarySource).toContain('launchSupervisedRun: "选择来源并启动"');
    expect(dictionarySource).toContain('activeSupervisedRun: "现场进度"');
    expect(dictionarySource).toContain('runList: "结果列表"');
    expect(dictionarySource).toContain('runDetail: "结果详情"');
    expect(dictionarySource).toContain('libraryItems: "已记录建议"');
    expect(dictionarySource).toContain('pendingReview: "待处理建议"');
    expect(dictionarySource).toContain('workbenchContext: "当前评测入口"');
  });

  it("keeps the live launch panel focused on starting evaluations", () => {
    expect(routeSource).toContain("styles.liveLaunchStack");
    expect(routeSource).toContain("styles.closedLoopLaunchBlock");
    expect(routeSource).toContain('t("startClosedLoopRun")');
    expect(routeSource).not.toContain("styles.worktreeReviewSurface");
    expect(routeSource).not.toContain("worktreeReviewPanelHint");
    expect(routeStyles.liveLaunchStack).toContain("[grid-template-rows:minmax(0,_1fr)]");
    expect(routeStyles.launchSurface).toContain("[max-height:none]");
    expect(routeStyles.supervisedRunConsole).toContain("[container-type:inline-size]");
    expect(routeStyles.supervisedRunConsoleGrid).toContain("[grid-template-columns:minmax(0,_1fr)]");
  });

  it("shows a compact supervised workflow rail and center overview fallback", () => {
    expect(routeSource).toContain("SUPERVISED_WORKFLOW_STEPS");
    expect(routeSource).toContain('{ id: "baseline_eval", zh: "基线评测", en: "Baseline", role: "baseline" }');
    expect(routeSource).toContain('{ id: "improve", zh: "提出建议与改良", en: "Improve", role: "candidate" }');
    expect(routeSource).toContain('{ id: "rerun_score", zh: "复跑与评分", en: "Rerun + Score", role: "candidate" }');
    expect(routeSource).toContain('{ id: "approval", zh: "用户审批", en: "Approval", role: null }');
    expect(routeSource).not.toContain('{ id: "results", zh: "运行结果"');
    expect(routeSource).not.toContain('{ id: "proposal", zh: "改进提案"');
    expect(routeSource).not.toContain('{ id: "review", zh: "样本评审"');
    expect(evolutionTypesSource).toContain("export type EvolutionWorkflowStep");
    expect(evolutionTypesSource).toContain("workflowSteps?: EvolutionWorkflowStep[]");
    expect(routeSource).toContain("selectedSupervisedWorkflowStepId");
    expect(routeSource).toContain("supervisedRuntimeWorkflowStepId");
    expect(routeSource).toContain("supervisedSelectedWorkflowStep");
    expect(routeSource).toContain("supervisedWorkflowManualSelection");
    expect(routeSource).toContain("supervisedWorkflowCards");
    expect(routeSource).toContain("approvalEvidenceItems");
    expect(routeSource).toContain("最终运行结果");
    expect(routeSource).toContain("改进提案");
    expect(routeSource).toContain("样本评审");
    expect(routeSource).toContain("用户审批");
    expect(routeSource).toContain("supervisedRunMembers");
    expect(routeSource).toContain("hasSupervisedAgentBindings");
    expect(routeSource).toContain("currentSupervisedAgentBindings");
    expect(routeSource).toContain("const bindings = supervisedMembersBindings");
    expect(routeSource).toContain("supervisedMembersRun?.currentAgentBinding?.agentId");
    expect(routeSource).toContain("binding?.dialogueModelLabel || binding?.dialogueModelName");
    expect(routeSource).toContain("modelDisplayLabel(supervisedMemberModelId(binding), resolveModelLabel)");
    expect(routeSource).toContain("configQuery.data?.modelLabels");
    expect(routeSource).toContain("EvolutionRoleConversationSession");
    expect(evolutionTypesSource).toContain("roleConversationSessions?: Record<string, EvolutionRoleConversationSession>");
    expect(routeSource).toContain("function supervisedMemberChatRoute");
    expect(routeSource).toContain("const roleSessions = supervisedMembersRun?.roleConversationSessions ?? {}");
    expect(routeSource).toContain("const conversationSession = roleSessions[role]");
    expect(routeSource).toContain("conversationSessionId");
    expect(routeSource).toContain("chatRoute: supervisedMemberChatRoute");
    expect(routeSource).toContain("configRoute: agentId ? supervisedMemberAgentManagementRoute");
    expect(routeSource).toContain("member.chatRoute");
    expect(routeSource).toContain("打开监督成员");
    expect(routeSource).toContain("返回监督进化");
    expect(routeSource).toContain("selectedWorkflowConversationMessages");
    expect(routeSource).toContain("selectedWorkflowHasConversationMessages");
    expect(routeSource).toContain("LazyConversationView");
    expect(routeSource).toContain("approvalWorktreeActionMutation");
    expect(routeSource).toContain('action: "approve_review"');
    expect(routeSource).toContain('action: "merge"');
    expect(routeSource).toContain("reviewCandidateWorktree?.actionStates?.approveReview?.enabled");
    expect(routeSource).toContain("reviewCandidateWorktree?.actionStates?.merge?.enabled");
    expect(routeSource).toContain("supervisedMemberAgentManagementRoute");
    expect(routeSource).toContain('new URLSearchParams({ pane: "config", returnLabel: "supervised_evolution" })');
    expect(routeSource).toContain('params.set("agent", normalizedAgentId)');
    expect(routeSource).toContain('params.set("returnTo", normalizedReturnTo)');
    expect(routeSource).toContain("const supervisedMemberReturnTo = `${location.pathname}${location.search}`");
    expect(routeSource).toContain("<ArrowUpRight size={13} aria-hidden=\"true\" />");
    expect(routeSource).toContain("onClick={() => setSelectedSupervisedWorkflowStepId(step.id)}");
    expect(routeSource).toContain("aria-pressed={selected}");
    expect(routeSource).toContain("setSelectedSupervisedWorkflowStepId(null)");
    expect(routeSource).toContain("跟随现场");
    expect(routeSource).toContain("styles.supervisedWorkflowPanel");
    expect(routeSource).toContain("styles.workflowStepRail");
    expect(routeSource).toContain("styles.workflowStepButton");
    expect(routeSource).toContain("styles.workflowStepButtonActive");
    expect(routeSource).toContain("styles.workflowStepPreview");
    expect(routeSource).toContain("selectedWorkflowOverviewItems");
    expect(routeSource).toContain("selectedWorkflowEvidenceItems");
    expect(routeSource).toContain("styles.caseOverviewWorkspace");
    expect(routeSource).toContain("styles.caseOverviewEvidence");
    expect(routeSource).toContain("styles.caseOverviewEvidenceGrid");
    expect(routeSource).toContain("selectedWorkflowHasConversationMessages ? (");
    expect(routeSource).not.toContain("styles.supervisedWorkflowCardGrid");
    expect(routeSource).not.toContain("styles.supervisedWorkflowCardButton");
    expect(routeSource).not.toContain("styles.supervisedWorkflowCardFooter");
    expect(routeSource).toContain("监督进化步骤导航");
    expect(routeStyles.supervisedWorkflowPanel).toContain("[overflow:hidden]");
    expect(routeStyles.workflowStepRail).toContain("[max-height:min(196px,_30vh)]");
    expect(routeStyles.workflowStepButton).toContain("hover:[border-color:");
    expect(routeStyles.workflowStepButton).toContain("[background:var(--vui-surface-row)]");
    expect(routeStyles.workflowStepButton).toContain("w-full");
    expect(routeStyles.workflowStepButtonActive).toContain("[border-color:");
    expect(routeStyles.workflowStepPreview).toContain("[-webkit-line-clamp:2]");
    expect(routeStyles.caseOverviewWorkspace).toContain("[grid-template-rows:auto_minmax(120px,_1fr)]");
    expect(routeStyles.caseOverviewWorkspace).toContain("[background-image:linear-gradient(to_right");
    expect(routeStyles.caseOverviewWorkspace).toContain("linear-gradient(to_bottom");
    expect(routeStyles.caseOverviewWorkspace).toContain("[background-size:40px_40px]");
    expect(routeStyles.caseOverviewItem).toContain("grid");
    expect(routeStyles.caseOverviewEvidence).toContain("[grid-template-rows:auto_minmax(120px,_1fr)_auto]");
    expect(routeStyles.caseOverviewEvidenceGrid).toContain("[grid-template-columns:repeat(4,_minmax(0,_1fr))]");
    expect(routeSource).toContain("styles.caseOverviewEmptyState");
    expect(routeStyles.caseOverviewEmptyState).toContain("min-h-[120px]");
    expect(routeStyles.caseOverviewEmptyState).toContain("[place-items:center]");
    expect(stylesSource).not.toContain(".supervisedWorkflowCardGrid");
    expect(stylesSource).not.toContain(".supervisedWorkflowCardButton");
    expect(stylesSource).not.toContain(".supervisedWorkflowCardFooter");
    expect(routeStyles.supervisedWorkflowFollowButton).toContain("[min-height:24px]");
  });

  it("shows immediate local feedback while a supervised worktree run is waiting for the run record", () => {
    expect(routeSource).toContain("LOCAL_SUPERVISED_RUN_PREFIX");
    expect(routeSource).toContain("buildSupervisedStartPlaceholder");
    expect(routeSource).toContain("isLocalSupervisedStartPlaceholder");
    expect(runMutationsSource).toContain("onMutate: () =>");
    expect(runMutationsSource).toContain("启动请求已提交，正在等待运行记录刷新。");
    expect(runMutationsSource).toContain("options.setLiveActiveRun(");
    expect(runMutationsSource).toContain("options.buildSupervisedStartPlaceholder({");
    expect(routeSource).toContain("placeholderAgentBindings:");
    expect(routeSource).toContain("activeRunSnapshot?.agentBindings");
    expect(routeSource).toContain("?? workspaceSnapshotQuery.data?.currentAgentBindings");
    expect(routeSource).toContain("?? EMPTY_AGENT_BINDINGS");
    expect(runMutationsSource).toContain("agentBindings: payload.placeholderAgentBindings");
    expect(routeSource).not.toContain("latestSupervisedRunSnapshot?.agentBindings ?? {}");
    expect(runMutationsSource).toContain("await options.afterWorktreeRunChanged()");
    expect(runMutationsSource).toContain("void options.afterWorktreeRunChanged()");
    expect(routeSource).not.toContain("isEvolutionRunCommandAccepted");
    expect(routeSource).toContain("visibleLiveRunSnapshot");
    expect(routeSource).toContain("const streamLiveRun = isLocalSupervisedStartPlaceholder(liveActiveRun) ? null : liveActiveRun");
    expect(runMutationsSource).toContain("options.setLiveActiveRun((current: any) =>");
    expect(runMutationsSource).toContain(
      "options.isLocalSupervisedStartPlaceholder(current) ? null : current,",
    );
    expect(routeSource).toContain("const supervisedStartSubmitting = startWorktreeRunMutation.isPending || isLocalSupervisedStartPlaceholder(liveActiveRun)");
    expect(routeSource).toContain("onClick={() => startWorktreeRunMutation.mutate()}");
    expect(runMutationsSource).toContain('executionMode: "real"');
    expect(runMutationsSource).toContain("confirmRealLlmCost: true");
    expect(routeSource).toContain("监督运行中");
    expect(routeSource).toContain("supervisedStartButtonLabel");
  });

  it("keeps supervised closed-loop review in a dedicated ledger projection", () => {
    expect(evolutionTypesSource).toContain("export type EvolutionClosedLoopRecord");
    expect(evolutionTypesSource).toContain("export type EvolutionClosedLoopRoleSession");
    expect(evolutionTypesSource).toContain("closedLoopRecord?: EvolutionClosedLoopRecord | null");
    expect(evolutionTypesSource).toContain("latestClosedLoopRecord: EvolutionClosedLoopRecord | null");
    expect(routeSource).toContain("const supervisedClosedLoopRecord");
    expect(routeSource).toContain("workspaceSnapshot?.latestClosedLoopRecord");
    expect(routeSource).toContain("const supervisedClosedLoopLedger");
    expect(routeSource).toContain("closedLoop: supervisedClosedLoopLedger");
    expect(activeRunMonitorPanelSource).toContain("styles.closedLoopLedger");
    expect(activeRunMonitorPanelSource).toContain("styles.closedLoopLedgerEvidenceGrid");
    expect(routeSource).toContain("闭环记录库");
    expect(routeSource).toContain("审查入口");
    expect(routeSource).toContain("supervisedClosedLoopRecord.nextAction");
    expect(routeSource).toContain("supervisedClosedLoopProposalCount");
  });

  it("keeps the active run monitor DOM and local styles in the extracted display panel", () => {
    expect(routeSource).toContain("<EvolutionActiveRunMonitorPanel");
    expect(routeSource).toContain("const supervisedActiveRunMonitorMetrics");
    expect(routeSource).toContain("const supervisedActiveRunMonitorEvents");
    expect(routeSource).toContain("const supervisedActiveRunMonitorRun");
    expect(routeSource).not.toContain("function statusIcon");
    expect(routeSource).not.toContain("RUN_SUMMARY_TONE_CLASS");
    expect(routeSource).not.toContain("styles.runMonitorDense");
    expect(routeSource).not.toContain("styles.eventListScrollable");
    expect(routeSource).not.toContain("styles.runNextActionStrip");
    expect(activeRunMonitorPanelSource).toContain("RUN_SUMMARY_TONE_CLASS");
    expect(activeRunMonitorPanelSource).toContain("<VButton");
    expect(activeRunMonitorPanelSource).toContain("styles.runMonitorDense");
    expect(activeRunMonitorPanelSource).toContain("styles.eventListScrollable");
    expect(activeRunMonitorPanelSource).toContain("styles.runNextActionStrip");
    expect(activeRunMonitorStylesSource).toContain("runMonitorDense");
    expect(activeRunMonitorStylesSource).toContain("closedLoopLedgerEvidenceGrid");
    expect(stylesSource).not.toContain("runMonitorDense");
    expect(stylesSource).not.toContain("eventListScrollable");
  });

  it("keeps the extracted active-run monitor compact and background-aware", () => {
    expect(activeRunMonitorStylesSource).not.toContain("surface-card");
    expect(activeRunMonitorStyles.runMonitorDense).toContain("[gap:6px]");
    expect(activeRunMonitorStyles.idleMonitor).toContain("[gap:6px]");
    expect(activeRunMonitorStyles.metricTile).toContain("[min-height:32px]");
    expect(activeRunMonitorStyles.metricTile).toContain("[padding:4px_6px]");
    expect(activeRunMonitorStyles.eventListScrollable).toContain("[max-height:min(180px,_24vh)]");
    expect(activeRunMonitorStyles.liveRunToolbar).toContain("[padding:6px]");
    expect(activeRunMonitorStyles.compactTextAction).toContain("[width:fit-content]");
    expect(activeRunMonitorStyles.compactTextAction).toContain("[max-width:160px]");
    expect(activeRunMonitorStyles.closedLoopLedger).toContain("[background:color-mix(in_srgb,_var(--accent-cool)_7%,_var(--vui-surface-row))]");
  });

  it("explains closed-loop launch and dataset case limits without changing review actions", () => {
    expect(routeSource).toContain('t("caseLimitHint")');
    expect(routeSource).toContain("styles.closedLoopLaunchBlock");
    expect(routeSource).toContain('t("closedLoopLaunchPanelTitle")');
    expect(routeSource).toContain('t("closedLoopLaunchPanelHint")');
    expect(routeSource).toContain("disabledReason={supervisedStartDisabledReason}");
    expect(routeSource).toContain("disabledReason={simulationStartDisabledReason}");
    expect(routeSource).not.toContain('title={t("caseLimitHint")}');
    expect(routeSource).not.toContain('title={t("closedLoopLaunchPanelHint")}');
    expect(routeSource).toContain("styles.closedLoopModeBadge");
    expect(routeSource).toContain("当前只演练编排链路，不调用真实 LLM 自改。");
    expect(dictionarySource).toContain("结果会进入下方候选审核，不会自动合并。");
    expect(routeStyles.closedLoopLaunchBlock).toContain("[grid-template-columns:minmax(0,_1fr)_minmax(92px,_auto)]");
    expect(routeStyles.closedLoopModeBadge).toContain("[border-radius:999px]");
  });

  it("keeps the supervised live console as a dense desktop split before narrow layouts", () => {
    expect(routeStyles.overviewGrid).toContain("[grid-template-columns:minmax(300px,_var(--evolution-live-launch-width,_348px))");
    expect(routeStyles.overviewGrid).toContain("[grid-template-rows:minmax(0,_1fr)]");
    expect(routeStyles.overviewGrid).not.toContain("grid-template-areas");
    expect(routeStyles.overviewGrid).not.toContain("--evolution-overview-areas");
    expect(routeStyles.dashboardLaunch).toContain("[grid-column:1]");
    expect(routeStyles.dashboardLaunch).toContain("[grid-row:1]");
    expect(routeStyles.liveResizeHandleLaunch).toContain("[grid-column:2]");
    expect(routeStyles.liveResizeHandleLaunch).toContain("[grid-row:1]");
    expect(routeStyles.dashboardIo).toContain("[grid-column:3]");
    expect(routeStyles.dashboardIo).toContain("[grid-row:1]");
    expect(routeStyles.liveResizeHandleRun).toContain("[grid-column:4]");
    expect(routeStyles.liveResizeHandleRun).toContain("[grid-row:1]");
    expect(routeStyles.dashboardRun).toContain("[grid-column:5]");
    expect(routeStyles.dashboardRun).toContain("[grid-row:1]");
  });

  it("keeps supervised split resize handles on the shared collapse-resize contract", () => {
    expect(routeStyles.resizeHandle).toContain("max-[1200px]:hidden");
    expect(routeSource).toContain("PaneCollapseHandle");
  });

  it("keeps supervised run empty states compact for first-viewport scanning", () => {
    expect(routeStyles.structuredEmptyState).toContain("[min-height:86px]");
    expect(routeStyles.structuredEmptyState).toContain("[padding:10px_12px]");
    expect(routeStyles.structuredEmptyState).not.toContain("[min-height:220px]");
  });

  it("uses denser supervised launch and member panels at narrow workbench widths", () => {
    expect(routeStyles.overviewGrid).toContain("minmax(300px,_var(--evolution-live-launch-width,_348px))");
    expect(routeStyles.overviewGrid).toContain("minmax(300px,_var(--evolution-live-run-width,_360px))");
    expect(routeStyles.supervisedRunConsole).toContain("[container-type:inline-size]");
    expect(routeStyles.supervisedRunConsoleGrid).toContain("[@container(min-width:560px)]:[grid-template-columns:minmax(0,_1.08fr)_minmax(214px,_0.72fr)]");
    expect(routeStyles.supervisedRunConsoleGrid).toContain("[@container(min-width:560px)]:[align-items:start]");
    expect(routeStyles.overviewGrid).toContain("[grid-template-rows:minmax(0,_1fr)]");
    expect(routeStyles.overviewGrid).not.toContain("[grid-template-rows:minmax(0,_auto)_minmax(0,_0.9fr)_minmax(150px,_0.82fr)]");
    expect(routeStyles.overviewGrid).not.toContain("[grid-template-rows:minmax(0,_auto)_minmax(156px,_0.86fr)_minmax(150px,_0.74fr)]");
    expect(routeStyles.launchSurface).not.toContain("[max-height:min(430px,_60vh)]");
    expect(routeStyles.noticeText).toContain("max-[1200px]:hidden");
    expect(routeStyles.formHint).toContain("max-[1200px]:hidden");
    expect(routeStyles.sourceInventoryBar).not.toContain("max-[1200px]:hidden");
    expect(routeStyles.sourceMetaCompact).not.toContain("max-[1200px]:hidden");
    expect(routeStyles.supervisedMembersList).toContain("[max-height:min(118px,_22vh)]");
    expect(routeStyles.supervisedMembersList).toContain("[@container(min-width:560px)]:[max-height:min(238px,_34vh)]");
    expect(routeStyles.supervisedMemberRow).toContain("[min-height:34px]");
    expect(routeStyles.supervisedMemberRow).not.toContain("[min-height:40px]");
    expect(routeStyles.supervisedMemberIdentity).toContain("[font-family:var(--font-mono)]");
    expect(routeStyles.supervisedMembersPanel).not.toContain("[align-self:end]");
  });

  it("switches the supervised live grid to a single-column flow below tablet width", () => {
    expect(routeStyles.overviewGrid).toContain("max-[900px]:[grid-template-rows:max-content_max-content_max-content]");
    expect(routeStyles.dashboardIo).toContain("max-[900px]:[grid-row:1]");
    expect(routeStyles.dashboardLaunch).toContain("max-[900px]:[grid-row:2]");
    expect(routeStyles.dashboardRun).toContain("max-[900px]:[grid-row:3]");
    expect(routeStyles.overviewGrid).toContain("max-[900px]:[align-content:start]");
    expect(routeStyles.overviewGrid).toContain("max-[900px]:[height:auto]");
    expect(routeStyles.overviewGrid).toContain("max-[900px]:[overflow:auto]");
    expect(routeStyles.liveLaunchStack).toContain("max-[900px]:[grid-auto-rows:max-content]");
    expect(routeStyles.launchSurface).toContain("max-[900px]:[height:max-content]");
    expect(routeStyles.launchSurface).toContain("max-[900px]:[min-height:max-content]");
    expect(routeStyles.launchSurface).toContain("max-[900px]:[overflow:visible]");
    expect(routeStyles.supervisedMembersList).toContain("max-[900px]:[grid-template-columns:repeat(2,_minmax(0,_1fr))]");
  });

  it("lets the embedded supervised conversation fill the lower vertical space", () => {
    expect(routeSource).toContain("styles.caseConversationShell");
    expect(routeSource).toContain("styles.caseConversationTranscript");
    expect(routeSource).toContain("styles.caseRawEvidence");
    expect(routeSource).toContain("currentCaseOutputLabel(monitoredRun)");
    expect(routeStyles.caseConversationShell).toContain("[flex:1_1_0]");
    expect(routeStyles.caseConversationTranscript).toContain("[flex:1_1_0]");
    expect(routeStyles.caseConversationTranscript).toContain("[height:100%]");
    expect(routeStyles.caseConversationTranscript).toContain("[background:transparent_!important]");
    expect(routeStyles.caseRawEvidence).toContain("[max-height:none]");
    expect(routeStyles.supervisedConversationTrace).toContain("[max-height:min(260px,_30vh)]");
    expect(routeStyles.supervisedConversationTrace).not.toContain("[max-height:340px]");
    expect(routeStyles.ioSurface).toContain("[position:relative]");
    // Wave 6A: height chrome lives on PaneHeightResizeHandle, not route style maps.
    expect(routeSource).toContain("PaneHeightResizeHandle");
    expect(routeSource).not.toContain("styles.liveIoResizeHandleLine");
    expect(routeStyles.liveIoResizeHandle).not.toContain("cursor-row-resize");
    expect(routeStyles.liveIoResizeHandle).not.toContain("before:");
  });

  it("shows environment preflight failures instead of waiting for agent output forever", () => {
    expect(routeSource).toContain("supervisedPreflightIssue(monitoredRun, lang)");
    expect(routeSource).toContain("任务环境预检失败，未启动 Agent");
    expect(routeSource).toContain("missing_verifier_dependency");
    expect(routeSource).toContain("monitoredPreflightIssue ? (");
    expect(routeSource).toContain("styles.casePreflightIssue");
    expect(routeStyles.casePreflightIssue).toContain("var(--state-warning)");
  });

  it("keeps supervised launch from reserving an empty worktree-review track", () => {
    expect(routeStyles.liveLaunchStack).toContain("[grid-template-rows:minmax(0,_1fr)]");
    expect(routeStyles.liveLaunchStack).toContain("[overflow:hidden]");
    expect(routeStyles.launchSurface).toContain("[max-height:none]");
    expect(routeStyles.launchSurface).not.toContain("[max-height:min(430px,_60vh)]");
    expect(stylesSource).not.toContain(".worktreeReviewSurface");
    expect(worktreeReviewStylesSource).toContain("worktreeReviewSurfaceClass");
  });

  it("hides the supervised toolbar intro with content-sized chrome (no full-width empty band)", () => {
    expect(routeSource).toContain('const hideSupervisedToolbarIntro = activeTrack === "supervised"');
    expect(routeSource).toContain("hideIntro={hideSupervisedToolbarIntro}");
    expect(routeSource).toContain("styles.toolbarSupervisedFocus");
    expect(routeSource).not.toContain("styles.toolbarHeaderHidden");
    // Do not stack generic `toolbar` (flex-wrap full row) on top of hideIntro chrome.
    expect(routeSource).not.toContain("`${styles.toolbar} ${styles.toolbarSupervisedFocus}`");
    expect(routeSource).toContain("hideSupervisedToolbarIntro");
    expect(routeSource).toContain("styles.toolbarControlsSupervisedFocus");
    expect(routeSource).toContain("aria-label={routeTitle}");
    expect(routeStyles.toolbarSupervisedFocus).toContain("w-fit");
    expect(routeStyles.toolbarSupervisedFocus).toContain("justify-self-end");
    expect(routeStyles.toolbarSupervisedFocus).toContain("self-start");
    expect(routeStyles.toolbarSupervisedFocus).toContain("flex-nowrap");
    expect(routeStyles.toolbarControls).toContain("[justify-content:flex-end]");
    expect(routeStyles.toolbarControls).toContain("max-[900px]:[justify-content:stretch]");
    expect(routeStyles.toolbarControls).not.toContain("[flex:1_1_100%]");
    expect(routeStyles.toolbarControlsSupervisedFocus).toContain("items-center");
    expect(routeStyles.toolbarControlsSupervisedFocus).toContain("w-fit");
    expect(routeStyles.toolbarControlsSupervisedFocus).toContain("max-w-full");
    expect(routeStyles.toolbarControlsSupervisedFocus).toContain("shrink-0");
    expect(routeStyles.toolbarControlsSupervisedFocus).not.toContain("[flex:1_1_100%]");
    // max-w-full is fine; avoid full-width stretch class ` w-full` / leading w-full.
    expect(routeStyles.toolbarControlsSupervisedFocus.split(/\s+/)).not.toContain("w-full");
    expect(routeStyles.toolbarControlsSupervisedFocus).toContain("justify-end");
  });

  it("keeps the supervised center pane as a read-only embedded conversation surface", () => {
    expect(routeSource).toContain("LazyConversationView");
    expect(routeSource).toContain("monitoredCaseConversationMessages");
    expect(routeSource).toContain("selectedWorkflowConversationMessages");
    expect(routeSource).toContain("selectedWorkflowIsRuntimeStep");
    expect(routeSource).toContain("selectedWorkflowConversationNotice");
    expect(routeSource).toContain("supervisedLiveConversationSupplement");
    expect(routeSource).toContain("showComposer={false}");
    expect(routeSource).toContain("showSessionOverview={Boolean(supervisedLiveConversationSupplement)}");
    expect(routeSource).toContain("supplementalContent={supervisedLiveConversationSupplement}");
    expect(routeSource).toContain("styles.caseConversationShell");
    expect(routeSource).toContain("styles.caseConversationTranscript");
    expect(routeStyles.caseConversationShell).toContain("[flex:1_1_0]");
    expect(routeStyles.caseConversationShell).toContain("[background-image:linear-gradient(to_right");
    expect(routeStyles.caseConversationShell).toContain("linear-gradient(to_bottom");
    expect(routeStyles.caseConversationShell).toContain("[background-size:40px_40px]");
    expect(routeStyles.caseConversationTranscript).toContain("[height:100%]");
    expect(routeStyles.caseConversationFallback).toContain("[place-items:center]");
    expect(routeStyles.supervisedConversationEvidence).toContain("[width:100%]");
    expect(routeStyles.supervisedConversationTrace).toContain("[max-height:min(260px,_30vh)]");
    expect(routeSource).not.toContain("styles.ioWaitingState");
    expect(routeSource).toContain("buildSupervisedCaseTraceItems");
    expect(routeSource).toContain("caseTraceItemExpanded");
    expect(routeSource).toContain("toggleCaseTraceItem");
    expect(routeSource).toContain("renderCaseTraceSection");
    expect(routeSource).toContain("styles.caseTraceTimeline");
    expect(routeSource).toContain("caseTraceTimelineRef");
    expect(routeSource).toContain("latestCaseTraceKey");
    expect(routeSource).toContain("timeline.scrollTop = timeline.scrollHeight");
    expect(routeSource).toContain("styles.caseTraceStack");
    expect(routeSource).toContain("styles.caseTraceMessage");
    expect(routeSource).toContain("styles.caseTraceMeta");
    expect(routeStyles.caseTraceTimeline).toContain("[content:\"\"]");
    expect(routeStyles.caseTraceStack).toContain("[justify-content:flex-end]");
    expect(routeStyles.caseTraceSummary).toContain("[grid-template-columns:26px_minmax(0,_1fr)_auto_18px]");
    expect(routeStyles.caseTraceMessage).toContain("grid");
    expect(routeStyles.caseTraceMeta).toContain("[align-items:flex-end]");
    expect(routeStyles.caseTracePreview).toContain("[-webkit-line-clamp:2]");
    expect(routeStyles.caseTraceStateGrid).toContain("grid");
  });

  it("keeps the proposal library summary in three columns at common desktop widths", () => {
    expect(routeStyles.librarySummaryBar).toContain("[grid-template-columns:minmax(0,_1.1fr)_minmax(0,_0.9fr)_minmax(0,_1fr)]");
    expect(routeStyles.librarySummaryBar).toContain("max-[1360px]:[grid-template-columns:minmax(0,_1fr)_minmax(0,_0.85fr)_minmax(0,_0.95fr)]");
    expect(routeStyles.librarySummaryBar).toContain("max-[1100px]:[grid-template-columns:1fr]");
  });

  it("keeps restored EvolutionRoute grids from the CSS module migration", () => {
    const restoredGridExpectations: Array<[string, string]> = [
      [routeStyles.sourceMetaCompact, "[grid-template-columns:minmax(0,_1fr)_minmax(96px,_auto)]"],
      [routeStyles.supervisedRunOptions, "[grid-template-columns:minmax(0,_0.95fr)_minmax(126px,_1.05fr)]"],
      [routeStyles.datasetCatalogItem, "[grid-template-columns:minmax(0,_1fr)_auto]"],
      [routeStyles.caseTraceSummary, "[grid-template-columns:26px_minmax(0,_1fr)_auto_18px]"],
      [activeRunMonitorStyles.closedLoopLedgerEvidenceGrid, "[grid-template-columns:repeat(2,_minmax(0,_1fr))]"],
    ];

    for (const [className, gridTemplate] of restoredGridExpectations) {
      expect(className).toContain("grid");
      expect(className).toContain(gridTemplate);
    }

    expect(routeStyles.toolbar).toContain("flex");
    expect(routeStyles.toolbar).toContain("max-[900px]:grid");
    expect(routeStyles.toolbar).toContain("max-[900px]:[grid-template-columns:1fr]");
  });

  it("does not put long live supervised text into native title tooltips", () => {
    expect(routeSource).not.toContain("title={monitoredRun.latestMessage}");
    expect(routeSource).not.toContain("title={monitoredTaskLabel}");
    expect(routeSource).not.toContain("title={entry.content}");
  });
});
