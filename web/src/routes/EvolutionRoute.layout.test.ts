import { describe, expect, it } from "vitest";

// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { readFileSync } from "node:fs";
import routeSource from "./EvolutionRoute.tsx?raw";

const stylesSource = readFileSync(new URL("./EvolutionRoute.module.css", import.meta.url), "utf-8");
const worktreeReviewStylesSource = readFileSync(new URL("./SupervisedWorktreeReviewPanel.module.css", import.meta.url), "utf-8");
const dictionarySource = readFileSync(new URL("../i18n/dictionary.ts", import.meta.url), "utf-8");

describe("EvolutionRoute library user flow contract", () => {
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
    const disabledSelectionCount = routeSource.match(/disabled={!item\.canDelete}/g)?.length ?? 0;
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

  it("routes risky self-evolution writes into the supervised worktree endpoint", () => {
    expect(routeSource).toContain("startSelfWorktreeRunMutation");
    expect(routeSource).toContain('"/api/evolution/self/worktree-runs"');
    expect(routeSource).toContain('mode: "manual"');
    expect(routeSource).toContain("onStartWorktreeRun={() => startSelfWorktreeRunMutation.mutate()}");
    expect(routeSource).toContain("startWorktreeError={startSelfWorktreeRunMutation.error?.message ?? \"\"}");
  });

  it("keeps candidate worktree review out of the live left rail", () => {
    expect(routeSource).toContain("startWorktreeRunMutation");
    expect(routeSource).toContain('"/api/evolution/worktree-runs"');
    expect(routeSource).not.toContain("SupervisedWorktreeReviewPanel");
    expect(routeSource).not.toContain("worktreeActionMutation");
    expect(routeSource).not.toContain("triggerWorktreeReviewApproval");
    expect(routeSource).not.toContain("triggerWorktreeAction");
    expect(routeSource).not.toContain("selectedWorktreeRunId");
    expect(routeSource).not.toContain("styles.worktreeRunPicker");
    expect(routeSource).not.toContain('t("worktreeReviewPanelTitle")');
  });

  it("merges supervised datasets and bundles into one source picker", () => {
    expect(routeSource).toContain("primaryDatasets");
    expect(routeSource).toContain("item.selectable !== false && item.effective");
    expect(routeSource).toContain("hiddenDatasetCount");
    expect(routeSource).toContain("supervisedSourceOptions");
    expect(routeSource).toContain('value: `dataset:${item.name}`');
    expect(routeSource).toContain('value: `bundle:${item.name}`');
    expect(routeSource).toContain("数据集会先物化，评测包可直接运行。");
    expect(routeSource).toContain("sourceInventoryBar");
    expect(routeSource).toContain("primaryDatasets.map((item)");
  });

  it("separates inconclusive terminal status and harness-only datasets from success wording", () => {
    expect(routeSource).toContain('normalizedDecision === "INCONCLUSIVE"');
    expect(routeSource).toContain("statusIcon(monitoredRun.status, monitoredRun.decision)");
    expect(routeSource).toContain("monitoredStatusLabel");
    expect(routeSource).toContain("latestRunStatusLabel");
    expect(routeSource).toContain("latestSupervisedResult");
    expect(routeSource).toContain('status === "agent_harness_ready"');
    expect(routeSource).toContain('status === "custom_harness_ready"');
    expect(routeSource).toContain("自定义评测");
    expect(routeSource).toContain("非官方 Terminal-Bench 成绩");
    expect(routeSource).toContain("selectedSourceOfficialWarning");
    expect(routeSource).toContain('t("sourceOfficialVerifierWarning")');
    expect(routeSource).toContain("styles.sourceWarningStrip");
    expect(dictionarySource).toContain("Terminal-Bench 官方 Harbor 判分尚未接入");
    expect(stylesSource).toContain(".sourceWarningStrip");
  });

  it("keeps the latest finished supervised run in the idle result instead of the live monitor", () => {
    expect(routeSource).toContain("queryKeys.evolutionWorkspaceSnapshot()");
    expect(routeSource).toContain('"/api/evolution/workspace-snapshot"');
    expect(routeSource).toContain("latestSupervisedRunSnapshot");
    expect(routeSource).toContain("const monitoredRun = effectiveActiveRunSnapshot");
    expect(routeSource).toContain("?? visibleLiveRunSnapshot;");
    expect(routeSource).not.toContain("?? latestSupervisedRunSnapshot");
    expect(routeSource).not.toContain("setLiveActiveRun(latestSupervisedRunSnapshot)");
    expect(routeSource).toContain("styles.latestSupervisedResult");
  });

  it("labels supervised retry as rerunning failed items", () => {
    expect(routeSource).toContain("retryRunMutation");
    expect(routeSource).toContain("`/api/evolution/runs/${runId}/retry`");
  });

  it("keeps the supervised launch panel compact", () => {
    expect(routeSource).toContain("sourceMetaSide");
    expect(routeSource).toContain("数据集会先物化，评测包可直接运行。");
    expect(routeSource).toContain("startWorktreeRunMutation");
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
    expect(stylesSource).toContain(".liveLaunchStack");
    expect(stylesSource).toContain(".liveLaunchStack > .launchSurface");
  });

  it("shows the current supervised run members in the left launch rail", () => {
    expect(routeSource).toContain("SUPERVISED_MEMBER_ROLES");
    expect(routeSource).toContain('["baseline", "candidate", "reviewer", "auditor", "judge"]');
    expect(routeSource).toContain("supervisedRunMembers");
    expect(routeSource).toContain("monitoredRun?.agentBindings");
    expect(routeSource).toContain("monitoredRun?.currentAgentBinding?.agentId");
    expect(routeSource).toContain("styles.supervisedMembersPanel");
    expect(routeSource).toContain("本轮监督成员");
    expect(stylesSource).toContain(".supervisedMembersPanel");
    expect(stylesSource).toContain(".supervisedMemberRowActive");
  });

  it("shows immediate local feedback while a supervised start request is waiting for the backend", () => {
    expect(routeSource).toContain("LOCAL_SUPERVISED_RUN_PREFIX");
    expect(routeSource).toContain("buildSupervisedStartPlaceholder");
    expect(routeSource).toContain("isLocalSupervisedStartPlaceholder");
    expect(routeSource).toContain("onMutate: () =>");
    expect(routeSource).toContain("启动请求已提交，正在等待后端返回真实运行记录。");
    expect(routeSource).toContain("setLiveActiveRun(buildSupervisedStartPlaceholder");
    expect(routeSource).toContain("visibleLiveRunSnapshot");
    expect(routeSource).toContain("const streamLiveRun = isLocalSupervisedStartPlaceholder(liveActiveRun) ? null : liveActiveRun");
    expect(routeSource).toContain("setLiveActiveRun((current) => (isLocalSupervisedStartPlaceholder(current) ? null : current))");
  });

  it("explains closed-loop launch and dataset case limits without changing review actions", () => {
    expect(routeSource).toContain('t("caseLimitHint")');
    expect(routeSource).toContain("styles.closedLoopLaunchBlock");
    expect(routeSource).toContain('t("closedLoopLaunchPanelTitle")');
    expect(routeSource).toContain('t("closedLoopLaunchPanelHint")');
    expect(dictionarySource).toContain("结果会进入下方候选审核，不会自动合并。");
    expect(stylesSource).toContain(".closedLoopLaunchBlock");
  });

  it("keeps the supervised live console as a dense desktop split before narrow layouts", () => {
    const desktopBreakpoint = stylesSource.slice(
      stylesSource.indexOf("@media (max-width: 1360px)"),
      stylesSource.indexOf("@media (max-width: 1200px)"),
    );
    expect(stylesSource).toContain("@media (max-width: 1360px)");
    expect(desktopBreakpoint).toContain('"launch resize-launch io resize-run run"');
    expect(desktopBreakpoint).not.toContain('"io io"\n      "launch run"');
  });

  it("lets the supervised case transcript fill the lower vertical space", () => {
    expect(routeSource).toContain("styles.transcriptSection");
    expect(routeSource).toContain("styles.caseRawEvidence");
    expect(routeSource).toContain("currentCaseOutputLabel(monitoredRun)");
    expect(stylesSource).toContain(".transcriptSection");
    expect(stylesSource).toContain("flex: 1 1 0");
    expect(stylesSource).toContain("background: transparent");
    expect(stylesSource).toContain(".caseRawEvidence");
    expect(stylesSource).toContain("max-height: 30%");
    expect(stylesSource).not.toContain("max-height: 340px");
  });

  it("keeps supervised launch from reserving space for worktree review in the left rail", () => {
    const launchStackRule = stylesSource.slice(
      stylesSource.indexOf(".liveLaunchStack {"),
      stylesSource.indexOf(".liveResizeHandleLaunch"),
    );

    expect(launchStackRule).toContain("overflow: auto");
    expect(stylesSource).toContain(".liveLaunchStack > .launchSurface");
    expect(stylesSource).toContain("max-height: min(520px, 48vh)");
    expect(stylesSource).not.toContain(".worktreeReviewSurface");
    expect(worktreeReviewStylesSource).toContain(".worktreeReviewSurface");
  });

  it("renders supervised case transcript as expandable chat-style trace items", () => {
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
    expect(stylesSource).toContain(".caseTraceTimeline::before");
    expect(stylesSource).toContain(".caseTraceStack");
    expect(stylesSource).toContain("justify-content: flex-end");
    expect(stylesSource).toContain(".caseTraceSummary");
    expect(stylesSource).toContain(".caseTraceMessage");
    expect(stylesSource).toContain(".caseTraceMeta");
    expect(stylesSource).toContain("-webkit-line-clamp: 2");
    expect(stylesSource).toContain(".caseTraceStateGrid");
  });

  it("keeps the proposal library summary in three columns at common desktop widths", () => {
    expect(stylesSource).toContain(".librarySummaryBar");
    expect(stylesSource).toContain("minmax(300px, 1fr) minmax(260px, 0.8fr) minmax(300px, 0.9fr)");
  });

  it("does not put long live supervised text into native title tooltips", () => {
    expect(routeSource).not.toContain("title={monitoredRun.latestMessage}");
    expect(routeSource).not.toContain("title={monitoredTaskLabel}");
    expect(routeSource).not.toContain("title={entry.content}");
  });
});
