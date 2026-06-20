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

  it("keeps supervised rejection and runtime notes in governance wording instead of raw status codes", () => {
    expect(routeSource).toContain("function displaySupervisedTechnicalText");
    expect(routeSource).toContain("decision\\s*=\\s*REJECT");
    expect(routeSource).toContain("agent_judgment\\s+fail");
    expect(routeSource).toContain("风险 gate");
    expect(routeSource).toContain('title={run.nextAction || ""}');
    expect(routeSource).toContain('title={selectedRun.outcomeSemantics.runtimeExplanation}');
    expect(routeSource).toContain('title={selectedRun.riskReasons.join(" / ")}');
    expect(routeSource).toContain("proposalDetailQuery.data.supervised.riskReasons.join");
    expect(dictionarySource).toContain('supervisedFlowRunsHint: "回看分数、结论和风险项"');
    expect(dictionarySource).toContain('decision: "治理结论"');
    expect(dictionarySource).toContain('diagnosis: "治理结论说明"');
    expect(dictionarySource).not.toContain('retrySupervisedRun: "重跑失败项"');
  });

  it("keeps the latest finished supervised run in the idle result instead of the live monitor", () => {
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
    expect(routeSource).toContain("styles.latestSupervisedResult");
  });

  it("loads self-evolution from dedicated endpoints before falling back to the workspace snapshot", () => {
    expect(routeSource).toContain("queryKeys.evolutionSelfOverview()");
    expect(routeSource).toContain('"/api/evolution/self/overview"');
    expect(routeSource).toContain("queryKeys.evolutionSelfLatestRun()");
    expect(routeSource).toContain('"/api/evolution/self/latest-run"');
    expect(routeSource).toContain("queryKeys.evolutionSelfTransactions()");
    expect(routeSource).toContain('"/api/evolution/self/transactions"');
    expect(routeSource).toContain("const selfOverview = selfOverviewQuery.data ?? workspaceSnapshot?.selfOverview");
    expect(routeSource).toContain("selfLatestRunQuery.data ?? workspaceSnapshot?.selfLatestRun");
    expect(routeSource).toContain("const selfTransactions = selfTransactionsQuery.data ?? workspaceSnapshot?.selfTransactions ?? []");
    expect(routeSource).toContain("const selfTrackLoading = selfTrackQueriesEnabled");
    expect(routeSource).toContain("overview={selfOverview}");
    expect(routeSource).toContain("transactions={selfTransactions}");
    expect(routeSource).toContain("loading={selfTrackLoading}");
    expect(routeSource).not.toContain("loading={workspaceSnapshotQuery.isLoading}");
  });

  it("does not poll self-evolution detail endpoints while the supervised track is active", () => {
    expect(routeSource).toContain('const selfTrackQueriesEnabled = activeTrack === "self"');
    expect(routeSource).toContain('const supervisedTrackQueriesEnabled = activeTrack === "supervised"');
    expect(routeSource).toContain("enabled: selfTrackQueriesEnabled");
    expect(routeSource).not.toContain('const selfTrackQueriesEnabled = forcedTrack === "self" || forcedTrack === undefined');
  });

  it("loads the self-evolution track only after that track is shown", () => {
    expect(routeSource).toContain("LazySelfEvolutionTrack");
    expect(routeSource).toContain('import("./SelfEvolutionTrack")');
    expect(routeSource).toContain("<Suspense");
    expect(routeSource).not.toContain('import { SelfEvolutionTrack } from "./SelfEvolutionTrack";');
    expect(routeSource).toContain("正在加载自进化工作台");
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
    expect(routeSource).toContain("styles.selfModeStack");
    expect(routeSource).not.toContain("系统团队画布");
    expect(routeSource).not.toContain("自进化系统团队");
    expect(routeSource).not.toContain("监督进化系统团队");
  });

  it("labels supervised retry as rerunning failed items", () => {
    expect(routeSource).toContain("retryRunMutation");
    expect(routeSource).toContain("`/api/evolution/runs/${runId}/retry`");
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
    expect(routeSource).toContain('id="supervised-mental-mode"');
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
    expect(stylesSource).toContain(".liveLaunchStack");
    expect(stylesSource).toContain(".liveLaunchStack > .launchSurface");
    expect(stylesSource).toContain(".supervisedRunConsole");
    expect(stylesSource).toContain(".supervisedRunConsoleGrid");
  });

  it("shows supervised members by workflow step in the left launch rail", () => {
    expect(routeSource).toContain("SUPERVISED_RUN_MEMBER_ROLES");
    expect(routeSource).toContain('["baseline", "candidate", "judge"]');
    expect(routeSource).toContain("SUPERVISED_MEMBER_STEPS");
    expect(routeSource).toContain('{ id: "launch", zh: "启动与现场", en: "Launch", roles: ["baseline", "candidate"] }');
    expect(routeSource).toContain('{ id: "results", zh: "运行结果", en: "Results", roles: ["baseline", "candidate"] }');
    expect(routeSource).toContain('{ id: "proposal", zh: "改进提案", en: "Proposal", roles: ["candidate", "judge"] }');
    expect(routeSource).toContain('{ id: "review", zh: "样本评审", en: "Review", roles: ["judge"] }');
    expect(routeSource).not.toContain('["baseline", "candidate", "reviewer", "auditor", "judge"]');
    expect(routeSource).toContain("selectedSupervisedMemberStepId");
    expect(routeSource).toContain("supervisedRuntimeMemberStepId");
    expect(routeSource).toContain("supervisedSelectedMemberStep");
    expect(routeSource).toContain("supervisedSelectedStepMembers");
    expect(routeSource).toContain("supervisedMemberStepManualSelection");
    expect(routeSource).toContain("supervisedStepMemberSummaries");
    expect(routeSource).toContain("supervisedRunMembers");
    expect(routeSource).toContain("hasSupervisedAgentBindings");
    expect(routeSource).toContain("currentSupervisedAgentBindings");
    expect(routeSource).toContain("const bindings = supervisedMembersBindings");
    expect(routeSource).toContain("supervisedMembersRun?.currentAgentBinding?.agentId");
    expect(routeSource).toContain("binding?.dialogueModelLabel || binding?.dialogueModelName");
    expect(routeSource).toContain("modelDisplayLabel(supervisedMemberModelId(binding), resolveModelLabel)");
    expect(routeSource).toContain("configQuery.data?.modelLabels");
    expect(routeSource).toContain("title={member.modelId || member.model}");
    expect(routeSource).toContain("supervisedMemberAgentManagementRoute");
    expect(routeSource).toContain('new URLSearchParams({ pane: "config", returnLabel: "supervised_evolution" })');
    expect(routeSource).toContain('params.set("agent", normalizedAgentId)');
    expect(routeSource).toContain('params.set("returnTo", normalizedReturnTo)');
    expect(routeSource).toContain("const supervisedMemberReturnTo = `${location.pathname}${location.search}`");
    expect(routeSource).toContain("to={supervisedMemberAgentManagementRoute(member.agentId, supervisedMemberReturnTo)}");
    expect(routeSource).toContain("styles.supervisedMemberLink");
    expect(routeSource).toContain("<ArrowUpRight size={13} aria-hidden=\"true\" />");
    expect(routeSource).toContain("onClick={() => setSelectedSupervisedMemberStepId(step.id)}");
    expect(routeSource).toContain("aria-pressed={selected}");
    expect(routeSource).toContain("setSelectedSupervisedMemberStepId(null)");
    expect(routeSource).toContain("跟随现场");
    expect(routeSource).toContain("styles.supervisedMembersPanel");
    expect(routeSource).toContain("styles.supervisedStepMemberRail");
    expect(routeSource).toContain("styles.supervisedStepMemberCardActive");
    expect(routeSource).toContain("styles.supervisedStepMemberCardCurrent");
    expect(routeSource).toContain("监督步骤成员导航");
    expect(stylesSource).toContain(".supervisedMembersPanel");
    expect(stylesSource).toContain(".supervisedStepMemberRail");
    expect(stylesSource).toContain(".supervisedStepMemberCardActive");
    expect(stylesSource).toContain(".supervisedStepMemberCardCurrent");
    expect(stylesSource).toContain(".supervisedStepFollowButton");
    expect(stylesSource).toContain(".supervisedMemberLink");
    expect(stylesSource).toContain(".supervisedMemberRowActive");
  });

  it("shows immediate local feedback while a supervised start command is waiting for the run record", () => {
    expect(routeSource).toContain("LOCAL_SUPERVISED_RUN_PREFIX");
    expect(routeSource).toContain("buildSupervisedStartPlaceholder");
    expect(routeSource).toContain("isLocalSupervisedStartPlaceholder");
    expect(routeSource).toContain("isEvolutionRunCommandAccepted");
    expect(routeSource).toContain("onMutate: () =>");
    expect(routeSource).toContain("启动请求已提交，正在等待运行记录刷新。");
    expect(routeSource).toContain("启动命令已排队，等待运行记录刷新。");
    expect(routeSource).toContain("setLiveActiveRun(buildSupervisedStartPlaceholder");
    expect(routeSource).toContain("const placeholderAgentBindings = activeRunSnapshot?.agentBindings");
    expect(routeSource).toContain("?? workspaceSnapshot?.currentAgentBindings");
    expect(routeSource).toContain("?? EMPTY_AGENT_BINDINGS");
    expect(routeSource).toContain("agentBindings: placeholderAgentBindings");
    expect(routeSource).not.toContain("latestSupervisedRunSnapshot?.agentBindings ?? {}");
    expect(routeSource).toContain("evolutionWorkspaceCache.refreshSupervisedActiveRun()");
    expect(routeSource).toContain("visibleLiveRunSnapshot");
    expect(routeSource).toContain("const streamLiveRun = isLocalSupervisedStartPlaceholder(liveActiveRun) ? null : liveActiveRun");
    expect(routeSource).toContain("setLiveActiveRun((current) => (isLocalSupervisedStartPlaceholder(current) ? null : current))");
    expect(routeSource).toContain("const supervisedStartSubmitting = startRunMutation.isPending || isLocalSupervisedStartPlaceholder(liveActiveRun)");
    expect(routeSource).toContain("监督运行中");
    expect(routeSource).toContain("supervisedStartButtonLabel");
  });

  it("explains closed-loop launch and dataset case limits without changing review actions", () => {
    expect(routeSource).toContain('t("caseLimitHint")');
    expect(routeSource).toContain("styles.closedLoopLaunchBlock");
    expect(routeSource).toContain('t("closedLoopLaunchPanelTitle")');
    expect(routeSource).toContain('t("closedLoopLaunchPanelHint")');
    expect(routeSource).toContain("styles.closedLoopModeBadge");
    expect(routeSource).toContain("当前只演练编排链路，不调用真实 LLM 自改。");
    expect(dictionarySource).toContain("结果会进入下方候选审核，不会自动合并。");
    expect(stylesSource).toContain(".closedLoopLaunchBlock");
    expect(stylesSource).toContain(".closedLoopModeBadge");
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

  it("keeps supervised run empty states compact for first-viewport scanning", () => {
    expect(stylesSource).toContain(".structuredEmptyState");
    expect(stylesSource).toContain("min-height: 86px");
    expect(stylesSource).toContain("padding: 10px 12px");
    expect(stylesSource).not.toContain("min-height: 220px");
  });

  it("uses denser supervised launch and member panels at narrow workbench widths", () => {
    const middleBreakpoint = stylesSource.slice(
      stylesSource.indexOf("@media (min-width: 901px) and (max-width: 1200px)"),
      stylesSource.indexOf("@media (max-width: 900px)"),
    );

    expect(stylesSource).toContain("minmax(300px, var(--evolution-live-launch-width, 348px))");
    expect(stylesSource).toContain("minmax(300px, var(--evolution-live-run-width, 360px))");
    expect(stylesSource).toContain("container-type: inline-size");
    expect(stylesSource).toContain("@container (min-width: 560px)");
    expect(stylesSource).toContain("grid-template-columns: minmax(0, 1.08fr) minmax(214px, 0.72fr)");
    expect(stylesSource).toContain("grid-template-rows: minmax(0, 1fr)");
    expect(stylesSource).not.toContain("grid-template-rows: minmax(0, auto) minmax(0, 0.9fr) minmax(150px, 0.82fr)");
    expect(stylesSource).not.toContain("grid-template-rows: minmax(0, auto) minmax(156px, 0.86fr) minmax(150px, 0.74fr)");
    expect(stylesSource).not.toContain("max-height: min(430px, 60vh)");
    expect(middleBreakpoint).toContain(".liveLaunchStack > .launchSurface > .noticeText");
    expect(middleBreakpoint).toContain(".liveLaunchStack > .launchSurface .formHint");
    expect(middleBreakpoint).not.toContain(".liveLaunchStack > .launchSurface .sourceInventoryBar");
    expect(middleBreakpoint).not.toContain(".liveLaunchStack > .launchSurface .sourceMetaCompact");
    expect(middleBreakpoint).toContain("display: none");
    expect(stylesSource).toContain("max-height: min(118px, 22vh)");
    expect(stylesSource).toContain("max-height: min(238px, 34vh)");
    expect(stylesSource).toContain("min-height: 34px");
    expect(stylesSource).not.toContain("min-height: 40px");
    expect(stylesSource).toContain("font-family: var(--font-mono)");
    expect(stylesSource).not.toContain("align-self: end");
  });

  it("switches the supervised live grid to a single-column flow below tablet width", () => {
    const tabletBreakpoint = stylesSource.slice(
      stylesSource.indexOf("@media (max-width: 900px)"),
      stylesSource.indexOf("@media (max-width: 640px)"),
    );

    expect(tabletBreakpoint).toContain("grid-template-rows: max-content max-content max-content");
    expect(tabletBreakpoint).toContain('grid-template-areas:\n      "io"\n      "launch"\n      "run"');
    expect(tabletBreakpoint).toContain("align-content: start");
    expect(tabletBreakpoint).toContain("height: auto");
    expect(tabletBreakpoint).toContain("overflow: auto");
    expect(tabletBreakpoint).toContain("grid-auto-rows: max-content");
    expect(tabletBreakpoint).toContain("height: max-content");
    expect(tabletBreakpoint).toContain("min-height: max-content");
    expect(tabletBreakpoint).toContain("overflow: visible");
    expect(tabletBreakpoint).toContain("grid-template-columns: repeat(2, minmax(0, 1fr))");
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

  it("shows environment preflight failures instead of waiting for agent output forever", () => {
    expect(routeSource).toContain("supervisedPreflightIssue(monitoredRun, lang)");
    expect(routeSource).toContain("任务环境预检失败，未启动 Agent");
    expect(routeSource).toContain("missing_verifier_dependency");
    expect(routeSource).toContain("monitoredPreflightIssue ? (");
    expect(routeSource).toContain("styles.casePreflightIssue");
    expect(stylesSource).toContain(".casePreflightIssue");
    expect(stylesSource).toContain("var(--state-warning)");
  });

  it("keeps supervised launch from reserving an empty worktree-review track", () => {
    const launchStackRule = stylesSource.slice(
      stylesSource.indexOf(".liveLaunchStack {"),
      stylesSource.indexOf(".liveResizeHandleLaunch"),
    );

    expect(launchStackRule).toContain("grid-template-rows: minmax(0, 1fr)");
    expect(launchStackRule).toContain("overflow: hidden");
    expect(stylesSource).toContain(".liveLaunchStack > .launchSurface");
    expect(stylesSource).toContain("max-height: none");
    expect(stylesSource).not.toContain("max-height: min(430px, 60vh)");
    expect(stylesSource).not.toContain(".worktreeReviewSurface");
    expect(worktreeReviewStylesSource).toContain(".worktreeReviewSurface");
  });

  it("renders supervised case transcript with a read-only conversation view and trace fallback", () => {
    expect(routeSource).toContain("LazyConversationView");
    expect(routeSource).toContain("monitoredCaseConversationMessages");
    expect(routeSource).toContain("monitoredCaseHasConversationMessages");
    expect(routeSource).toContain("showComposer={false}");
    expect(routeSource).toContain("conversationMessages");
    expect(routeSource).toContain("styles.caseConversationShell");
    expect(routeSource).toContain("styles.caseConversationTranscript");
    expect(stylesSource).toContain(".caseConversationShell");
    expect(stylesSource).toContain(".caseConversationTranscript");
    expect(stylesSource).toContain(".caseConversationFallback");
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
