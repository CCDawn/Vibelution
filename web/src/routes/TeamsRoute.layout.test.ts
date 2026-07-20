import { describe, expect, it } from "vitest";

import { resolveLegacyTeamsRedirect } from "./LegacyTeamsRedirect";
import canvasDataSource from "./TeamsRoute.canvasData.ts?raw";
import routeSource from "./TeamsRoute.tsx?raw";
import teamsSourceCollectionPanelSource from "./teams/TeamsSourceCollectionPanel.tsx?raw";
import researchMemoryEvidencePanelSource from "./teams/ResearchMemoryEvidencePanel.tsx?raw";
import evidenceModelSource from "./teams/source-collection/evidenceModel.ts?raw";
import runModelSource from "./teams/source-collection/runModel.ts?raw";
import stageProjectionSource from "./teams/source-collection/stageProjection.ts?raw";
import researchWorkflowResourcesSource from "./teams/useResearchWorkflowResources.ts?raw";
import teamMemoryIndexPanelSource from "./TeamMemoryIndexPanel.tsx?raw";
import teamMemoryIndexPanelStyles from "./TeamMemoryIndexPanel.styles";
import teamExperimentMethodPanelSource from "./TeamExperimentMethodPanel.tsx?raw";
import teamExperimentMethodPanelStyles from "./TeamExperimentMethodPanel.styles";
import teamSourceCollectionActiveStagePanelSource from "./TeamSourceCollectionActiveStagePanel.tsx?raw";
import teamSourceCollectionActiveStagePanelStyles from "./TeamSourceCollectionActiveStagePanel.styles";
import teamSourceCollectionCandidatePanelSource from "./TeamSourceCollectionCandidatePanel.tsx?raw";
import teamSourceCollectionCandidatePanelStyles from "./TeamSourceCollectionCandidatePanel.styles";
import teamSourceCollectionConversationPanelSource from "./TeamSourceCollectionConversationPanel.tsx?raw";
import teamSourceCollectionConversationPanelStyles from "./TeamSourceCollectionConversationPanel.styles";
import teamSourceCollectionConversationPanelStylesSource from "./TeamSourceCollectionConversationPanel.styles.ts?raw";
import teamSourceCollectionControlsPanelSource from "./TeamSourceCollectionControlsPanel.tsx?raw";
import teamSourceCollectionControlsPanelStyles from "./TeamSourceCollectionControlsPanel.styles";
import teamSourceCollectionExtractionRecoveryPanelSource from "./TeamSourceCollectionExtractionRecoveryPanel.tsx?raw";
import teamSourceCollectionExtractionRecoveryPanelStyles from "./TeamSourceCollectionExtractionRecoveryPanel.styles";
import teamSourceCollectionFindingDetailsPanelSource from "./TeamSourceCollectionFindingDetailsPanel.tsx?raw";
import teamSourceCollectionFindingDetailsPanelStyles from "./TeamSourceCollectionFindingDetailsPanel.styles";
import teamSourceCollectionGraphPanelSource from "./TeamSourceCollectionGraphPanel.tsx?raw";
import teamSourceCollectionGraphPanelStyles from "./TeamSourceCollectionGraphPanel.styles";
import teamSourceCollectionManualWritebackPanelSource from "./TeamSourceCollectionManualWritebackPanel.tsx?raw";
import teamSourceCollectionManualWritebackPanelStyles from "./TeamSourceCollectionManualWritebackPanel.styles";
import teamSourceCollectionMemoryPanelSource from "./TeamSourceCollectionMemoryPanel.tsx?raw";
import teamSourceCollectionMemoryPanelStyles from "./TeamSourceCollectionMemoryPanel.styles";
import teamSourceCollectionPhaseCloseGatePanelSource from "./TeamSourceCollectionPhaseCloseGatePanel.tsx?raw";
import teamSourceCollectionPhaseCloseGatePanelStyles from "./TeamSourceCollectionPhaseCloseGatePanel.styles";
import teamSourceCollectionOverviewPanelSource from "./TeamSourceCollectionOverviewPanel.tsx?raw";
import teamSourceCollectionOverviewPanelStyles from "./TeamSourceCollectionOverviewPanel.styles";
import teamSourceCollectionOverviewPanelStylesSource from "./TeamSourceCollectionOverviewPanel.styles.ts?raw";
import teamSourceCollectionPanelFrameStyles from "./TeamSourceCollectionPanelFrame.styles";
import teamSourceCollectionPanelFrameStylesSource from "./TeamSourceCollectionPanelFrame.styles.ts?raw";
import teamSourceCollectionResultControlsSource from "./TeamSourceCollectionResultControls.tsx?raw";
import teamSourceCollectionRunSettingsPanelSource from "./TeamSourceCollectionRunSettingsPanel.tsx?raw";
import teamSourceCollectionRunSettingsPanelStyles from "./TeamSourceCollectionRunSettingsPanel.styles";
import teamSourceCollectionScreeningPanelSource from "./TeamSourceCollectionScreeningPanel.tsx?raw";
import teamSourceCollectionScreeningPanelStyles from "./TeamSourceCollectionScreeningPanel.styles";
import teamSourceCollectionStageAgentsPanelSource from "./TeamSourceCollectionStageAgentsPanel.tsx?raw";
import teamSourceCollectionStageAgentsPanelStyles from "./TeamSourceCollectionStageAgentsPanel.styles";
import teamSourceCollectionRunSwitcherPanelSource from "./TeamSourceCollectionRunSwitcherPanel.tsx?raw";
import teamSourceCollectionRunSwitcherPanelStyles from "./TeamSourceCollectionRunSwitcherPanel.styles";
import teamSourceCollectionSourceDetailPanelSource from "./TeamSourceCollectionSourceDetailPanel.tsx?raw";
import teamSourceCollectionSourceDetailPanelStyles from "./TeamSourceCollectionSourceDetailPanel.styles";
import teamSourceCollectionStandaloneStagePanelSource from "./TeamSourceCollectionStandaloneStagePanel.tsx?raw";
import teamSourceCollectionStandaloneStagePanelStyles from "./TeamSourceCollectionStandaloneStagePanel.styles";
import teamSourceCollectionStorageActionsPanelSource from "./TeamSourceCollectionStorageActionsPanel.tsx?raw";
import teamSourceCollectionStorageActionsPanelStyles from "./TeamSourceCollectionStorageActionsPanel.styles";
import teamWorkflowCandidatePreviewPanelSource from "./TeamWorkflowCandidatePreviewPanel.tsx?raw";
import teamWorkflowCandidatePreviewPanelStyles from "./TeamWorkflowCandidatePreviewPanel.styles";
import teamWorkflowCandidatePreviewPanelStylesSource from "./TeamWorkflowCandidatePreviewPanel.styles.ts?raw";
import teamWorkflowStatusPanelsSource from "./TeamWorkflowStatusPanels.tsx?raw";
import teamWorkflowStatusPanelStyles from "./TeamWorkflowStatusPanels.styles";
import teamWorkflowStatusPanelStylesSource from "./TeamWorkflowStatusPanels.styles.ts?raw";
import workflowGraphViewSource from "./TeamWorkflowGraphView.tsx?raw";
import workflowGraphViewStyles from "./TeamWorkflowGraphView.styles";
import teamCandidateCardSource from "../components/vui/product/team-management/TeamCandidateCard.tsx?raw";
import teamSourceEmptyStateSource from "../components/vui/product/team-management/TeamSourceEmptyState.tsx?raw";
import teamSourceFilterBarSource from "../components/vui/product/team-management/TeamSourceFilterBar.tsx?raw";
import teamSourcePaginationSource from "../components/vui/product/team-management/TeamSourcePagination.tsx?raw";
import teamStageCardSource from "../components/vui/product/team-management/TeamStageCard.tsx?raw";
import teamStageCommandBarSource from "../components/vui/product/team-management/TeamStageCommandBar.tsx?raw";
import teamStagePipelineSource from "../components/vui/product/team-management/TeamStagePipeline.tsx?raw";
import teamSourceResultListSource from "../components/vui/product/team-management/TeamSourceResultList.tsx?raw";
import teamSourceResultStatsSource from "../components/vui/product/team-management/TeamSourceResultStats.tsx?raw";
import routeStylesBase from "./TeamsRoute.styles";
import routeStylesModuleSource from "./TeamsRoute.styles.ts?raw";
import routerSource from "../app/router.tsx?raw";

const sourceCollectionLocalStyles = {
  ...teamSourceCollectionActiveStagePanelStyles,
  ...teamSourceCollectionCandidatePanelStyles,
  ...teamSourceCollectionConversationPanelStyles,
  ...teamSourceCollectionControlsPanelStyles,
  ...teamSourceCollectionExtractionRecoveryPanelStyles,
  ...teamSourceCollectionGraphPanelStyles,
  ...teamSourceCollectionMemoryPanelStyles,
  ...teamSourceCollectionPhaseCloseGatePanelStyles,
  ...teamSourceCollectionPanelFrameStyles,
  ...teamSourceCollectionRunSwitcherPanelStyles,
  ...teamSourceCollectionScreeningPanelStyles,
  ...teamSourceCollectionSourceDetailPanelStyles,
  ...teamSourceCollectionStageAgentsPanelStyles,
  ...teamSourceCollectionStandaloneStagePanelStyles,
};

const routeStyles = {
  ...routeStylesBase,
  ...sourceCollectionLocalStyles,
};

const routeStylesSource = [
  routeStylesModuleSource,
  ...Object.keys(routeStylesBase).map((key) => `.${key}`),
  ...Object.values(routeStylesBase),
].join("\n");

function classTokenCount(className: string, token: string) {
  return className.split(/\s+/).filter((item) => item === token).length;
}

function topLevelBackgroundTokenCount(className: string) {
  return className.split(/\s+/).filter((item) => item.startsWith("bg-[")).length;
}

function expectOperationalSurface(className: string, surface = "bg-[var(--vui-surface-panel)]") {
  expect(className).toContain(surface);
  expect(className).not.toContain("bg-[var(--vui-surface-glass)]");
  expect(className).not.toContain("shadow-[var(--vui-shadow-hairline)]");
  expect(className).not.toContain("bg-[image:var(--vui-gradient-route-soft)]");
  expect(className).not.toContain("shadow-[var(--vui-elevation-1-sheen)]");
  expect(className).not.toContain("hover:shadow-[var(--vui-elevation-2-sheen)]");
}

describe("TeamsRoute layout contract", () => {
  it("uses shell language state without loading the full app dictionary", () => {
    expect(routeSource).toContain("useShellI18n");
    expect(routeSource).toContain("const { lang } = useShellI18n()");
    expect(routeSource).not.toContain("useAppI18n");
  });

  it("is mounted as the top-level Team workspace with legacy redirects", () => {
    expect(routerSource).toContain('path: "teams"');
    expect(routerSource).toContain('guardedLazyElement(<TeamsRoute />, "workbench", "teams")');
    expect(routerSource).toContain('path: "agents/teams"');
    expect(routerSource).toContain('path: "research"');
    expect(routerSource).toContain("<LegacyTeamsRedirect />");
    expect(routeSource).not.toContain("AgentManagementNav");
    expect(routeSource).toContain("团队工作台 / 组织画布");
    expect(routeSource).toContain("Team Workspace / Canvas");
  });

  it("keeps canvas action labels compact and exposes non-critical explanations through VUI tooltips", () => {
    expect(routeSource).toContain("VTooltip,");
    expect(routeSource).toContain('content={lang === "zh" ? "自动排版只改变当前显示，不保存坐标"');
    expect(routeSource).toContain('content={lang === "zh" ? "显示画布文件中的原始坐标"');
    expect(routeSource).toContain("<VTooltip content={communicationEdgeHint}>");
    expect(routeSource).toContain('content={lang === "zh" ? "当前阶段 Agent 配置"');
    expect(routeSource).toContain('content={lang === "zh" ? "到 AgentDirectory 源配置修改"');
    expect(routeSource).not.toContain("title={communicationEdgeHint}");
    expect(routeSource).not.toContain('title={lang === "zh" ? "自动排版只改变当前显示，不保存坐标"');
    expect(routeSource).not.toContain('title={lang === "zh" ? "当前阶段 Agent 配置"');
    expect(routeSource).not.toContain('title={lang === "zh" ? "到 AgentDirectory 源配置修改"');
    expect(routeSource).not.toContain('{" · "}\n                  {communicationEdgeHint}');
  });

  it("preserves selected Team deep links from legacy routes", () => {
    expect(resolveLegacyTeamsRedirect("")).toBe("/teams");
    expect(resolveLegacyTeamsRedirect("?team=research-core")).toBe("/teams?team=research-core");
  });

  it("uses Team APIs and Agent Center as the binding source", () => {
    expect(routeSource).toContain('fetchJson<TeamListPayload>("/api/teams", { signal })');
    expect(routeSource).toContain("TEAM_BOOTSTRAP_REFETCH_STATUSES");
    expect(routeSource).toContain("query.state.data?.systemTeamBootstrap?.status");
    expect(routeSource).toContain("TEAM_BOOTSTRAP_ACTIVE_REFETCH_MS");
    expect(routeSource).not.toContain('fetchJson<TeamTemplateListPayload>("/api/team-templates")');
    expect(routeSource).not.toContain("/api/team-templates/${encodeURIComponent(templateId)}/instantiate");
    expect(routeSource).not.toContain("instantiateTeamTemplateMutation");
    expect(routeSource).toContain("TEAM_PICKER_TEAM_IDS");
    expect(canvasDataSource).toContain("const TEAM_PICKER_TEAM_IDS = [AI_SEARCH_TEAM_ID, KNOWLEDGE_EXPANSION_TEAM_ID, RESEARCH_TEAM_ID] as const");
    expect(routeSource).toContain("fetchJson<Team>(`/api/teams/${encodeURIComponent(effectiveTeamId)}?detail=${teamDetailLoadMode}`, { signal })");
    expect(routeSource).toContain("queryKeys.agentSummary(false)");
    expect(routeSource).toContain('fetchJson<AgentConfigWorkspaceAgent[]>("/api/agents?detail=summary", { signal })');
    expect(routeSource).not.toContain("includeArchived=true&detail=summary");
    expect(routeSource).not.toContain('fetchJson<AgentConfigWorkspace>("/api/agents/config-workspace")');
    expect(routeSource).toContain("fetchJson<Team>(`/api/teams/${encodeURIComponent(teamId)}`");
    expect(routeSource).toContain('method: "DELETE"');
    expect(routeSource).toContain("sendTeamProjectBusMessage(payload)");
    expect(routeSource).toContain("kernelTaskCenterHref");
    expect(routeSource).toContain("queryFn: ({ signal }) => listProjectAgentBusTimeline(PROJECT_AGENT_BUS_TEAM_TIMELINE_LIMIT, { signal })");
    expect(routeSource).toContain("revokeProjectAgentBusMessage({");
    expect(routeSource).toContain("/api/teams/${encodeURIComponent(teamId)}/chat-room/sync");
    expect(routeSource).toContain("syncTeamChatRoomMutation");
    expect(routeSource).toContain("fetchJson<ChatRoomDetail>(`/api/chat-rooms/${payload.roomId}/rounds`");
    expect(routeSource).toContain("fetchJson<ChatRoomDetail>(`/api/chat-rooms/${encodeURIComponent(linkedChatRoomId)}`, { signal })");
    expect(routeSource).toContain("linkedRoomRefetchInterval(pageVisible");
    expect(routeSource).toContain("latestChatRoomRound(linkedRoomDetail)");
    expect(researchWorkflowResourcesSource).toContain("fetchJson<TeamWorkflowOrchestration>");
    expect(researchWorkflowResourcesSource).toContain("/workflow-orchestration`");
    expect(researchWorkflowResourcesSource).toContain("fetchJson<TeamWorkflowCandidateListPayload>");
    expect(routeSource).toContain("fetchJson<TeamWorkflowCandidateGraphBuildPayload>");
    expect(researchWorkflowResourcesSource).toContain("fetchJson<TeamWorkflowKnowledgeIngestionStatus>");
    expect(researchWorkflowResourcesSource).toContain("fetchJson<TeamWorkflowOfficialModelEvidenceStatus>");
    expect(researchWorkflowResourcesSource).toContain("TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT");
    expect(researchWorkflowResourcesSource).toContain("TEAM_WORKFLOW_CANDIDATE_GRAPH_LIMIT");
    expect(routeSource).toContain("isResearchWorkflowTeam(selectedTeam)");
    expect(routeSource).toContain("researchWorkflowTeamSelected");
    expect(routeSource).toContain("teamWorkflowKnowledgeIngestionStatusQuery");
    expect(researchWorkflowResourcesSource).toContain("/workflow-orchestration/knowledge-ingestion/status");
    expect(routeSource).toContain("teamWorkflowOfficialModelEvidenceStatusQuery");
    expect(researchWorkflowResourcesSource).toContain("/workflow-orchestration/official-model-evidence/status");
    expect(researchWorkflowResourcesSource).toContain("TeamWorkflowSourceQualityStatus");
    expect(routeSource).toContain("teamWorkflowSourceQualityStatusQuery");
    expect(researchWorkflowResourcesSource).toContain("/workflow-orchestration/source-quality/status");
    expect(routeSource).toContain("/source-quality/assess");
    expect(routeSource).toContain("assessSourceQualityMutation");
    expect(routeSource).toContain("candidateSourceQualityAssessmentSummary");
    expect(researchWorkflowResourcesSource).toContain("TeamWorkflowPaperNoteChunkStatus");
    expect(routeSource).toContain("teamWorkflowPaperNoteChunkStatusQuery");
    expect(researchWorkflowResourcesSource).toContain("/workflow-orchestration/paper-note-chunks/status");
    expect(routeSource).toContain("/paper-note-chunks/plan");
    expect(routeSource).toContain("planPaperNoteChunksMutation");
    expect(routeSource).toContain("sourceCandidateHasCompletedExtraction");
    expect(routeSource).toContain("candidatePaperNoteChunkPlanSummary");
    expect(routeSource).toContain("ResearchStageRoundStatusPayload");
    expect(routeSource).toContain("researchStageRoundStatusQuery");
    expect(researchWorkflowResourcesSource).toContain("/workflow-orchestration/stage-rounds/status");
    expect(routeSource).toContain("/workflow-orchestration/stage-rounds/start");
    expect(routeSource).toContain("startResearchStageRoundMutation");
    expect(routeSource).toContain("seedSourceCollectionAgentSessionContextMutation");
    expect(routeSource).toContain("/source-collection-runs/${encodeURIComponent(payload.runId)}/agent-session-context");
    expect(routeSource).toContain("await seedSourceCollectionAgentSessionContextMutation.mutateAsync");
    expect(routeSource).toContain("TeamWorkflowSourceCollectionStageSessionTaskPayload");
    expect(routeSource).toContain("startSourceCollectionStageSessionTaskMutation");
    expect(routeSource).toContain("/source-collection-runs/${encodeURIComponent(payload.runId)}/stage-session-tasks");
    expect(routeSource).toContain("startSourceCollectionStageSessionTask(stageId");
    expect(routeSource).toContain("await startSourceCollectionStageSessionTaskMutation.mutateAsync");
    expect(routeSource).toContain("sourceCollectionStageTaskClickKey(stageId)");
    expect(routeSource).toContain("idempotencyKey: payload.idempotencyKey");
    expect(routeSource).toContain("idempotencyKey: sourceCollectionStageTaskClickKey(stageId)");
    expect(routeSource).toContain('ingestion: ["source_ingestor"]');
    expect(routeSource).toContain("priorityByKey");
    expect(routeSource).toContain("ExperimentFullRunResultRegisterPayload");
    expect(routeSource).toContain("ExperimentResultKnowledgeIngestionPayload");
    expect(routeSource).toContain("/workflow-orchestration/experiments/plans/${encodeURIComponent(payload.plan.planId)}/full-run-result");
    expect(routeSource).toContain("/workflow-orchestration/experiments/plans/${encodeURIComponent(payload.plan.planId)}/knowledge-ingestion-request");
    expect(routeSource).toContain("registerExperimentFullRunResultMutation");
    expect(routeSource).toContain("requestExperimentKnowledgeIngestionMutation");
    expect(routeSource).toContain("登记 full-run");
    expect(routeSource).toContain("通知知识库管理员");
    expect(routeSource).toContain("manualFullRunResult: true");
    expect(routeSource).toContain("explicitUserBoundary: true");
    expect(routeSource).toContain("stewardReviewRequired: true");
    expect(routeStylesSource).toContain(".experimentKnowledgePanel");
    expect(routeStylesSource).toContain(".experimentKnowledgeForm");
    expect(routeSource).toContain("ResearchLoopStatusPayload");
    expect(routeSource).toContain("researchLoopTemplatesQuery");
    expect(routeSource).toContain("researchLoopStatusQuery");
    expect(routeSource).toContain("/workflow-orchestration/research-loop/templates");
    expect(routeSource).toContain("/workflow-orchestration/research-loop/status");
    expect(routeSource).toContain("/workflow-orchestration/research-loop/loops");
    expect(routeSource).toContain("/workflow-orchestration/research-loop/loops/${encodeURIComponent(payload.loop.loopId)}/evidence");
    expect(routeSource).toContain("/workflow-orchestration/research-loop/loops/${encodeURIComponent(payload.loop.loopId)}/decision");
    expect(routeSource).toContain("createResearchLoopMutation");
    expect(routeSource).toContain("recordResearchLoopEvidenceMutation");
    expect(routeSource).toContain("recordResearchLoopDecisionMutation");
    expect(routeSource).toContain("renderResearchLoopPanel");
    expect(routeSource).toContain("Research Loop 模板");
    expect(routeSource).toContain("实验迭代决策");
    expect(routeSource).toContain("noSandboxRunner: true");
    expect(routeSource).toContain("noTrainingExecution: true");
    expect(routeSource).toContain("commandPreviewOnly: true");
    expect(routeSource).toContain("startSourceCollectionRunMutation");
    expect(routeSource).toContain("knowledgeExpansionWorkflowTeamSelected");
    expect(routeSource).toContain("SOURCE_COLLECTION_KNOWLEDGE_EXPANSION_ROLES");
    expect(routeSource).toContain("source_finder");
    expect(routeSource).toContain("collectionMode");
    expect(routeSource).toContain("local_workspace");
    expect(routeSource).toContain("mixed");
    expect(routeSource).toContain("localScanScope");
    expect(routeSource).toContain("workflowPurpose");
    expect(routeSource).toContain("workflowKind");
    expect(routeSource).toContain("recordSourceCollectionOutputMutation");
    expect(routeSource).toContain("executeSourceCollectionSearchMutation");
    const executeSearchMutationSource = routeSource.slice(
      routeSource.indexOf("const executeSourceCollectionSearchMutation"),
      routeSource.indexOf("const extractSourceCollectionCandidatesMutation"),
    );
    expect(executeSearchMutationSource).toContain("researchStageRoundStatusQueryKey(variables.teamId)");
    expect(routeSource).toContain("/workflow-orchestration/source-collection-runs");
    expect(routeSource).toContain("/search/execute");
    expect(routeSource).toContain("/api/data-processing/runs?limit=${SOURCE_COLLECTION_RUN_PREVIEW_LIMIT}");
    expect(routeSource).toContain("/collection-assignments/${encodeURIComponent(payload.draft.assignmentId)}/outputs");
    expect(routeSource).toContain("/source-candidate");
    expect(routeSource).toContain("sourceCollectionRunsForTeam");
    expect(routeSource).toContain("sourceCollectionRunHasUsableRecords");
    expect(routeSource).toContain("selectDefaultSourceCollectionRun");
    expect(routeSource).not.toContain("function sourceCollectionRunMetric");
    expect(routeSource).not.toContain("export function sourceCollectionRunRecordCount");
    expect(runModelSource).toContain("function sourceCollectionRunMetric");
    expect(runModelSource).toContain("export function selectDefaultSourceCollectionRun");
    expect(routeSource).toContain("sourceCollectionHistoricalRunWithRecords");
    expect(routeSource).toContain("sourceCollectionLatestRunIsEmpty");
    expect(routeSource).toContain("renderSourceCollectionRunSwitcher");
    expect(routeSource).toContain("TeamSourceCollectionRunSwitcherPanel");
    expect(routeSource).toContain("runOptions: TeamSourceCollectionRunSwitcherRun[]");
    expect(routeSource).toContain("onRunChange={setSelectedSourceCollectionRunId}");
    expect(teamSourceCollectionRunSwitcherPanelSource).toContain("sourceCollectionRunSwitcher");
    expect(teamSourceCollectionRunSwitcherPanelSource).toContain("sourceCollectionRunSwitcherMain");
    expect(teamSourceCollectionRunSwitcherPanelSource).toContain("sourceCollectionRunSwitcherStats");
    expect(teamSourceCollectionRunSwitcherPanelSource).toContain("VTooltip");
    expect(teamSourceCollectionRunSwitcherPanelSource).not.toContain("<small>{hint}</small>");
    expect(routeSource).toContain("TeamSourceEmptyState");
    expect(routeSource).toContain("rawRecordEmptyFacts");
    expect(routeSource).toContain("rawRecordEmptyActions");
    expect(routeSource).not.toContain("sourceCollectionEmptyRunNotice");
    expect(routeSource).toContain("当前批次暂无资料");
    expect(routeSource).toContain("上一轮有资料");
    expect(teamSourceCollectionRunSwitcherPanelSource).toContain("切换到有资料批次");
    expect(routeSource).toContain("还没有开始资料搜集");
    expect(routeSource).toContain("文件产物");
    expect(routeSource).toContain("TeamSourceCollectionStorageActionsPanel");
    expect(routeSource).toContain("primaryAction: TeamSourceCollectionStorageAction");
    expect(teamSourceCollectionStorageActionsPanelSource).toContain("workflowSourceCollectionStorageActions");
    expect(teamSourceCollectionStorageActionsPanelSource).toContain("workflowSourceCollectionStorageButtons");
    expect(teamSourceCollectionStorageActionsPanelSource).toContain("workflowSourceCollectionStorageDetails");
    expect(teamSourceCollectionStorageActionsPanelSource).toContain("本轮产物");
    expect(teamSourceCollectionStorageActionsPanelSource).toContain("更多证据文件");
    expect(routeSource).toContain("SOURCE_COLLECTION_DEFAULT_ROLES");
    expect(researchWorkflowResourcesSource).toContain("candidateType=candidate_graph");
    expect(routeSource).toContain("/workflow-orchestration/candidate-graph");
    expect(routeSource).toContain("buildCandidateGraphMutation");
    expect(routeSource).toContain('source: "team_workspace"');
    expect(routeSource).toContain("teamId: payload.teamId");
    expect(routeSource).toContain("startTeamRoundMutation");
    expect(routeSource).toContain("chatWorkspaceCache.afterTeamRoomMembershipChanged(variables.teamId, room.roomId)");
    expect(routeSource).toContain("chatWorkspaceCache.afterTeamRoomMembershipChanged(team.teamId, team.linkedChatRoom.roomId)");
    expect(routeSource).toContain("teamConversationStatusLabel");
    expect(routeSource).toContain("selectedTeam?.conversation");
    expect(routeSource).toContain("isAiSearchScopeTeam(selectedTeam)");
    expect(routeSource).toContain("showAiSearchScopePanel");
    expect(routeSource).toContain("renderAiSearchSourceScopePanel");
    expect(routeSource).toContain("selectedTeam?.sourceScope");
    expect(routeSource).toContain("AiSearchRunListPayload");
    expect(routeSource).toContain("queryKeys.teamAiSearchRuns");
    expect(routeSource).toContain("/api/teams/${encodeURIComponent(effectiveTeamId)}/ai-search-runs?limit=${AI_SEARCH_RUN_PREVIEW_LIMIT}");
    expect(routeSource).toContain("/api/teams/${encodeURIComponent(payload.teamId)}/ai-search-runs");
    expect(routeSource).toContain("startAiSearchRunMutation");
    expect(routeSource).toContain("aiSearchRunTopic");
    expect(routeSource).toContain("主题 -> 可信来源 -> 摘要/引用 -> 运行记录");
    expect(routeSource).toContain("结论需一手证据");
    expect(routeSource).toContain("默认启用");
    expect(routeSource).toContain("线索");
    expect(routeSource).toContain("白名单、去重、存储路径");
    expect(routeSource).toContain("启动一键搜索");
    expect(routeSource).toContain("最近搜索结果");
    expect(routeSource).toContain("latestAiSearchRun");
    expect(routeSource).toContain("/api/teams/${encodeURIComponent(nextCanvas.teamId)}/canvas");
    expect(routeSource).toContain("成员源");
    expect(routeSource).toContain("Member source");
    expect(routeSource).toContain("Agent Center");
    expect(routeSource).toContain("teamCanvasNodeAgentSourceRoute");
    expect(routeSource).toContain("writableTeamCanvas(nextCanvas)");
    expect(routeSource).toContain("delete writableNode.agentSourceRef");
    expect(routeSource).toContain("delete writableNode.agentProjectionEdit");
    expect(routeSource).toContain("delete writableNode.agentProjectionCanWrite");
    expect(routeSource).toContain("TEAM_ORGANIZATION_CANVAS_KIND");
    expect(canvasDataSource).toContain("team_organization_canvas");
    expect(routeSource).not.toContain("/api/research/flow-canvas");
  });

  it("extracts the research source-collection workspace through a route-local wrapper", () => {
    expect(routeSource).toContain("TeamsSourceCollectionPanel");
    expect(routeSource).toContain('from "./teams/TeamsSourceCollectionPanel"');
    expect(teamsSourceCollectionPanelSource).toContain("TeamSourceCollectionOverviewPanel");
    expect(teamsSourceCollectionPanelSource).not.toContain("TeamsRoute.styles");
    expect(teamsSourceCollectionPanelSource).not.toContain("useQuery");
    expect(teamsSourceCollectionPanelSource).not.toContain("useMutation");
  });

  it("can deep-link from Agent references to a selected Team", () => {
    expect(routeSource).toContain("useSearchParams");
    expect(routeSource).toContain('searchParams.get("team")');
    expect(routeSource).toContain('searchParams.get("agent")');
    expect(routeSource).toContain('searchParams.get("researchView")');
    expect(routeSource).toContain("parseResearchWorkspaceView");
    expect(routeSource).toContain("requestedAgentTeamId");
    expect(routeSource).toContain("setSearchParams({ team: team.teamId })");
  });

  it("exposes Team and member Agent memory deep links from the Team workspace", () => {
    expect(routeSource).toContain("teamMemoryRoute");
    expect(routeSource).toContain("agentCenterMemoryRoute");
    expect(routeSource).toContain("selectedTeamReturnRoute");
    expect(routeSource).toContain("selectedTeamKnowledgeRoute");
    expect(routeSource).toContain("selectedTeamGraphRoute");
    expect(routeSource).toContain("selectedTeamMemoryMembers: TeamMemoryIndexMember[]");
    expect(routeSource).toContain("renderTeamMemoryIndex()");
    expect(routeSource).toContain("<TeamMemoryIndexPanel");
    expect(routeSource).toContain("members={selectedTeamMemoryMembers}");
    expect(routeSource).toContain("knowledgeRoute={selectedTeamKnowledgeRoute}");
    expect(routeSource).toContain("graphRoute={selectedTeamGraphRoute}");
    expect(teamMemoryIndexPanelSource).toContain("styles.teamMemoryIndex");
    expect(teamMemoryIndexPanelSource).toContain("styles.teamMemoryMemberTable");
    expect(teamMemoryIndexPanelSource).toContain("styles.teamMemoryMemberHeading");
    expect(teamMemoryIndexPanelSource).toContain("styles.teamMemoryActionRail");
    expect(teamMemoryIndexPanelSource).toContain("团队记忆索引");
    expect(teamMemoryIndexPanelSource).toContain("团队知识库");
    expect(teamMemoryIndexPanelSource).toContain("团队记忆图谱");
    expect(teamMemoryIndexPanelSource).toContain("职责");
    expect(teamMemoryIndexPanelSource).toContain("入口");
    expect(routeSource).not.toContain("跳转到团队知识、图谱和成员 Agent 私有记忆");
    expect(routeSource).toContain('view: "agents"');
    expect(routeSource).toContain('view: "knowledge"');
    expect(routeSource).toContain('view: "graph"');
    expect(routeSource).toContain("teamId: selectedTeam.teamId");
    expect(routeSource).toContain("teamId: selectedTeam?.teamId");
    expect(routeStyles.teamMemoryIndex).toContain("!flex-none");
    expect(routeStyles.teamMemoryIndex).toContain("bg-[var(--vui-surface-panel)]");
    expect(routeStyles.teamMemoryMemberTable).toContain("grid-cols-[minmax(0,1fr)]");
    expect(routeStyles.teamMemoryMemberTable).not.toContain("repeat(auto-fit");
    expect(routeStyles.teamMemoryMemberTable).not.toContain("repeat(auto-fill");
    expect(routeStyles.teamMemoryMemberCard).toContain("bg-[var(--vui-surface-row)]");
    expect(routeStyles.teamMemoryMemberCard).not.toContain("bg-[var(--vui-surface-glass)]");
    expect(routeStyles.teamMemoryMemberCard).not.toContain("shadow-[var(--vui-shadow-hairline)]");
    expect(teamMemoryIndexPanelStyles.teamMemoryIndex).toContain("!flex-none");
    expect(teamMemoryIndexPanelStyles.teamMemoryIndex).toContain("bg-[var(--vui-surface-panel)]");
    expect(teamMemoryIndexPanelStyles.teamMemoryMemberTable).toContain("grid-cols-[minmax(0,1fr)]");
    expect(teamMemoryIndexPanelStyles.teamMemoryMemberTable).not.toContain("repeat(auto-fit");
    expect(teamMemoryIndexPanelStyles.teamMemoryMemberTable).not.toContain("repeat(auto-fill");
    expect(teamMemoryIndexPanelStyles.teamMemoryMemberCard).toContain("bg-[var(--vui-surface-row)]");
    expect(teamMemoryIndexPanelStyles.teamMemoryMemberCard).not.toContain("bg-[var(--vui-surface-glass)]");
    expect(teamMemoryIndexPanelStyles.teamMemoryMemberCard).not.toContain("shadow-[var(--vui-shadow-hairline)]");
    expect(routeStylesSource).toContain(".teamMemoryMemberTable");
    expect(routeStylesSource).toContain(".teamMemoryMemberHeading");
    expect(routeStylesSource).toContain(".teamMemoryActionRail");
    expect(routeStyles.teamMemoryMemberHeading).toContain("max-[720px]:hidden");
    expect(routeStyles.teamMemoryMemberActions).toContain("[&_a]:min-h-8");
    expect(routeStyles.teamMemoryActionRail).toContain("[&_a]:inline-flex");
  });

  it("distinguishes Agent-directory hydration from a missing Team binding in the memory index", () => {
    expect(routeSource).toContain("const memoryIndexAgentHydrationPending = Boolean(");
    expect(routeSource).toContain("const memoryIndexAgentLoadFailed = Boolean(");
    expect(routeSource).toContain('lang === "zh" ? "正在读取 Agent 目录" : "Loading Agent directory"');
    expect(routeSource).toContain('lang === "zh" ? "Agent 目录加载失败" : "Agent directory load failed"');
    expect(routeSource).toContain('lang === "zh" ? "Agent 引用失效" : "Agent reference missing"');
    expect(routeSource).not.toContain("statusLabel: researchStageAgentConfigStatusLabel(agent, lang)");
  });

  it("keeps the research overview on a readable workbench surface instead of a transparent card wall", () => {
    expect(routeStyles.workspaceResearch).toContain("bg-[var(--vui-surface-panel)]");
    expect(routeStyles.workspaceResearch).toContain("rounded-none");
    expect(routeStyles.workspaceResearch).toContain("gap-2");
    expect(routeStyles.workspaceResearch).not.toContain("gap-[var(--team-workbench-gap)]");

    expect(routeStyles.researchStageLauncher).toContain("bg-[var(--vui-surface-panel)]");
    expect(routeStyles.researchStageLauncher).toContain("rounded-[var(--radius-panel)]");
    expect(routeStyles.researchStageLauncher).toContain("grid");
    expect(routeStyles.researchStageLauncher).toContain("gap-3");

    expect(routeStyles.teamMemoryIndex).toContain("bg-[var(--vui-surface-panel)]");
    expect(routeStyles.teamMemoryIndex).toContain("rounded-[var(--radius-panel)]");
    expect(routeStyles.teamMemoryMemberTable).toContain("grid-cols-[minmax(0,1fr)]");
    expect(routeStyles.teamMemoryMemberTable).not.toContain("repeat(auto-fit");
    expect(routeStyles.teamMemoryMemberCard).toContain("grid-cols-[minmax(10rem,1.1fr)_minmax(11rem,1.4fr)_max-content_auto]");
    expect(teamMemoryIndexPanelStyles.teamMemoryMemberTable).toContain("grid-cols-[minmax(0,1fr)]");
    expect(teamMemoryIndexPanelStyles.teamMemoryMemberTable).not.toContain("repeat(auto-fit");
  });

  it("keeps only the fixed research and AI search teams in the picker", () => {
    expect(routeSource).toContain("EVOLUTION_SYSTEM_TEAM_IDS");
    expect(routeSource).toContain('"self-evolution-team"');
    expect(routeSource).toContain('"supervised-evolution-team"');
    expect(canvasDataSource).toContain('RESEARCH_TEAM_ID = "research-team"');
    expect(canvasDataSource).toContain('AI_SEARCH_TEAM_ID = "ai-search-team"');
    expect(canvasDataSource).toContain('KNOWLEDGE_EXPANSION_TEAM_ID = "knowledge-expansion-team"');
    expect(routeSource).toContain("TEAM_PICKER_TEAM_IDS.map((teamId) => teamsById.get(teamId))");
    expect(routeSource).toContain("isEvolutionSystemTeam");
    expect(routeSource).toContain("team.teamKind === \"self_evolution\"");
    expect(routeSource).toContain("team.teamKind === \"supervised_evolution\"");
    expect(routeSource).toContain("team.teamSource === \"self_evolution\"");
    expect(routeSource).toContain("team.teamSource === \"supervised_evolution\"");
    expect(routeSource).toContain("const visibleTeamIds = useMemo(() => new Set(visibleTeams.map((team) => team.teamId)), [visibleTeams])");
    expect(routeSource).toContain("requestedVisibleTeamId");
    expect(routeSource).toContain("requestedVisibleAgentTeamId");
    expect(routeSource).toContain("selectedVisibleTeamId");
    expect(routeSource).toContain("fallbackVisibleTeamId");
    expect(routeSource).toContain("const hasTeams = visibleTeams.length > 0");
    expect(routeSource).toContain("visibleTeamSummary.activeTeamCount");
    expect(routeSource).toContain("visibleTeams.map((team) => (");
    expect(routeSource).toContain("visibleTeams.find((team) => team.teamId === String(key))");
    expect(routeSource).toContain("visibleTeams.find((team) => team.teamId === effectiveTeamId)");
    expect(routeSource).not.toContain("{teams.map((team) => (");
    expect(routeSource).not.toContain("teams[0]?.teamId");
  });

  it("renders a dense list canvas inspector workflow", () => {
    expect(routeSource).toContain("VRouteHeader");
    expect(routeSource).toContain("VSelect");
    expect(routeSource).toContain("VStatusStrip");
    expect(routeSource).toContain("VIconButton");
    expect(routeSource).toContain("VNativeInput");
    expect(routeSource).toContain("VNativeSelect");
    expect(routeSource).toContain("VNativeTextarea");
    expect(routeSource).not.toMatch(/<input\b/);
    expect(routeSource).not.toMatch(/<select\b/);
    expect(routeSource).not.toMatch(/<textarea\b/);
    expect(routeSource).toContain("teamContextBar");
    expect(routeSource).toContain("teamSelectField");
    expect(routeSource).toContain("teamSelectPrefix");
    expect(routeSource).toContain("teamSelectControl");
    expect(routeSource).toContain("teamRefreshButton");
    expect(routeSource).toContain("teamContextChips");
    expect(routeSource).toContain("selectedTeamContextTitle");
    expect(routeSource).toContain("成员源");
    expect(routeSource).toContain("Member source");
    expect(routeSource).not.toContain("teamPickerPanel");
    expect(routeSource).not.toContain("teamSwitcherBar");
    expect(routeSource).not.toContain("teamPickerLabel");
    expect(routeSource).not.toContain("teamPickerSummary");
    expect(routeSource).not.toContain("summaryBar");
    expect(routeSource).toContain("aria-label={lang === \"zh\" ? \"选择团队\" : \"Select team\"}");
    expect(routeSource).not.toContain("<select\n            value={selectedTeam?.teamId ?? effectiveTeamId}");
    expect(routeSource).not.toContain("className={styles.teamPanel}");
    expect(routeSource).toContain("canvasPanel");
    expect(routeSource).toContain("inspector");
    expect(routeSource).toContain("hasTeams");
    expect(routeSource).toContain("showTeamInitialLoadingSurface");
    expect(routeSource).toContain("showTeamUnavailableSurface");
    expect(routeSource).toContain("teamListInitialLoading");
    expect(routeSource).toContain("const showTeamInitialLoadingSurface = teamListInitialLoading");
    expect(routeSource).toContain("const showTeamUnavailableSurface = !teamListInitialLoading && !hasTeams");
    expect(routeSource).toContain("teamContextMeta");
    expect(routeSource).toContain("teamSummaryStatusItems");
    expect(routeSource).toContain("styles.teamUnavailableSurface");
    expect(routeSource).toContain("teamListUnavailable");
    expect(routeSource).toContain("团队数据不可用");
    expect(routeSource).toContain("正在读取团队");
    expect(routeSource).toContain("团队尚未初始化");
    expect(routeSource).not.toContain("styles.workspaceEmpty");
    expect(routeSource).toContain("showTeamInitialLoadingSurface ? (");
    expect(routeSource).toContain("showTeamUnavailableSurface ? (");
    expect(routeSource).toContain('tone="loading"');
    expect(routeSource).toContain("skeletonLines={3}");
    expect(routeSource).toContain("<VLoadingValue");
    expect(routeSource).toContain('tone={teamListUnavailable ? "error" : "empty"}');
    const initialLoadingSurfaceSource = routeSource.slice(
      routeSource.indexOf("showTeamInitialLoadingSurface ? ("),
      routeSource.indexOf(") : showTeamUnavailableSurface ? ("),
    );
    expect(initialLoadingSurfaceSource).toContain('tone="loading"');
    expect(initialLoadingSurfaceSource).toContain("skeletonLines={3}");
    expect(initialLoadingSurfaceSource).toContain("<VLoadingValue");
    expect(initialLoadingSurfaceSource).not.toContain("visibleTeamSummary.activeTeamCount");
    expect(initialLoadingSurfaceSource).not.toContain("visibleTeamSummary.memberCount");
    expect(routeSource).toContain("styles.emptyCanvasPanel");
    expect(routeSource).not.toContain("选择团队后进入对应工作区");
    expect(routeSource).not.toContain("顶部只保留 AI 搜索范围团队和 挑战杯ai科研团队 两个入口");
    expect(routeSource).toContain("暂无可用团队。请确认 AI 搜索范围团队和 挑战杯ai科研团队 已初始化。");
    expect(routeSource).not.toContain("teamNameInputRef");
    expect(routeSource).not.toContain("从模板创建");
    expect(routeSource).not.toContain("创建 Demo 团队");
    expect(routeSource).not.toContain("selectedTemplate.chatRoom.mode");
    expect(routeSource).not.toContain("styles.templatePanel");
    expect(routeSource).not.toContain("styles.templatePicker");
    expect(routeSource).not.toContain("styles.templateSelect");
    expect(routeSource).not.toContain("styles.templatePreview");
    expect(routeSource).not.toContain("styles.templateCard");
    expect(routeSource).not.toContain("先填写团队名称，再创建团队。");
    expect(routeSource).not.toContain("styles.formError");
    expect(routeSource).not.toContain("styles.formHint");
    expect(routeSource).toContain("暂无画布数据");
    expect(routeSource).toContain("等待数据");
    expect(routeSource).toContain("styles.nodeBindingSection");
    expect(routeSource).toContain("styles.nodeBindingPlaceholder");
    expect(routeSource).toContain("styles.nodeSourceAuthority");
    expect(routeSource).toContain("Agent 身份只读投影");
    expect(routeSource).toContain("Read-only Agent identity");
    expect(routeSource).toContain("到 AgentDirectory 源配置修改");
    expect(routeSource).toContain("selectedNode.agentSourceRef?.owner");
    expect(routeSource).toContain("teamCanvasNodeAgentSourceRoute(selectedNode)");
    expect(routeSource).toContain("正在读取团队节点");
    expect(routeSource).toContain("agentTeamMembership");
    expect(routeSource).toContain("membership.teamId !== selectedTeam?.teamId");
    expect(routeSource).toContain("disabled={ownedByOtherTeam}");
    expect(routeSource).toContain("已属于");
    expect(routeSource).toContain("接入主干");
    expect(routeSource).toContain("保存节点");
    expect(routeSource).toContain("归档");
    expect(routeSource).toContain("function isSystemManagedTeam");
    expect(routeSource).toContain("systemManagedTeamArchiveReason");
    expect(routeSource).toContain("系统团队由工作流自动维护，不能在这里归档。");
    expect(routeSource).toContain("系统团队不可归档");
    expect(routeSource).toContain("解绑节点");
    expect(routeSource).toContain("删除节点");
    expect(routeSource).toContain("团队任务");
    expect(routeSource).toContain("启动团队讨论");
    expect(routeSource).toContain("teamTaskTopic");
    expect(routeSource).toContain("linkedRoomBusy");
    expect(routeSource).toContain("最近团队任务");
    expect(routeSource).toContain("styles.teamRoundPanel");
    expect(routeSource).toContain("styles.teamRoundCard");
    expect(routeSource).toContain("查看完整群聊");
    expect(routeSource).toContain("styles.teamTaskForm");
    expect(routeSource).toContain("科研流程");
    expect(routeSource).toContain("TeamWorkflowOrchestration");
    expect(routeSource).toContain("teamWorkflowQuery");
    expect(routeSource).toContain("teamWorkflowCandidatesQuery");
    expect(routeSource).toContain("teamWorkflowValidationSummary");
    expect(routeSource).toContain("teamWorkflowKnowledgeIngestionStatus");
    expect(routeSource).toContain("teamWorkflowOfficialModelEvidenceStatus");
    expect(routeSource).toContain("workflowStateLabel");
    expect(routeSource).toContain("workflowQualityTone");
    expect(routeSource).toContain("workflowIngestionStatusLabel");
    expect(routeSource).toContain("workflowIngestionTone");
    expect(routeSource).toContain("styles.workflowPanel");
    expect(routeSource).toContain("styles.workflowStats");
    expect(routeSource).toContain("TeamWorkflowModelEvidenceStatusPanel");
    expect(routeSource).toContain("TeamWorkflowCoordinationStatusPanel");
    expect(routeSource).toContain("TeamWorkflowKnowledgeIngestionStatusPanel");
    expect(routeSource).toContain("TeamWorkflowCandidateGraphStatusPanel");
    expect(routeSource).toContain("TeamWorkflowSourceQualityStatusPanel");
    expect(routeSource).toContain("TeamWorkflowPaperNoteChunkStatusPanel");
    expect(teamWorkflowStatusPanelsSource).toContain("styles.workflowIngestionPanel");
    expect(teamWorkflowStatusPanelsSource).toContain("styles.workflowIngestionStages");
    expect(teamWorkflowStatusPanelsSource).toContain("styles.workflowIngestionBoundary");
    expect(teamWorkflowStatusPanelsSource).toContain("styles.workflowGraphPanel");
    expect(workflowGraphViewSource).toContain("styles.workflowGraphFrame");
    expect(workflowGraphViewSource).toContain("styles.workflowGraphNode");
    expect(teamWorkflowStatusPanelsSource).toContain("styles.workflowGraphBoundary");
    expect(routeSource).not.toContain("styles.workflowCandidateList");
    expect(teamWorkflowCandidatePreviewPanelStylesSource).toContain("workflowCandidateList");
    expect(teamSourceCollectionGraphPanelStyles.workflowCandidateList).toContain("overflow-auto");
    expect(routeSource).toContain("styles.workflowValidation");
    expect(routeSource).toContain("RESEARCH_WORKSPACE_NAV_ITEMS");
    expect(routeSource).toContain("ResearchWorkspaceView");
    expect(routeSource).toContain("researchWorkspaceView");
    expect(routeSource).toContain("selectResearchWorkspaceView");
    expect(routeSource).toContain("selectTeamRecord");
    expect(routeSource).toContain("renderResearchStageLauncher");
    expect(routeSource).toContain("researchWorkspaceViewLabel");
    expect(routeSource).toContain("styles.workspaceResearch");
    expect(routeSource).toContain("styles.workspaceResearchCanvas");
    expect(routeSource).toContain("styles.researchInspector");
    expect(routeSource).toContain("styles.researchCanvasPanelHidden");
    expect(routeSource).toContain("styles.aiSearchScopePanel");
    expect(routeSource).toContain("styles.aiSearchSourceGroups");
    expect(routeSource).toContain("styles.aiSearchSourceItem");
    expect(routeSource).toContain('researchWorkspaceView !== "overview"');
    expect(routeSource).not.toContain("科研三阶段索引");
    expect(routeSource).not.toContain("团队专属阶段页");
    expect(routeSource).toContain("三阶段");
    expect(routeSource).toContain("ResearchStageWorkspaceView");
    expect(routeSource).toContain("researchWorkspaceStageRoute");
    expect(routeSource).toContain('view: "knowledge_collection"');
    expect(routeSource).toContain('view: "experiment"');
    expect(routeSource).toContain('view: "iteration"');
    expect(routeSource).toContain('key: "experiment_planner"');
    expect(routeSource).toContain('challenge_cup_experiment_planner');
    expect(routeSource).toContain('key: "experiment_ledger"');
    expect(routeSource).toContain('challenge_cup_experiment_ledger');
    expect(routeSource).toContain('key: "iteration_planner"');
    expect(routeSource).toContain('challenge_cup_iteration_planner');
    expect(routeSource).toContain('key: "iteration_versioning"');
    expect(routeSource).toContain('challenge_cup_versioning');
    expect(routeSource).not.toContain('key: "paper_note_extraction"');
    expect(routeSource).not.toContain('key: "neuro_mechanism"');
    expect(routeSource).not.toContain('key: "mechanism_mapping"');
    expect(routeSource).not.toContain('key: "challenge_cup_delivery"');
    expect(routeSource).not.toContain('view: "source_collection", zh: "资料搜集"');
    expect(routeSource).toContain("组织画布");
    expect(routeSource).toContain('canvas: { zh: "组织画布", en: "Canvas" }');
    expect(routeSource).toContain("搜索资料");
    expect(routeSource).toContain("科研控制台");
    expect(routeSource).toContain("开始知识搜集");
    expect(routeSource).toContain("搜索下一批");
    expect(routeSource).toContain("新一轮搜集");
    expect(routeSource).toContain("继续审查");
    expect(routeSource).toContain("准备实验");
    expect(runModelSource).toContain("正在团队搜索");
    expect(routeSource).toContain("知识搜集操作台");
    expect(routeSource).toContain("sourceCollectionDecisionText");
    expect(routeSource).toContain("下一步");
    expect(routeSource).toContain("待执行");
    expect(routeSource).toContain("原始记录");
    expect(routeSource).toContain("原始资料");
    expect(routeSource).toContain("可点击来源");
    expect(routeSource).toContain("本地文件");
    expect(evidenceModelSource).toContain("缺少来源");
    expect(routeSource).toContain("SourceCollectionSourceFilter");
    expect(routeSource).toContain("SOURCE_COLLECTION_SOURCE_FILTERS");
    expect(routeSource).toContain("sourceCollectionSourceFilterLabel");
    expect(routeSource).toContain("sourceCollectionSourceFilter");
    expect(routeSource).toContain("sourceCollectionFilteredRecords");
    expect(routeSource).toContain("sourceCollectionFilteredRunCandidates");
    expect(routeSource).toContain("sourceCollectionFilterMatches");
    expect(evidenceModelSource).toContain("论文网页/DOI");
    expect(evidenceModelSource).toContain("PDF");
    expect(routeSource).toContain("sourceCollectionCandidateProvenance");
    expect(routeSource).toContain("sourceCollectionRecordProvenance");
    expect(routeSource).toContain("sourceCollectionRecordClickableSourceCount");
    expect(routeSource).toContain("sourceCollectionRecordLocalFileCount");
    expect(routeSource).toContain("sourceCollectionRecordMissingSourceCount");
    expect(routeSource).toContain("sourceCollectionRawRecordCount");
    expect(routeSource).toContain("sourceCollectionRunCandidateCount");
    expect(routeSource).toContain("sourceCollectionRunPendingScreeningCount");
    expect(routeSource).toContain("sourceCollectionPendingCandidateImportCount");
    expect(routeSource).toContain("/api/data-processing/runs/${encodeURIComponent(selectedSourceCollectionRunEffectiveId)}/records");
    expect(teamSourceCollectionConversationPanelSource).toContain("还有 ${pendingCandidateImportCount} 条原始记录尚未进入候选库");
    expect(evidenceModelSource).toContain('label: "DOI"');
    expect(evidenceModelSource).toContain("https://doi.org/");
    expect(routeSource).toContain("点击查看来源详情");
    expect(routeSource).toContain("sourceCollectionCandidateTrace");
    expect(routeSource).toContain("selectedSourceCollectionCandidateId");
    expect(routeSource).toContain("TeamSourceCollectionSourceDetailPanel");
    expect(routeSource).toContain("TeamSourceCollectionSourceDetailFact[]");
    expect(evidenceModelSource).toContain("打开论文 DOI");
    expect(routeSource).toContain("打开 API 原文");
    expect(teamSourceCollectionSourceDetailPanelSource).toContain("sourceCollectionSourceDetailPanel");
    expect(teamSourceCollectionSourceDetailPanelSource).toContain("sourceCollectionSearchEvidence");
    expect(teamSourceCollectionSourceDetailPanelSource).toContain("查看搜索证据");
    expect(evidenceModelSource).toContain("sourceCollectionIsMachineEvidenceUrl");
    expect(routeSource).toContain("仅有搜索记录，缺少可读来源");
    expect(routeSource).not.toContain("打开搜索页");
    expect(teamSourceCollectionConversationPanelSource).toContain("本轮原始资料记录");
    expect(routeSource).toContain("当前筛选没有资料");
    expect(routeSource).toContain("查看全部来源");
    expect(routeSource).toContain("搜索问题");
    expect(routeSource).toContain("待 Agent 复核");
    expect(routeSource).not.toContain("<span>{lang === \"zh\" ? \"缓存\" : \"cache\"}");
    expect(routeSource).toContain("sourceCollectionScreeningButtonText");
    expect(routeSource).toContain("sourceCollectionScreeningDisabled");
    expect(routeSource).toContain("openSourceCollectionScreeningPanel");
    expect(routeSource).toContain("runSourceCollectionScreeningAction");
    expect(routeSource).toContain("assessSourceQualityBatchMutation");
    expect(routeSource).toContain("sourceCollectionExtractorAgentId");
    expect(routeSource).toContain("source-quality/assess-batch");
    expect(runModelSource).toContain("执行资料提炼复核");
    expect(routeSource).toContain("Agent 复核中");
    expect(routeSource).toContain("sourceCollectionExpandedPanelId");
    expect(routeSource).toContain("sourceCollectionFocusedPanelId");
    expect(routeSource).toContain("sourceCollectionControlPanelRef");
    expect(routeSource).toContain("TeamSourceCollectionControlsPanel");
    expect(teamSourceCollectionControlsPanelSource).toContain("source-collection-actions");
    expect(teamSourceCollectionControlsPanelSource).toContain("sourceCollectionControlPanel");
    expect(teamSourceCollectionControlsPanelSource).toContain("forwardRef");
    expect(routeSource).toContain("TeamSourceCollectionManualWritebackPanel");
    expect(routeSource).toContain("renderSourceCollectionManualWritebackPanel");
    expect(teamSourceCollectionManualWritebackPanelSource).toContain("workflowSourceCollectionDetails");
    expect(teamSourceCollectionManualWritebackPanelSource).toContain("workflowSourceCollectionOutputForm");
    expect(teamSourceCollectionManualWritebackPanelSource).toContain("兜底手工回写");
    expect(teamSourceCollectionManualWritebackPanelSource).toContain("写入一条资料结果");
    expect(teamSourceCollectionManualWritebackPanelSource).toContain("分工任务");
    expect(teamSourceCollectionManualWritebackPanelSource).toContain("sourceTypeLabel(sourceType)");
    expect(teamSourceCollectionManualWritebackPanelSource).toContain("回写并导入候选");
    expect(teamSourceCollectionManualWritebackPanelSource).toContain("wrapInDetails");
    expect(routeSource).not.toContain("sourceCollectionPanelClassName");
    expect(teamSourceCollectionPanelFrameStylesSource).toContain("workflowSourceCollectionDetails");
    expect(teamSourceCollectionPanelFrameStylesSource).toContain("sourceCollectionFocusedPanel");
    expect(teamSourceCollectionStandaloneStagePanelSource).toContain("TeamStagePipeline");
    expect(routeSource).toContain("container.scrollTo");
    expect(routeSource).toContain("HTMLDetailsElement");
    expect(routeSource).toContain("暂无候选");
    expect(routeSource).toContain("TeamSourceCollectionScreeningPanel");
    expect(teamSourceCollectionScreeningPanelSource).toContain("source-collection-screening-panel");
    expect(teamSourceCollectionScreeningPanelSource).toContain("sourceCollectionScreeningListShell");
    expect(teamSourceCollectionScreeningPanelSource).toContain("sourceCollectionScreeningScrollHint");
    expect(teamSourceCollectionScreeningPanelSource).toContain("资料提炼复核候选列表，可向下滚动查看更多");
    expect(teamSourceCollectionScreeningPanelSource).toContain("向下滚动查看更多本页候选");
    expect(routeSource).toContain("TeamSourceCollectionCandidatePanel");
    expect(teamSourceCollectionCandidatePanelSource).toContain("source-collection-candidates-panel");
    expect(routeSource).toContain("TeamSourceCollectionGraphPanel");
    expect(routeSource).toContain("source-collection-graph-panel");
    expect(teamSourceCollectionGraphPanelSource).toContain("source-collection-graph-panel");
    expect(teamSourceCollectionGraphPanelSource).toContain("workflowGraphStats");
    expect(routeSource).toContain("TeamSourceCollectionMemoryPanel");
    expect(teamSourceCollectionMemoryPanelSource).toContain("source-collection-memory-panel");
    expect(routeSource).not.toContain("researchView=candidates");
    expect(routeSource).toContain("查看提炼结果");
    expect(routeSource).toContain("openSourceCollectionCandidatePanel");
    expect(routeSource).toContain("renderSourceCollectionCandidatePanel");
    expect(routeSource).not.toContain("sourceCollectionRunCandidates.slice(0, 6)");
    expect(routeSource).toContain("TeamSourceCollectionExtractionRecoveryPanel");
    expect(routeSource).toContain("renderSourceCollectionExtractionRecoveryPanel");
    expect(teamSourceCollectionExtractionRecoveryPanelSource).toContain("sourceCollectionExtractionRecoveryStats");
    expect(teamSourceCollectionExtractionRecoveryPanelSource).toContain("sourceCollectionExtractionRecoveryActions");
    expect(teamSourceCollectionExtractionRecoveryPanelSource).toContain("titleLabel");
    expect(teamSourceCollectionExtractionRecoveryPanelSource).toContain("failedLabel");
    expect(teamSourceCollectionExtractionRecoveryPanelSource).toContain("recoverLabel");
    expect(teamSourceCollectionExtractionRecoveryPanelSource).toContain("可保留");
    expect(routeSource).toContain("进入 Agent 私聊");
    expect(routeSource).toContain("runSourceCollectionCandidateExtractionAction");
    expect(routeSource).toContain("runSourceCollectionScreeningAction");
    expect(routeSource).toContain("openSourceCollectionStageAgentChat(\"extraction\")");
    expect(routeSource).toContain("sourceCollectionExtractionRecoveryFailureCount");
    expect(routeSource).toContain("sourceCollectionExtractionRecoverySalvageCount");
    expect(routeSource).toContain("deriveSourceCollectionExcludedRecoveryState");
    expect(routeSource).toContain("sourceCollectionExtractionExcludedRecoveryState");
    expect(evidenceModelSource).toContain("剩余资料已被排除");
    expect(evidenceModelSource).toContain("查看排除原因");
    expect(evidenceModelSource).toContain("提炼排除项确认");
    expect(routeSource).toContain("sourceCollectionExtractionCanProceedAfterExclusions");
    expect(evidenceModelSource).toContain("可继续推进");
    expect(routeSource).toContain('onPress={() => void openSourceCollectionStageAgentChat("extraction")}');
    expect(routeSource).not.toContain("sourceCollectionRunCandidates.slice(0, 12)");
    expect(routeSource).not.toContain("SOURCE_COLLECTION_RESULT_PREVIEW_LIMIT");
    expect(routeSource).toContain("sourceCollectionStageCard");
    expect(routeSource).toContain("detailLabel");
    expect(teamSourceCollectionStandaloneStagePanelSource).toContain("onActivate={module.onDetail}");
    expect(teamSourceCollectionActiveStagePanelSource).toContain("sourceCollectionStagePrimaryAction");
    expect(teamSourceCollectionActiveStagePanelSource).toContain("sourceCollectionStageSecondaryAction");
    expect(routeSource).not.toContain("styles.sourceCollectionStagePrimaryAction");
    expect(routeSource).not.toContain("styles.sourceCollectionStageSecondaryAction");
    expect(routeSource).not.toContain("sourceCollectionStageActionRow");
    expect(routeSource).not.toContain("module.onAgentChat");
    expect(routeSource).toContain("SourceCollectionStepState");
    expect(routeSource).toContain("SourceCollectionStageModuleId");
    expect(routeSource).toContain("SourceCollectionStageCardProjection");
    expect(routeSource).toContain("sourceCollectionStageCards");
    expect(routeSource).toContain("sourceCollectionStageCardSummary");
    expect(routeSource).toContain("sourceCollectionStageCardById");
    expect(routeSource).toContain("excludedSourceCount");
    expect(routeSource).toContain("filteredExcludedCount");
    expect(routeSource).toContain("无效来源已过滤");
    expect(stageProjectionSource).toContain("已移出");
    expect(routeSource).toContain("sourceCollectionDisplayedCandidateCount");
    expect(routeSource).toContain("sourceCollectionPrimaryDataLoading");
    expect(routeSource).toContain("sourceCollectionSourceQualityLoading");
    expect(routeSource).toContain("sourceCollectionScreeningDataLoading");
    expect(routeSource).toContain("sourceCollectionLoadingText");
    expect(routeSource).toContain("sourceCollectionLoadingSummary");
    expect(routeSource).toContain("sourceCollectionDisplayedCandidateFilterCounts");
    expect(routeSource).toContain("sourceCollectionCandidateProjectionFallbackCount");
    expect(routeSource).toContain("candidateListAwaitingRefresh");
    expect(evidenceModelSource).toContain("正在加载资料提炼结果");
    expect(routeSource).toContain("正在读取资料提炼结果");
    expect(evidenceModelSource).toContain("列表正在同步");
    expect(routeSource).toContain("sourceCollectionStageProjectionState");
    expect(stageProjectionSource).toContain("agent_interrupted");
    expect(stageProjectionSource).toContain("agent_done_artifact_pending");
    expect(routeSource).toContain("latestTask");
    expect(stageProjectionSource).toContain("blockingReasons");
    expect(routeSource).toContain("sourceCollectionStageUserStatusLabel");
    expect(routeSource).toContain("sourceCollectionStageUserSummary");
    expect(routeSource).toContain("sourceCollectionStageRecoveryStatusLabel");
    expect(routeSource).not.toContain("sourceCollectionStageTechnicalDetails");
    expect(routeSource).toContain("sourceCollectionCandidateEmptyStateText");
    expect(stageProjectionSource).toContain("已收到 Agent 结果，等待生成可用资料");
    expect(stageProjectionSource).toContain("Agent 返回的候选 ID 没有匹配到本轮资料");
    expect(routeSource).not.toContain("技术详情");
    expect(evidenceModelSource).toContain("待补提炼");
    expect(stageProjectionSource).toContain("已中断，需要继续");
    expect(stageProjectionSource).toContain("继续这次任务");
    expect(routeSource).toContain("待 Agent 复核");
    expect(evidenceModelSource).toContain("继续补全提炼");
    expect(routeSource).not.toContain("sourceCollectionStageBlockingReasonLabel(module.projection.blockingReasons[0], lang)");
    expect(stageProjectionSource).toContain("sourceCollectionStageBlockingReasonsLabel");
    expect(stageProjectionSource).toContain("sourceCollectionStageArtifactSummaryLabel");
    expect(routeSource).not.toContain("待 Agent 产出");
    expect(routeSource).not.toContain("已有输入，等待该阶段生成目标产物。");
    expect(routeSource).not.toContain("证据 ${evidenceCount}");
    expect(routeSource).not.toContain("candidateProjection.blockingReasons.join");
    expect(routeSource).not.toContain("{module.projection.blockingReasons[0]}</small>");
    expect(evidenceModelSource).toContain("evidenceRefCount");
    expect(stageProjectionSource).toContain("materializedSources");
    expect(stageProjectionSource).toContain("SourceCollectionCoverageSummary");
    expect(routeSource).toContain("coverageSummary");
    expect(routeSource).toContain("currentCoverageSummary");
    expect(stageProjectionSource).toContain("partial_current_inputs");
    expect(stageProjectionSource).toContain("当前批次还有资料未处理");
    expect(stageProjectionSource).toContain("SourceCollectionStageClosureSummary");
    expect(routeSource).toContain("closureSummary");
    expect(stageProjectionSource).toContain("SourceCollectionStageTaskToolProgress");
    expect(stageProjectionSource).toContain("taskToolProgress");
    expect(stageProjectionSource).toContain("SourceCollectionStageCompletionGate");
    expect(stageProjectionSource).toContain("SourceCollectionStageActionReadinessProjection");
    expect(stageProjectionSource).toContain("actionReadiness?: SourceCollectionStageActionReadinessProjection");
    expect(routeSource).toContain("sourceCollectionStageBackendActionReadiness");
    expect(routeSource).toContain("sourceCollectionStageActionLabelFor");
    expect(stageProjectionSource).toContain("completionGatePassed");
    expect(stageProjectionSource).toContain("sourceCollectionTaskToolProgressMetric");
    expect(stageProjectionSource).toContain("检查项");
    expect(routeSource).toContain("sourceCollectionStageLaunchActive");
    expect(routeSource).toContain("sourceCollectionStageLaunchSummary");
    expect(routeSource).toContain("Agent 已启动，正在进入私聊");
    expect(runModelSource).toContain("等待 Agent 回写");
    expect(routeSource).toContain("sourceCollectionStageDisplayState");
    expect(stageProjectionSource).toContain("sourceCollectionStageInterruptedSummary");
    expect(stageProjectionSource).toContain("剩余检查项");
    expect(routeSource).toContain('sourceCollectionStageModules.find((module) => module.state === "failed")');
    expect(routeSource).not.toContain("仍需完成检查项或生成本阶段产物");
    expect(routeSource).toContain("invalidRecordIds");
    expect(stageProjectionSource).toContain("本轮未生成候选资料");
    expect(evidenceModelSource).toContain("没有生成候选资料");
    expect(stageProjectionSource).toContain("完整 recordId");
    expect(stageProjectionSource).toContain("sourceCollectionCoverageMetric");
    expect(routeSource).toContain("invalidCandidateIds");
    expect(stageProjectionSource).toContain("materializedContentExtraction");
    expect(evidenceModelSource).toContain("继续补全提炼");
    expect(evidenceModelSource).toContain("继续补全提炼");
    expect(routeSource).not.toContain("Agent 已回写，仍待补产物");
    expect(routeSource).toContain("已提炼");
    expect(evidenceModelSource).toContain("待补提炼");
    expect(routeSource).toContain("已审");
    expect(routeSource).toContain("待 Agent 复核");
    expect(routeSource).not.toContain("未匹配资料");
    expect(routeSource).toContain("graphForSelectedSourceRun");
    expect(routeSource).toContain("parseSourceCollectionStageModuleId");
    expect(routeSource).toContain("collectionStage");
    expect(routeSource).toContain("selectedSourceCollectionStageId");
    expect(routeSource).toContain("selectSourceCollectionStage");
    expect(routeSource).toContain("renderSourceCollectionActiveStagePanel");
    expect(routeSource).toContain("researchStageAgentDirectChatRoute");
    expect(routeSource).toContain("sourceCollectionStageReturnRoute");
    expect(routeSource).toContain("sourceCollectionStageChatReturnLabel");
    expect(routeSource).toContain("params.set(\"returnTo\", normalizedReturnTo)");
    expect(routeSource).toContain("params.set(\"returnLabel\", normalizedReturnLabel)");
    expect(routeSource).toContain("openSourceCollectionStageAgentChat");
    expect(routeSource).toContain('type SourceCollectionStageAgentChatStatus = "ready" | "loading" | "error" | "repair"');
    expect(routeSource).toContain("sourceCollectionStageAgentChatState(stageId");
    expect(routeSource).toContain("agentSummaryQuery.isPending || agentSummaryQuery.isFetching");
    expect(routeSource).toContain("primaryStageAgentChatLoading");
    expect(routeSource).toContain("加载 Agent...");
    expect(routeSource).toContain('chatState.status === "repair"');
    expect(routeSource).toContain("onAction: () => void startSourceCollectionStageSessionTask(\"finding\")");
    expect(routeSource).toContain("onAction: sourceCollectionExtractionCanProceedAfterExclusions");
    expect(routeSource).toContain(": () => void startSourceCollectionStageSessionTask(\"extraction\")");
    expect(routeSource).toContain("onAction: () => void startSourceCollectionStageSessionTask(\"relations\")");
    expect(routeSource).toContain("onAction: () => void startSourceCollectionStageSessionTask(\"ingestion\")");
    expect(routeSource).toContain("repairChallengeCupTeamAgentsMutation");
    expect(routeSource).toContain("/challenge-cup-agents/repair");
    expect(routeSource).toContain("repairKnowledgeExpansionTeamAgentsMutation");
    expect(routeSource).toContain("/knowledge-expansion-agents/repair");
    expect(routeSource).toContain("修复团队 Agent");
    expect(routeSource).toContain("进入 Agent 私聊");
    expect(routeSource).toContain("Agent 私聊");
    expect(routeSource).not.toContain("window.alert(lang === \"zh\"");
    expect(routeSource).not.toContain("sourceCollectionStageChatRoute");
    expect(routeSource).not.toContain("sourceCollectionStageRoomKey");
    expect(routeSource).not.toContain("createSourceCollectionStageChatRoomMutation");
    expect(routeSource).not.toContain("sourceCollectionStageViewMode");
    expect(routeSource).not.toContain("SourceCollectionStageViewMode");
    expect(routeSource).toContain("sourceCollectionPageItems");
    expect(routeSource).toContain("renderSourceCollectionPagination");
    expect(routeSource).toContain("stopSourceCollectionPaginationEvent");
    expect(routeSource).toContain("onContain={stopSourceCollectionPaginationEvent}");
    expect(routeSource).toContain("sourceCollectionExtractionDefaultPanelId");
    expect(routeSource).toContain("sourceCollectionExpandedPanelId === \"source-collection-screening-panel\"");
    expect(routeSource).toContain("sourceCollectionExpandedPanelId === \"source-collection-candidates-panel\"");
    expect(routeSource).not.toContain("preventSourceCollectionPanelSummaryToggle");
    expect(routeSource).not.toContain("onClick={preventSourceCollectionPanelSummaryToggle}");
    expect(routeSource).not.toContain("sourceCollectionTraceMessagesForStage");
    expect(routeSource).not.toContain("renderSourceCollectionStageProcessPanel");
    expect(routeSource).toContain("selected: module.id === selectedSourceCollectionStageId");
    expect(teamSourceCollectionStandaloneStagePanelSource).toContain("selected={module.selected}");
    expect(routeSource).not.toContain("sourceCollectionStageOperationPanel");
    expect(routeSource).not.toContain("<small>{module.summary}</small>");
    expect(routeSource).not.toContain("sourceCollectionStageProjectionTaskMetric(module.projection");
    expect(routeSource).not.toContain("<summary>{lang === \"zh\" ? \"技术详情\" : \"Technical details\"}</summary>");
    const graphStateExpression = routeSource.slice(
      routeSource.indexOf("const sourceCollectionGraphStepState"),
      routeSource.indexOf("const sourceCollectionMemoryStepState"),
    );
    const memoryStateExpression = routeSource.slice(
      routeSource.indexOf("const sourceCollectionMemoryStepState"),
      routeSource.indexOf("const sourceCollectionCollectionActionLabel"),
    );
    expect(graphStateExpression).not.toContain("teamWorkflowCandidateGraphQuery.isFetching");
    expect(memoryStateExpression).not.toContain("teamWorkflowKnowledgeIngestionStatusQuery.isFetching");
    expect(routeSource).not.toContain("className={styles.sourceCollectionStageMiniFlow}");
    expect(teamSourceCollectionActiveStagePanelSource).toContain("sourceCollectionStageHandoffNext");
    expect(routeSource).not.toContain("Agent过程");
    expect(routeSource).toContain("activeModule.nextLabel");
    expect(routeSource).toContain("activeModule.onAction");
    expect(routeSource).toContain("sourceCollectionStagePrimaryAgentBinding(activeModule.id)");
    expect(routeSource).toContain("配置 Agent");
    expect(routeSource).toContain("绑定 Agent");
    expect(routeSource).toContain("sourceCollectionStageModules.map");
    expect(routeSource).toContain("sourceCollectionStepClassName");
    expect(routeSource).not.toContain("下一步操作");
    expect(routeSource).toContain("TeamSourceCollectionActiveStagePanel");
    expect(teamSourceCollectionActiveStagePanelSource).toContain("sourceCollectionStageWorkspace");
    expect(teamSourceCollectionActiveStagePanelSource).toContain("sourceCollectionStageHandoffNext");
    expect(teamSourceCollectionActiveStagePanelSource).toContain("sourceCollectionStageChatActions");
    expect(teamSourceCollectionActiveStagePanelSource).toContain("当前阶段子页");
    expect(teamSourceCollectionControlsPanelSource).toContain("步骤侧栏");
    expect(teamSourceCollectionActiveStagePanelSource).toContain("输入");
    expect(teamSourceCollectionActiveStagePanelSource).toContain("输出");
    expect(routeSource).toContain("styles.researchStageCardHead");
    expect(routeSource).toContain("styles.researchStageCardMetrics");
    expect(routeSource).toContain("RESEARCH_STAGE_AGENT_ROLES");
    expect(routeSource).toContain("researchStageAgentBindingsByStage");
    expect(routeSource).toContain("renderResearchStageAgentSummary(stageType)");
    expect(routeSource).toContain("renderResearchStageAgentPanel(stageType)");
    expect(routeSource).not.toContain('renderResearchStageAgentPanel("knowledge_collection", "compact")');
    expect(routeSource).toContain("SOURCE_COLLECTION_STAGE_AGENT_KEYS");
    expect(routeSource).toContain("sourceCollectionStageAgentBindings(stageId)");
    expect(routeSource).not.toContain("renderSourceCollectionStageAgentStrip");
    expect(teamStageCardSource).toContain('target.closest("button, a")');
    expect(routeSource).toContain("renderSourceCollectionStageAgents(activeModule.id)");
    expect(routeSource).toContain("TeamSourceCollectionStageAgentsPanel");
    expect(routeSource).toContain("agentCards: TeamSourceCollectionStageAgentCard[]");
    expect(teamSourceCollectionStageAgentsPanelSource).toContain("当前步骤 Agent 配置");
    expect(teamSourceCollectionStageAgentsPanelSource).toContain("sourceCollectionStageAgentCardBody");
    expect(teamSourceCollectionStageAgentsPanelSource).toContain("sourceCollectionStageAgentCardActions");
    expect(teamSourceCollectionStageAgentsPanelSource).toContain("sourceCollectionStageAgentPanel");
    expect(routeSource).not.toContain("sourceCollectionStageAgentStrip");
    expect(routeSource).not.toContain("sourceCollectionStageAgentChips");
    expect(routeSource).not.toContain("sourceCollectionStageAgentChip");
    expect(routeSource).toContain("researchStageAgentManagementRoute(binding.agentId)");
    expect(routeSource).not.toContain("const chatRoute = researchStageAgentDirectChatRoute");
    expect(routeSource).toContain("Agent 管理");
    expect(routeSource).not.toContain("还需补充资料");
    expect(routeSource).toContain("sourceCollectionSearchOpenAssignmentCount");
    expect(routeSource).toContain("sourceCollectionDownstreamOpenAssignmentCount");
    expect(routeSource).toContain("SOURCE_COLLECTION_SEARCH_EXECUTION_ROLES");
    expect(routeSource).toContain("个搜索任务待执行");
    expect(runModelSource).toContain("搜索已停止，还有");
    expect(routeSource).not.toContain("sourceCollectionOpenAssignmentCount > 0 ? <Search");
    expect(routeSource).toContain("条资料通过审查");
    expect(routeSource).toContain("Agent 重新提炼复核");
    expect(routeSource).toContain("sourceCollectionIngestorAgentId");
    expect(routeSource).toContain("runKnowledgeIngestionPrecheckMutation");
    expect(routeSource).toContain("knowledge-ingestion/precheck");
    expect(routeSource).toContain("runSourceCollectionGraphAction");
    expect(routeSource).not.toContain("runSourceCollectionMemoryPrecheckAction");
    expect(routeSource).toContain("runKnowledgeCollectionLoopAction");
    expect(routeSource).toContain("runKnowledgeCollectionCompletionMutation");
    expect(routeSource).toContain("/workflow-orchestration/knowledge-collection/complete");
    expect(routeSource).toContain("sourceCollectionActionRunId");
    expect(routeSource).toContain("sourceCollectionSummary?.runId");
    expect(routeSource).toContain("startKnowledgeCollectionCompletionForRun(sourceCollectionActionRunId");
    const sourceCollectionCompletionDisabledSource = routeSource.slice(
      routeSource.indexOf("const sourceCollectionLoopActionDisabled ="),
      routeSource.indexOf("const sourceCollectionLoopActionLabel ="),
    );
    expect(sourceCollectionCompletionDisabledSource).not.toContain("!selectedSourceCollectionRun");
    expect(routeSource).toContain("extractionAgentId: sourceCollectionExtractorAgentId");
    expect(routeSource).toContain("agent_approved_only");
    expect(routeSource).toContain("Agent 生成关系图");
    expect(routeSource).toContain("通知资料入库 Agent");
    expect(routeSource).toContain("开始第一轮闭环");
    expect(routeSource).toContain("继续本轮闭环");
    expect(routeSource).toContain("开始下一轮闭环");
    expect(routeSource).toContain("renderKnowledgeCollectionCompletionFlowPanel");
    expect(routeSource).toContain("knowledgeCompletionFlowPanel");
    expect(routeSource).toContain("sourceCollectionCompletionFlowNodes");
    expect(routeSource).toContain("selectedTeamKnowledgeIngestionLatestWorkRun");
    expect(routeSource).toContain("flowVisualization");
    expect(routeSource).toContain("latestWorkRun");
    expect(routeSource).toContain('nextParams.set("researchView", "canvas")');
    expect(routeSource).toContain('selectResearchWorkspaceView("canvas")');
    expect(routeSource).toContain("一键流程图");
    expect(routeSource).toContain("阶段详情");
    expect(routeSource).toContain("Agent 私聊");
    expect(routeSource).toContain("重试失败节点");
    expect(routeSource).toContain("openSourceCollectionStageAgentChat(node.stageId)");
    expect(routeSource).toContain("提炼后通知入库 Agent");
    expect(routeSource).toContain("资料已写入团队知识库");
    expect(routeSource).toContain("sourceCollectionPrecheckCandidateCount");
    expect(routeSource).toContain("sourceCollectionIngestCandidateCount");
    expect(routeSource).toContain("sourceCollectionCanBuildGraph");
    expect(routeSource).toContain("sourceCollectionGraphActionDisabled");
    expect(routeSource).toContain("审查并生成关系图");
    expect(routeSource).toContain("sourceCollectionMemoryActionDisabled");
    expect(routeSource).toContain("sourceCollectionMemoryActionLabel");
    expect(routeSource).toContain("maxCandidates: Math.max(1, Math.min(80, sourceCollectionIngestCandidateCount))");
    expect(routeSource).toContain("forceReview: precheckCandidateCount <= 0 && displayedCandidateCount > 0");
    expect(routeSource).toContain("forceReview: sourceCollectionRunApprovedCount <= 0 && sourceCollectionDisplayedCandidateCount > 0");
    expect(routeSource).toContain("可通知资料入库 Agent");
    expect(routeSource).toContain("条候选资料");
    expect(routeSource).not.toContain("onAction: refreshSourceCollectionGraph");
    expect(routeSource).not.toContain("onAction: refreshSourceCollectionMemoryPrecheck");
    expect(routeSource).toContain("forceRescreen");
    expect(routeSource).toContain("force: forceRescreen");
    expect(teamSourceCollectionScreeningPanelSource).toContain("sourceCollectionPanelActions");
    expect(routeSource).toContain("Source Extractor Agent re-screened already assessed source_manifest candidates");
    expect(routeSource).toContain("通知资料入库 Agent");
    expect(routeSource).not.toContain("待继续搜索");
    expect(routeSource).toContain("/storage/open");
    expect(teamSourceCollectionStorageActionsPanelSource).toContain("本轮产物");
    expect(routeSource).toContain("打开批次目录");
    expect(teamSourceCollectionStorageActionsPanelSource).toContain("更多证据文件");
    expect(routeSource).toContain("sourceCollectionStorageTargetForRef");
    expect(routeSource).toContain("sourceCollectionStatusLabel");
    expect(routeSource).toContain("sourceCollectionAgentRoleLabel");
    expect(routeSource).not.toContain("currentTraceMessage");
    expect(routeSource).toContain("结果");
    expect(routeSource).not.toContain("Agent 执行过程");
    expect(routeSource).not.toContain("过程</button>");
    expect(routeSource).toContain("TeamSourceCollectionConversationPanel");
    expect(teamSourceCollectionConversationPanelSource).toContain("sourceCollectionResultsPanel");
    expect(teamSourceCollectionConversationPanelSource).toContain("source-collection-results");
    expect(teamSourceCollectionConversationPanelSource).toContain("TeamSourceResultStats");
    expect(teamSourceCollectionConversationPanelSource).toContain("sourceCollectionResultWarning");
    expect(routeSource).toContain("TeamSourceResultList");
    expect(routeSource).toContain("TeamSourceResultItem");
    expect(routeSource).toContain("sourceCollectionResultTone");
    expect(routeSource).toContain("resultStatusLabel");
    expect(routeSource).toContain("当前过滤条件下没有候选资料");
    expect(routeSource).toContain("当前过滤条件下没有入库关系节点");
    expect(routeSource).toContain("当前过滤条件下没有入库资料");
    expect(routeSource).toContain("sourceCollectionCandidateQualityState(candidate).approved");
    expect(routeSource).toContain("source_needs_quality_revision: \"需补资料\"");
    expect(routeSource).toContain("source_screened: \"已审查\"");
    expect(teamSourceCollectionCandidatePanelSource).toContain("sourceCollectionCandidateListShell");
    expect(teamSourceCollectionCandidatePanelSource).toContain("loading && !hasCandidates");
    expect(teamSourceCollectionCandidatePanelSource).toContain("sourceCollectionCandidateSkeletonRow");
    expect(routeSource).not.toContain("const resultPanel = selectedSourceCollectionStageId");
    expect(teamSourceCollectionActiveStagePanelSource).toContain('stageId === "ingestion"');
    expect(teamSourceCollectionActiveStagePanelSource).toContain("styles.sourceCollectionIngestionPanels");
    expect(teamSourceCollectionActiveStagePanelSource).toContain("renderGraphPanel()");
    expect(teamSourceCollectionActiveStagePanelSource).toContain("renderMemoryPanel()");
    expect(teamSourceCollectionActiveStagePanelSource).toContain('stageId === "extraction"');
    expect(teamSourceCollectionActiveStagePanelSource).toContain("styles.sourceCollectionExtractionPanels");
    expect(teamSourceCollectionActiveStagePanelSource).toContain("renderCandidatePanel()");
    expect(teamSourceCollectionActiveStagePanelSource).toContain("renderScreeningPanel()");
    expect(routeSource).toContain("renderGraphPanel={renderSourceCollectionGraphPanel}");
    expect(routeSource).toContain("renderMemoryPanel={renderSourceCollectionMemoryPanel}");
    expect(routeSource).toContain("renderCandidatePanel={renderSourceCollectionCandidatePanel}");
    expect(routeSource).toContain("renderScreeningPanel={renderSourceCollectionScreeningPanel}");
    const graphPanelOpenSource = routeSource.slice(
      routeSource.indexOf("<TeamSourceCollectionGraphPanel"),
      routeSource.indexOf("onToggle={(event) =>", routeSource.indexOf("<TeamSourceCollectionGraphPanel")),
    );
    expect(graphPanelOpenSource).toContain('selectedSourceCollectionStageId === "relations"');
    expect(graphPanelOpenSource).not.toContain('selectedSourceCollectionStageId === "ingestion"');
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionIngestionPanels).toContain("grid-rows-[auto_minmax(0,1fr)]");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionIngestionPanels).toContain("overflow-hidden");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionIngestionPanels).toContain("min-h-0");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionIngestionPanels).toContain("max-[860px]:min-h-[560px]");
    expect(teamSourceCollectionGraphPanelStyles.sourceCollectionGraphNodeListShell).toContain("max-h-[28vh]");
    expect(teamSourceCollectionGraphPanelStyles.sourceCollectionGraphNodeListShell).toContain("[scrollbar-gutter:stable]");
    expect(routeStylesSource).not.toContain(".sourceCollectionIngestionPanels");
    expect(routeStylesSource).not.toContain(".sourceCollectionGraphNodeListShell");
    expect(teamSourceCollectionMemoryPanelSource).toContain("sourceCollectionMemoryListShell");
    expect(teamSourceCollectionMemoryPanelStyles.sourceCollectionMemoryListShell).toContain("max-h-[44vh]");
    expect(teamSourceCollectionMemoryPanelStyles.sourceCollectionMemoryListShell).toContain("max-[860px]:max-h-[58vh]");
    expect(teamSourceCollectionMemoryPanelStyles.sourceCollectionMemoryListShell).toContain("[scrollbar-gutter:stable]");
    expect(routeSource).toContain("待 Agent 复核");
    expect(routeSource).not.toContain("待质检");
    expect(routeSource).not.toContain("workflowSourceCollectionPrimaryButton");
    expect(routeSource).toContain("启动设计");
    expect(routeSource).toContain("启动执行迭代");
    expect(routeSource).not.toContain("{researchWorkflowTeamSelected ? renderResearchWorkspaceNav() : null}");
    expect(routeSource).toContain("onSelectionChange={(key) => {");
    expect(routeSource).toContain("selectTeamRecord(nextTeam)");
    expect(routeSource).toContain("setResearchWorkspaceView(\"overview\")");
    expect(routeSource).not.toContain("{renderResearchWorkspaceNav()}");
    expect(routeSource).toContain("{renderResearchStageLauncher()}");
    expect(routeSource).toContain("researchWorkflowTeamSelected && !researchCanvasVisible");
    expect(routeSource).toContain("研究关系图");
    expect(routeSource).toContain("researchStageHeaderActions");
    expect(routeSource).toContain("researchCanvasRoute(selectedTeam?.teamId || RESEARCH_TEAM_ID)");
    expect(routeSource).toContain("搜索、提炼、审查与入库");
    expect(routeSource).toContain("资料寻找 / 资料提炼 / 资料关系整理 / 资料入库");
    expect(routeSource).toContain("研究问题 / 假设 / 控制变量 / 冻结设计");
    expect(routeSource).toContain("执行批次 / 结果评估 / 消融归因 / 优化迭代");
    expect(routeSource).toContain("lifecycleProjection");
    expect(routeSource).toContain("已设计 · 待执行");
    expect(routeSource).toContain("训练结果不参与本阶段完成判定");
    expect(routeSource).toContain("最近诊断单独展示，不覆盖主线结果");
    expect(routeSource).toContain("bestValidatedResultId");
    expect(routeSource).toContain("latestDiagnosticStatus");
    expect(routeSource).toContain("memoryContextSummary");
    expect(routeSource).toContain("团队记忆");
    expect(routeSource).toContain("已用记忆");
    expect(routeSource).toContain("forbiddenDuplicateExperimentCount");
    expect(researchMemoryEvidencePanelSource).toContain("查看 Claim Map 与变量边界");
    expect(researchMemoryEvidencePanelSource).toContain("claimStatusCounts");
    expect(researchMemoryEvidencePanelSource).toContain("allowedVariableContract");
    expect(researchMemoryEvidencePanelSource).toContain("claimMap");
    expect(researchMemoryEvidencePanelSource).toContain("data-memory-context-id");
    expect(routeSource).toContain("ResearchMemoryEvidencePanel");
    expect(routeSource).toContain('stage="experiment"');
    expect(routeSource).toContain('stage="iteration"');
    expect(routeSource).toContain("value === \"source_collection\"");
    expect(routeSource).toContain("return \"knowledge_collection\"");
    expect(routeSource).toContain('id="research-workflow-overview"');
    expect(routeSource).toContain('knowledge_collection: "research-workflow-knowledge-collection"');
    expect(teamSourceCollectionOverviewPanelSource).toContain('id="research-workflow-source-collection"');
    expect(routeSource).toContain('id="research-organization-canvas"');
    expect(routeSource).toContain('researchWorkspaceView === "canvas"');
    expect(routeSource).toContain('const researchCanvasReadOnly = researchWorkflowTeamSelected && researchWorkspaceView === "canvas"');
    expect(routeSource).toContain("const researchCanvasVisible = researchCanvasReadOnly");
    expect(routeSource).toContain("showNodeBindingPanel = !researchWorkflowTeamSelected || (researchCanvasVisible && !researchCanvasReadOnly)");
    expect(routeSource).toContain("renderResearchCanvasReadOnlyPanel");
    expect(routeSource).toContain("researchCanvasReadOnly ? renderResearchCanvasReadOnlyPanel() : null");
    expect(routeSource).toContain("只读组织画布");
    expect(routeSource).toContain("不会同步群聊或修改节点");
    expect(routeSource).toContain("canvasNodeStatusLabel");
    expect(routeSource).toContain("已绑定");
    expect(routeSource).toContain("专属管理员");
    expect(routeSource).toContain("暂无信息线");
    expect(routeSource).toContain("没有可展开的信息线");
    expect(routeSource).toContain('useState<ResearchCanvasLayoutMode>("auto")');
    expect(routeSource).toContain("autoLayoutResearchCanvasNodes(canvasNodes, organizationEdges)");
    expect(routeSource).toContain("const researchCanvasAutoLayoutActive = researchCanvasReadOnly && researchCanvasLayoutMode === \"auto\"");
    expect(routeSource).toContain("const displayCanvasNodes = researchCanvasAutoLayoutActive ? autoLayoutCanvasNodes : canvasNodes");
    expect(routeSource).toContain("自动排版只改变当前显示，不保存坐标");
    expect(routeSource).toContain("原始坐标");
    expect(routeSource).toContain("canvasLayoutModeSwitch");
    expect(routeSource).toContain("RESEARCH_CANVAS_AUTO_LAYOUT_LAYER_GAP");
    expect(routeSource).toContain("RESEARCH_CANVAS_AUTO_LAYOUT_ROW_GAP");
    expect(routeSource).toContain("researchCanvasRoleLayer");
    expect(routeSource).toContain("返回三阶段");
    expect(routeSource).toContain("researchCanvasReadOnly ? undefined : (event) => startNodeDrag(event, node)");
    expect(routeSource).toContain("researchCanvasReadOnly ? undefined : moveNodeDrag");
    expect(routeSource).toContain("researchCanvasReadOnly ? undefined : finishNodeDrag");
    expect(routeSource).toContain("researchCanvasReadOnly ? styles.nodeReadOnly : \"\"");
    expect(routeSource).toContain("styles.canvasReadOnlyPanel");
    expect(routeSource).toContain("styles.canvasReadOnlyBadge");
    expect(routeSource).toContain("styles.canvasLayoutModeSwitch");
    expect(routeSource).toContain("showNodeBindingPanel");
    expect(routeSource).toContain("showWorkflowPanel");
    expect(routeSource).toContain("showResearchSourceCollection");
    expect(routeSource).toContain('const teamDetailLoadMode = sourceCollectionStandalone ? "light" : "full"');
    expect(routeSource).toContain("queryKeys.team(effectiveTeamId, teamDetailLoadMode)");
    expect(routeSource).toContain("detail=${teamDetailLoadMode}");
    expect(routeSource).toContain("sourceCollectionAgentIdsFromTeam(selectedTeam, canvas)");
    expect(routeSource).toContain("sourceCollectionOwnerAgentIdFromTeam(selectedTeam, canvas)");
    expect(routeSource).toContain("researchSourceCollectionRoute");
    expect(routeSource).toContain("teamWorkspaceRoute");
    expect(routeSource).toContain("researchCanvasRoute");
    expect(routeSource).toContain("teamChatRoomRoute");
    expect(routeSource).toContain("返回团队页面");
    expect(routeSource).toContain("返回知识搜集");
    expect(routeSource).toContain("返回阶段页");
    expect(routeSource).toContain("renderSourceCollectionConversation");
    expect(routeSource).toContain("renderSourceCollectionControlsPanel");
    expect(routeSource).toContain("知识搜集工作台");
    expect(routeSource).toContain("researchStageAgentDirectChatRoute");
    expect(routeSource).toContain("openSourceCollectionStageAgentChat");
    expect(routeSource).not.toContain("sourceCollectionStageChatRoute");
    expect(routeSource).not.toContain("SOURCE_COLLECTION_STAGE_CHAT_PURPOSE");
    expect(routeSource).not.toContain("sourceCollectionTraceMessages");
    expect(routeSource).not.toContain("KV 缓存门禁已写入本轮搜集");
    expect(routeSource).not.toContain("执行模型：见当前步骤 Agent 配置");
    expect(routeSource).toContain("sourceCollectionPromptCacheModelDisplay");
    expect(routeSource).not.toContain("本轮使用 ${sourceCollectionPromptCachePolicy?.modelName");
    expect(routeSource).toContain("promptCachePolicy: SOURCE_COLLECTION_PROMPT_CACHE_POLICY");
    expect(routeSource).toContain('SOURCE_COLLECTION_PROMPT_CACHE_MODEL_LABEL = "configured prompt-cache model"');
    expect(routeSource).not.toContain('modelId: "houmo_qwen35_9b_agent"');
    expect(routeSource).toContain("|| selectedTeamStartResearchStageError");
    expect(routeSource).toContain("continuedSourceRunRef");
    expect(routeSource).toContain("sourceCollectionSearchExecution");
    expect(routeSource).toContain("selectedTeamInitialSourceCollectionSearchResult");
    expect(routeSource).toContain("selectedSourceCollectionSearchExecutionResult");
    const sourceCollectionBackgroundRefreshSource = routeSource.slice(
      routeSource.indexOf("const selectedSourceCollectionActiveWorkRun"),
      routeSource.indexOf("const sourceCollectionAcceptedBackgroundActive"),
    );
    expect(sourceCollectionBackgroundRefreshSource).not.toContain("researchStageRoundStatusQueryKey(selectedTeam.teamId)");
    expect(routeSource).toContain("sourceCollectionStageWritebackRefetchInterval");
    expect(routeSource).toContain("SOURCE_COLLECTION_STAGE_WRITEBACK_SYNC_GRACE_MS");
    expect(routeSource).toContain("sourceCollectionStageSyncUntilMs");
    expect(routeSource).toContain("sourceCollectionStageWritebackSyncActive");
    expect(routeSource).toContain("sourceCollectionPendingStageTaskIds");
    expect(routeSource).toContain("sourceCollectionPendingStageTaskIdList");
    expect(routeSource).toContain("sourceCollectionStageWritebackAwaitingTask");
    expect(routeSource).toContain("setSourceCollectionPendingStageTaskIds");
    expect(routeSource).toContain("payload.taskId");
    expect(stageProjectionSource).toContain("正在同步 Agent 结果");
    expect(stageProjectionSource).toContain("Syncing Agent result");
    expect(researchWorkflowResourcesSource).toContain("refetchInterval: (query) =>");
    expect(researchWorkflowResourcesSource).toContain("query.state.data as ResearchStageRoundStatusPayload | null | undefined");
    expect(routeSource).toContain("sourceCollectionStageWritebackSyncActive,");
    expect(routeSource).toContain("sourceCollectionStageWritebackRefetchInterval(");
    expect(researchWorkflowResourcesSource).toContain("refetchInterval: () => sourceCollectionStageWritebackRefetchInterval(");
    const sourceQualityStatusQuerySource = researchWorkflowResourcesSource.slice(
      researchWorkflowResourcesSource.indexOf("const sourceQuality = useQuery"),
      researchWorkflowResourcesSource.indexOf("const paperNoteChunks = useQuery"),
    );
    expect(sourceQualityStatusQuerySource).toContain("refetchInterval");
    expect(sourceQualityStatusQuerySource).toContain("stageWritebackSync.active");
    expect(routeSource).toContain("SourceCollectionSummaryPayload");
    expect(routeSource).toContain("sourceCollectionSummaryQueryKey");
    expect(routeSource).toContain("/workflow-orchestration/source-collection/summary");
    expect(routeSource).toContain("sourceCollectionSummaryQueryPrefix");
    expect(researchWorkflowResourcesSource).toContain("includeValidation=false&includeStore=false");
    expect(researchWorkflowResourcesSource).toContain("const TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT = 80;");
    expect(researchWorkflowResourcesSource).not.toContain("const TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT = 500;");
    expect(routeSource).toContain("sourceCollectionWorkspaceSelected");
    expect(routeSource).toContain("teamWorkflowCandidateListEnabled");
    expect(routeSource).toContain("teamWorkflowGraphEnabled");
    expect(routeSource).toContain("teamWorkflowKnowledgeIngestionEnabled");
    expect(routeSource).toContain("teamWorkflowSourceQualityEnabled");
    expect(routeSource).toContain("researchStageRoundStatusEnabled");
    expect(routeSource).toContain("sourceCollectionSummaryStageRound");
    expect(routeSource).toContain("sourceCollectionSummaryCounts");
    expect(routeSource).toContain("summarySourceCollectionActiveWorkRun");
    expect(routeSource).toContain("workflow: Boolean(effectiveTeamId && researchWorkflowTeamSelected)");
    expect(routeSource).toContain("const sourceCollectionFindingDetailsVisible = Boolean(");
    const sourceCollectionFindingDetailsVisibleSource = routeSource.slice(
      routeSource.indexOf("const sourceCollectionFindingDetailsVisible = Boolean("),
      routeSource.indexOf("const runtimeSummaryQuery = useQuery({"),
    );
    expect(sourceCollectionFindingDetailsVisibleSource).toContain("sourceCollectionWorkspaceSelected");
    expect(sourceCollectionFindingDetailsVisibleSource).toContain("selectedSourceCollectionRunEffectiveId");
    expect(sourceCollectionFindingDetailsVisibleSource).toContain('selectedSourceCollectionStageId === "finding"');
    expect(sourceCollectionFindingDetailsVisibleSource).toContain("sourceCollectionRecordsQueryEnabled");
    expect(sourceCollectionFindingDetailsVisibleSource).toContain("sourceCollectionAssignmentsQueryEnabled");
    expect(sourceCollectionFindingDetailsVisibleSource).toContain("sourceCollectionRunStatusQueryEnabled");
    expect(sourceCollectionFindingDetailsVisibleSource).not.toContain("sourceCollectionSummaryQuery.isSuccess");
    expect(sourceCollectionFindingDetailsVisibleSource).not.toContain("sourceCollectionSummaryQuery.isError");
    const sourceCollectionRunStatusQuerySource = routeSource.slice(
      routeSource.indexOf("const sourceCollectionRunStatusQuery = useQuery({"),
      routeSource.indexOf("const sourceCollectionRecordsQuery = useQuery({"),
    );
    const sourceCollectionRecordsQuerySource = routeSource.slice(
      routeSource.indexOf("const sourceCollectionRecordsQuery = useQuery({"),
      routeSource.indexOf("const sourceCollectionAssignmentsQuery = useQuery({"),
    );
    const sourceCollectionAssignmentsQuerySource = routeSource.slice(
      routeSource.indexOf("const sourceCollectionAssignmentsQuery = useQuery({"),
      routeSource.indexOf("const autoCanvasViewportStyle"),
    );
    expect(sourceCollectionRunStatusQuerySource).toContain("enabled: sourceCollectionRunStatusQueryEnabled");
    expect(sourceCollectionRecordsQuerySource).toContain("enabled: sourceCollectionRecordsQueryEnabled");
    expect(sourceCollectionAssignmentsQuerySource).toContain("enabled: sourceCollectionAssignmentsQueryEnabled");
    const sourceCollectionRecordsDataLoadingSource = routeSource.slice(
      routeSource.indexOf("const sourceCollectionRecordsDataLoading = Boolean("),
      routeSource.indexOf("const sourceCollectionAssignmentsDataLoading = Boolean("),
    );
    expect(sourceCollectionRecordsDataLoadingSource).toContain("sourceCollectionRecordsQuery.isPending");
    expect(sourceCollectionRecordsDataLoadingSource).toContain("sourceCollectionRunStatusQuery.isPending");
    expect(sourceCollectionRecordsDataLoadingSource).not.toContain("sourceCollectionSummaryQuery.isPending");
    const sourceCollectionPrimaryLoadingSource = routeSource.slice(
      routeSource.indexOf("const sourceCollectionPrimaryDataLoading = Boolean("),
      routeSource.indexOf("const sourceCollectionSourceQualityLoading = Boolean("),
    );
    expect(sourceCollectionPrimaryLoadingSource).toContain("sourceCollectionSummaryQuery.isPending");
    expect(sourceCollectionPrimaryLoadingSource).not.toContain("researchStageRoundStatusQuery.isPending");
    expect(sourceCollectionPrimaryLoadingSource).not.toContain("teamWorkflowCandidatesQuery.isPending");
    expect(routeSource).toContain("sourceCollectionRecordsDataLoading");
    expect(routeSource).toContain("sourceCollectionAssignmentsDataLoading");
    expect(routeSource).toContain("sourceCollectionCollectedCountText");
    expect(routeSource).toContain("sourceCollectionSearchOpenAssignmentCountText");
    expect(routeSource).toContain("sourceCollectionQueryCountText");
    expect(stageProjectionSource).toContain("已有部分资料");
    expect(stageProjectionSource).toContain("Partial output ready");
    expect(stageProjectionSource).toContain("historicalTask");
    expect(stageProjectionSource).toContain("历史任务 ${historicalTaskCount} 已忽略");
    const sourceCollectionCommandStatsSource = routeSource.slice(
      routeSource.indexOf("<TeamSourceCollectionStandaloneStagePanel"),
      routeSource.indexOf("stagePipelineId=\"source-collection-stage-status\"")
    );
    expect(routeSource).toContain("TeamSourceCollectionStandaloneStagePanel");
    expect(routeSource).toContain("sourceCollectionStandaloneStageModules");
    expect(teamSourceCollectionStandaloneStagePanelSource).toContain("<TeamStageCommandBar");
    expect(teamSourceCollectionStandaloneStagePanelSource).toContain("<TeamStagePipeline");
    expect(teamSourceCollectionStandaloneStagePanelSource).toContain("<TeamStageCard");
    expect(teamSourceCollectionStandaloneStagePanelSource).toContain("TeamSourceCollectionStageActionIcon");
    expect(sourceCollectionCommandStatsSource).toContain("sourceCollectionConsoleStatusText");
    expect(sourceCollectionCommandStatsSource).toContain("sourceCollectionBoardNextStepLabel");
    expect(sourceCollectionCommandStatsSource).toContain("sourceCollectionCollectedCountLabel");
    expect(sourceCollectionCommandStatsSource).not.toContain("sourceCollectionSearchOpenAssignmentCountLabel");
    expect(sourceCollectionCommandStatsSource).not.toContain("sourceCollectionDownstreamOpenAssignmentCountLabel");
    expect(sourceCollectionCommandStatsSource).not.toContain("sourceCollectionQueryCountLabel");
    expect(sourceCollectionCommandStatsSource).not.toContain("sourceCollectionPromptCacheStatusLabel");
    expect(routeSource).not.toContain("researchStageRoundStatusQueryKey(effectiveTeamId || \"none\"),\n    queryFn: () =>\n      fetchJson<ResearchStageRoundStatusPayload>(\n        `/api/teams/${encodeURIComponent(effectiveTeamId)}/workflow-orchestration/stage-rounds/status`,\n      ),\n    enabled: Boolean(effectiveTeamId && researchWorkflowTeamSelected && teamWorkflowQuery.data)");
    expect(routeSource).not.toContain("queryKeys.teamWorkflowCandidates(effectiveTeamId || \"none\", TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT),\n    queryFn: () =>\n      fetchJson<TeamWorkflowCandidateListPayload>(\n        `/api/teams/${encodeURIComponent(effectiveTeamId)}/workflow-orchestration/candidates?limit=${TEAM_WORKFLOW_CANDIDATE_PREVIEW_LIMIT}`,\n      ),\n    enabled: Boolean(effectiveTeamId && researchWorkflowTeamSelected && teamWorkflowQuery.data)");
    expect(routeSource).not.toContain("enabled: Boolean(effectiveTeamId && researchWorkflowTeamSelected && teamWorkflowQuery.data)");
    expect(routeSource.match(/&& teamWorkflowQuery\.data\)/g) ?? []).toEqual([]);

    const queryLayerSource = routeSource.slice(
      routeSource.indexOf("const teamsQuery = useQuery"),
      routeSource.indexOf("const autoCanvasViewportStyle = useMemo"),
    );
    expect(queryLayerSource).toContain("queryFn: ({ signal }) => fetchJson<TeamListPayload>(\"/api/teams\", { signal })");
    expect(queryLayerSource).toContain("queryFn: ({ signal }) => fetchJson<Team>(`/api/teams/${encodeURIComponent(effectiveTeamId)}?detail=${teamDetailLoadMode}`, { signal })");
    expect(queryLayerSource).toContain("queryFn: ({ signal }) => fetchJson<TeamOrganizationCanvas>(`/api/teams/${encodeURIComponent(effectiveTeamId)}/canvas`, { signal })");
    expect(queryLayerSource).toContain("queryFn: ({ signal }) =>");
    expect(queryLayerSource.match(/queryFn: \(\{ signal \}\) =>/g)?.length ?? 0).toBe(17);
    expect(queryLayerSource.match(/queryFn: \(\) =>/g) ?? []).toEqual([]);
    const sourceCollectionStageReturnRefreshSource = routeSource.slice(
      routeSource.indexOf("if (!researchWorkflowTeamSelected || !pageVisible"),
      routeSource.indexOf("if (!selectedTeam?.teamId || !selectedSourceCollectionRunEffectiveId || !selectedSourceCollectionSearchAccepted"),
    );
    expect(sourceCollectionStageReturnRefreshSource).toContain("requestedSourceCollectionStage");
    expect(sourceCollectionStageReturnRefreshSource).not.toContain("researchStageRoundStatusQueryKey(selectedTeam.teamId)");
    expect(sourceCollectionStageReturnRefreshSource).not.toContain("queryKeys.teamWorkflowCandidates(selectedTeam.teamId");
    expect(sourceCollectionStageReturnRefreshSource).not.toContain("sourceQualityStatusQueryKey(selectedTeam.teamId)");
    expect(sourceCollectionStageReturnRefreshSource).toContain("sourceCollectionRunRecordsQueryKey(selectedSourceCollectionRunEffectiveId)");
    const sourceCollectionSearchAcceptedRefreshSource = routeSource.slice(
      routeSource.indexOf("if (!selectedTeam?.teamId || !selectedSourceCollectionRunEffectiveId || !selectedSourceCollectionSearchAccepted"),
      routeSource.indexOf("const openSourceCollectionStorageTarget = (target: SourceCollectionStorageOpenTarget"),
    );
    expect(sourceCollectionSearchAcceptedRefreshSource).toContain("selectedSourceCollectionSearchAccepted");
    expect(sourceCollectionSearchAcceptedRefreshSource).toContain("sourceCollectionSummaryQueryKey(selectedTeam.teamId");
    expect(sourceCollectionSearchAcceptedRefreshSource).not.toContain("queryKeys.teamWorkflowCandidates(selectedTeam.teamId");
    expect(sourceCollectionSearchAcceptedRefreshSource).not.toContain("researchStageRoundStatusQueryKey(selectedTeam.teamId)");
    expect(sourceCollectionSearchAcceptedRefreshSource).not.toContain("queryKeys.teamWorkflowKnowledgeIngestionStatus(selectedTeam.teamId)");
    expect(sourceCollectionSearchAcceptedRefreshSource).not.toContain("sourceCollectionRunStatus?.runStatus");
    expect(sourceCollectionSearchAcceptedRefreshSource).not.toContain("sourceCollectionRunStatus?.summary.recordCount");
    expect(routeSource).toContain("skippedDuplicateCount");
    expect(routeSource).toContain("条重复跳过");
    expect(routeSource).toContain("selectedSourceCollectionSearchAccepted");
    expect(routeSource).toContain('finding: ["source_finder"]');
    expect(routeSource).toContain('extraction: ["source_extractor"]');
    expect(routeSource).toContain('relations: ["source_relation_mapper"]');
    expect(routeSource).toContain('ingestion: ["source_ingestor"]');
    expect(routeSource).toContain('source_finder: "资料寻找 Agent"');
    expect(routeSource).toContain('source_extractor: "资料提炼 Agent"');
    expect(routeSource).toContain('source_relation_mapper: "资料关系整理 Agent"');
    expect(routeSource).toContain('source_ingestor: "资料入库 Agent"');
    expect(routeSource).toContain('return "relations";');
    expect(routeSource).toContain('SOURCE_COLLECTION_TEAM_AGENT_ROLES');
    expect(routeSource).toContain('key: "source_relation_mapper"');
    expect(routeSource).toContain("const sourceCollectionRelationMapperAgentId");
    expect(routeSource).toContain("createdByAgent: sourceCollectionRelationMapperAgentId");
    expect(routeSource).not.toContain("createdByAgent: sourceCollectionQualityAgentId");
    expect(routeSource).not.toContain("sourceCollectionStageRoomKey");
    expect(routeSource).toContain("openSourceCollectionStageAgentChat");
    expect(routeSource).toContain("repairChallengeCupTeamAgentsMutation.mutate(selectedTeam.teamId)");
    expect(routeSource).toContain("进入 Agent 私聊");
    expect(routeSource).toContain("researchStageStartFeedbackText");
    expect(routeSource).toContain("已复用正在运行的");
    expect(routeSource).not.toContain("像对话一样记录：搜索了什么");
    expect(routeSource).not.toContain("搜集批次已启动，等待功能 Agent 回写");
    expect(routeSource).not.toContain("后续接入全文下载或提炼器时");
    expect(routeSource).not.toContain("通常无需修改");
    expect(routeSource).not.toContain("一键生成搜索计划、团队分工");
    expect(routeSource).not.toContain("搜索计划、步骤记录、资料记录和候选镜像都已落盘");
    expect(routeSource).toContain("返回团队页面");
    expect(routeSource).toContain("实验规划工作台");
    expect(routeSource).toContain("experimentPlanningStatusQueryKey");
    expect(routeSource).toContain("renderExperimentPlanningLedgerPanel");
    expect(routeSource).toContain("实验计划账本");
    expect(routeSource).toContain("TeamExperimentMethodPanel");
    expect(routeSource).toContain("experimentMethodCatalogQueryKey");
    expect(routeSource).toContain("/workflow-orchestration/experiments/methods");
    expect(routeSource).toContain("activeContract={activeExperimentContract}");
    expect(routeSource).toContain("onSubmit={createExperimentPlanFromWorkspace}");
    expect(teamExperimentMethodPanelSource).toContain("catalog.researchModes.map");
    expect(teamExperimentMethodPanelSource).toContain("实验方式");
    expect(teamExperimentMethodPanelSource).toContain("实验目的");
    expect(teamExperimentMethodPanelSource).toContain("验证方法");
    expect(teamExperimentMethodPanelSource).toContain("buildExperimentPlanMethodRequest");
    expect(teamExperimentMethodPanelSource).toContain("保存为新版本");
    expect(teamExperimentMethodPanelSource).toContain("执行器尚未就绪");
    expect(teamExperimentMethodPanelStyles.methodGrid).toContain("max-[560px]:grid-cols-[minmax(0,1fr)]");
    expect(teamExperimentMethodPanelStyles.form).toContain("min-h-[18rem]");
    expect(routeSource).toContain("baseline-artifact");
    expect(routeSource).toContain("登记基线工件");
    expect(routeSource).toContain("reproductionCommand");
    expect(routeSource).toContain("smoke-result");
    expect(routeSource).toContain("ExperimentSmokeResultRecord");
    expect(routeSource).toContain("activeSmokeResult");
    expect(routeSource).toContain("gateDecision");
    expect(routeSource).toContain("登记 smoke 结果");
    expect(routeSource).toContain("needs_review");
    expect(routeSource).toContain("full-run 已解锁");
    expect(routeSource).toContain("readyForSmoke");
    expect(routeSource).toContain("baselineSelection");
    expect(routeSource).toContain("readyForFullRun");
    expect(routeSource).toContain("No training execution was triggered.");
    expect(routeSource).toContain("迭代优化工作台");
    expect(routeSource).toContain("renderResearchStageStandalonePage");
    expect(routeSource).toContain("不自动进入下一阶段。");
    expect(teamWorkflowStatusPanelsSource).toContain("资料提炼 Agent");
    expect(teamWorkflowStatusPanelsSource).toContain("入库审核状态");
    expect(teamWorkflowStatusPanelsSource).toContain("模型调用证据链");
    expect(teamWorkflowStatusPanelsSource).toContain("证据登记，不是正式知识");
    expect(teamWorkflowStatusPanelsSource).toContain("CandidateStore、Team Knowledge 和正式同步边界");
    expect(routeSource).toContain("TeamSourceCollectionOverviewPanel");
    expect(teamSourceCollectionOverviewPanelSource).toContain("workflowSourceCollectionPanel");
    expect(routeSource).toContain("资料搜索执行");
    expect(routeSource).toContain("sourceCollectionOverviewSummary");
    expect(routeSource).toContain("sourceCollectionOverviewStats");
    expect(routeSource).toContain("sourceCollectionOverviewPlan");
    expect(routeSource).toContain("TeamSourceCollectionRunSettingsPanel");
    expect(routeSource).toContain("onDraftChange={(patch) => setSourceCollectionDraft");
    expect(teamSourceCollectionRunSettingsPanelSource).toContain("启动搜集批次");
    expect(teamSourceCollectionRunSettingsPanelSource).toContain("workflowSourceCollectionForm");
    expect(teamSourceCollectionRunSettingsPanelSource).toContain("wrapInDetails");
    expect(routeSource).toContain("TeamSourceCollectionFindingDetailsPanel");
    expect(routeSource).toContain("sourceCollectionFindingRunOptions");
    expect(routeSource).toContain("sourceCollectionFindingAssignments");
    expect(routeSource).toContain("storageActions={renderSourceCollectionStorageActions()}");
    expect(teamSourceCollectionFindingDetailsPanelSource).toContain("最近批次");
    expect(teamSourceCollectionFindingDetailsPanelSource).toContain("查询与分工详情");
    expect(teamSourceCollectionFindingDetailsPanelSource).toContain("assignmentEmptyMessage");
    expect(routeSource).toContain("手工回写一条搜集结果");
    expect(teamSourceCollectionManualWritebackPanelSource).toContain("回写并导入候选");
    expect(teamSourceCollectionManualWritebackPanelSource).toContain("原始位置");
    expect(routeSource).toContain("不触发外部搜索，不写正式知识/RAG/图谱");
    expect(teamWorkflowStatusPanelsSource).toContain("正式知识写入关闭");
    expect(teamWorkflowStatusPanelsSource).toContain("入库关系图");
    expect(routeSource).toContain("Agent 生成关系图");
    expect(teamWorkflowStatusPanelsSource).toContain("CandidateStore 快照 · 正式知识/RAG/图谱写入关闭");
    expect(teamWorkflowStatusPanelsSource).toContain("paper_note 分块计划");
    expect(teamWorkflowStatusPanelsSource).toContain("资料提炼复核");
    expect(routeSource).toContain("通过复核");
    expect(routeSource).toContain("退回补资料");
    expect(teamWorkflowStatusPanelsSource).toContain("Source extraction Agent");
    expect(routeSource).toContain("TeamWorkflowCandidatePreviewPanel");
    expect(routeSource).toContain("teamWorkflowCandidatePreviewItems");
    expect(teamWorkflowCandidatePreviewPanelSource).toContain("候选仓库预览");
    expect(teamWorkflowCandidatePreviewPanelSource).toContain("查看完整候选库");
    expect(teamWorkflowCandidatePreviewPanelSource).toContain("向下滚动查看更多候选，或打开完整候选库分页处理");
    expect(teamWorkflowCandidatePreviewPanelStylesSource).toContain("workflowCandidateListPanel");
    expect(teamWorkflowCandidatePreviewPanelStylesSource).toContain("workflowCandidateListScroll");
    expect(routeSource).toContain("生成分块计划");
    expect(routeSource).toContain("重建分块计划");
    expect(teamWorkflowStatusPanelsSource).toContain("后续 paper_note draft 需带 chunkId");
    expect(routeSource).toContain("选择 research-team / 挑战杯ai科研团队 后显示挑战杯科研流程。");
    expect(routeSource).toContain("团队广播");
    expect(routeSource).toContain("发送给团队");
    expect(routeSource).toContain("最近团队广播");
    expect(routeSource).toContain("已衔接群聊");
    expect(routeSource).toContain("teamChatRoomRoute(selectedTeamStartRoundResult.roomId");
    expect(routeSource).toContain("teamChatRoomRoute(latestTeamRound.roomId");
    expect(routeSource).toContain("teamWorkspaceRoute(selectedTeam?.teamId || RESEARCH_TEAM_ID)");
    expect(routeSource).toContain("styles.linkedRoomLine");
    expect(routeSource).toContain("styles.toolbarLink");
    expect(routeSource).toContain("teamBusEvents");
    expect(routeSource).toContain("isProjectAgentBusEventRevoked");
    expect(routeSource).toContain("projectAgentBusEventsForTeam");
    expect(routeSource).toContain("revokeTeamMessageMutation");
    expect(routeSource).toContain("selectedTeamMessageResult.kernel?.taskId");
    expect(routeSource).toContain("event.kernel?.taskId");
    expect(routeSource).toContain("styles.teamHistoryPanel");
    expect(routeStyles.kernelTraceLink).toBeTypeOf("string");
    expect(routeSource).toContain("interrupt_targets");
    expect(routeSource).toContain("edges: durableCanvas.edges.filter((edge) => edge.source !== deletedNodeId && edge.target !== deletedNodeId)");
    expect(routeSource).toContain("disabled={!hasWritableCanvas");
    expect(routeStyles.teamContextBar).toBeTypeOf("string");
    expect(routeStyles.teamTitleBlock).toBeTypeOf("string");
    expect(routeStyles.teamSelectField).toBeTypeOf("string");
    expect(routeStyles.teamSelectPrefix).toBeTypeOf("string");
    expect(routeStyles.teamSelectControl).toBeTypeOf("string");
    expect(routeStyles.teamRefreshButton).toBeTypeOf("string");
    expect(routeStyles.teamContextChips).toBeTypeOf("string");
    expect(routeStyles.teamContextActions).toBeTypeOf("string");
    expect(routeStyles.teamContextActions).not.toContain("accent-warm");
    expect(routeStyles.teamContextBar).not.toContain("accent-warm");
    expect(routeStyles.teamSelectField).toContain("[&_[data-vui=select-trigger]]:!inline-flex");
    expect(routeStyles.teamSelectField).toContain("[&_[data-vui=select-trigger]]:justify-between");
    expect(routeStyles.teamRefreshButton).toContain("!h-8");
    expect(routeStyles.teamRefreshButton).toContain("!w-8");
    expect(routeStylesSource).not.toContain(".summaryBar");
    expect(routeStylesSource).not.toContain(".teamPickerPanel");
    expect(routeStylesSource).not.toContain(".teamPickerSummary");
    expect(routeStyles.nodeBindingSection).toBeTypeOf("string");
    expect(routeStyles.nodeBindingPlaceholder).toBeTypeOf("string");
    expect(routeStyles.nodeSourceAuthority).toBeTypeOf("string");
    expect(routeStyles.workflowPanel).toBeTypeOf("string");
    expect(routeStyles.workflowStats).toBeTypeOf("string");
    expect(teamWorkflowStatusPanelStyles.workflowIngestionPanel).toBeTypeOf("string");
    expect(teamWorkflowStatusPanelStyles.workflowIngestionStages).toBeTypeOf("string");
    expect(routeStyles.workflowIngestionBoundary).toBeTypeOf("string");
    expect(teamWorkflowStatusPanelStyles.workflowSourceQualityPanel).toBeTypeOf("string");
    expect(routeStyles.workflowSourceQualityStats).toBeTypeOf("string");
    expect(teamWorkflowStatusPanelStyles.workflowSourceQualityQueue).toBeTypeOf("string");
    expect(teamWorkflowStatusPanelStyles.workflowPaperNoteChunkPanel).toBeTypeOf("string");
    expect(teamWorkflowStatusPanelStyles.workflowPaperNoteChunkStats).toBeTypeOf("string");
    expect(teamSourceCollectionStorageActionsPanelStyles.workflowSourceCollectionStorageActions).toBeTypeOf("string");
    expect(teamSourceCollectionStorageActionsPanelStyles.workflowSourceCollectionStorageButtons).toBeTypeOf("string");
    expect(teamWorkflowStatusPanelStyles.workflowPaperNoteChunkPlans).toBeTypeOf("string");
    expect(teamWorkflowStatusPanelStyles.workflowModelEvidencePanel).toBeTypeOf("string");
    expect(teamWorkflowStatusPanelStyles.workflowModelEvidenceStats).toBeTypeOf("string");
    expect(teamWorkflowStatusPanelStyles.workflowModelEvidenceCoverage).toBeTypeOf("string");
    expect(teamSourceCollectionOverviewPanelStyles.workflowSourceCollectionPanel).toBeTypeOf("string");
    expect(teamSourceCollectionRunSettingsPanelStyles.workflowSourceCollectionForm).toBeTypeOf("string");
    expect(teamSourceCollectionFindingDetailsPanelStyles.workflowSourceCollectionRuns).toBeTypeOf("string");
    expect(teamSourceCollectionFindingDetailsPanelStyles.workflowSourceCollectionAssignments).toBeTypeOf("string");
    expect(teamSourceCollectionManualWritebackPanelStyles.workflowSourceCollectionOutputForm).toBeTypeOf("string");
    expect(routeStyles.workflowSuccess).toBeTypeOf("string");
    expect(routeStyles.workflowError).toBeTypeOf("string");
    expect(routeStyles.sourceCollectionPage).toBeTypeOf("string");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageGrid).toBeTypeOf("string");
    expect(routeStyles.sourceCollectionRunBadge).toBeTypeOf("string");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionExtractionPanels).toBeTypeOf("string");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionConversationPanel).toBeTypeOf("string");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionResultsPanel).toBeTypeOf("string");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionResultsHeader).toBeTypeOf("string");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionResultWarning).toBeTypeOf("string");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionConversationPanelCompact).toBeTypeOf("string");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionResultsPanelCompact).toBeTypeOf("string");
    expect(teamSourceCollectionRunSwitcherPanelStyles.sourceCollectionRunSwitcher).toBeTypeOf("string");
    expect(teamSourceCollectionRunSwitcherPanelStyles.sourceCollectionRunSwitcherMain).toBeTypeOf("string");
    expect(teamSourceCollectionRunSwitcherPanelStyles.sourceCollectionRunSwitcherStats).toBeTypeOf("string");
    expect(teamSourceCollectionCandidatePanelStyles.sourceCollectionCandidateListShell).toBeTypeOf("string");
    expect(teamSourceCollectionResultControlsSource).toContain("TeamSourceFilterBar");
    expect(teamSourceCollectionResultControlsSource).toContain("TeamSourcePagination");
    expect(teamSourceFilterBarSource).toContain("const BAR");
    expect(teamSourceFilterBarSource).toContain("const CHIP_ACTIVE");
    expect(teamSourceResultStatsSource).toContain('data-vui-product="team-source-result-stats"');
    expect(teamSourceResultListSource).toContain('data-vui-product="team-source-result-list"');
    expect(teamSourceResultListSource).toContain('data-vui-product="team-source-result-item"');
    expect(teamSourceResultListSource).toContain("ROW_SELECTED");
    expect(routeStylesSource).not.toContain(".sourceCollectionTraceMessage");
    expect(routeStylesSource).not.toContain(".sourceCollectionTrace_cache");
    expect(routeStylesSource).not.toContain(".sourceCollectionTraceStorage");
    expect(teamSourceEmptyStateSource).toContain('data-vui-product="team-source-empty-state"');
    expect(teamSourceEmptyStateSource).toContain('data-slot="source-empty-facts"');
    expect(teamSourceEmptyStateSource).toContain("actions");
    expect(teamSourceEmptyStateSource).toContain("border-dashed");
    expect(teamSourceEmptyStateSource).toContain("w-full");
    expect(teamSourceEmptyStateSource).not.toContain("self-start");
    expect(teamSourceEmptyStateSource).toContain("max-[560px]:grid-cols-[repeat(2,minmax(0,1fr))]");
    expect(teamSourceCollectionSourceDetailPanelStyles.sourceCollectionSourceDetailPanel).toBeTypeOf("string");
    expect(teamSourceCollectionSourceDetailPanelStyles.sourceCollectionSourceDetailActions).toBeTypeOf("string");
    expect(teamSourceCollectionSourceDetailPanelStyles.sourceCollectionSourceDetailFacts).toBeTypeOf("string");
    expect(teamSourceCollectionSourceDetailPanelStyles.sourceCollectionSourceDetailNotice).toBeTypeOf("string");
    expect(teamSourceCollectionSourceDetailPanelStyles.sourceCollectionSearchEvidence).toBeTypeOf("string");
    expect(teamSourceCollectionSourceDetailPanelStyles.sourceCollectionSearchEvidenceBody).toBeTypeOf("string");
    expect(routeStyles.workflowCandidateItemSelected).toBeTypeOf("string");
    expect(routeStylesSource).not.toContain(".sourceCollectionResultStatus");
    expect(routeStylesSource).not.toContain(".sourceCollectionResultSource");
    expect(routeStylesSource).not.toContain(".sourceCollectionResultSourceMissing");
    expect(routeStylesSource).not.toContain(".sourceCollectionFilterBar");
    expect(routeStylesSource).not.toContain(".sourceCollectionFilterActive");
    expect(teamSourceResultListSource).toContain(
      "grid-cols-[max-content_minmax(0,1fr)_minmax(70px,max-content)_minmax(8rem,16rem)]",
    );
    expect(teamSourceResultListSource).not.toContain("minmax(120px,220px)");
    expect(teamSourceCollectionRunSwitcherPanelStyles.sourceCollectionRunSwitcher).toContain("grid-cols-[minmax(0,1fr)_auto]");
    expect(teamSourceCollectionRunSwitcherPanelStyles.sourceCollectionRunSwitcherMain).toContain("grid-cols-[max-content_minmax(220px,360px)]");
    expect(teamSourceCollectionRunSwitcherPanelStyles.sourceCollectionRunSwitcherMain).not.toContain("[&_small]");
    expect(teamSourceCollectionRunSwitcherPanelStyles.sourceCollectionRunSwitcherStats).toContain("flex flex-wrap items-center justify-end");
    expect(teamSourceResultListSource).toContain("min-h-[36px]");
    expect(teamSourceResultListSource).toContain("whitespace-nowrap");
    expect(teamSourceResultListSource).not.toContain("grid-rows-[auto_auto_auto]");
    expect(routeStylesSource).not.toContain(".sourceCollectionCandidateListShell");
    expect(teamSourceCollectionCandidatePanelStyles.sourceCollectionCandidateListShell).toContain("overflow-auto");
    expect(teamSourceCollectionCandidatePanelStyles.sourceCollectionCandidateListShell).toContain("[scrollbar-gutter:stable]");
    expect(teamSourceCollectionCandidatePanelStyles.sourceCollectionCandidateListShell).toContain("items-start");
    expect(teamSourceCollectionCandidatePanelStyles.sourceCollectionCandidateListShell).toContain("content-start");
    expect(teamSourceCollectionCandidatePanelStyles.sourceCollectionCandidateListShell).toContain("self-start");
    expect(teamSourceCollectionExtractionRecoveryPanelStyles.sourceCollectionExtractionRecoveryPanel).toBeTypeOf("string");
    expect(teamSourceCollectionExtractionRecoveryPanelStyles.sourceCollectionExtractionRecoveryBody).toBeTypeOf("string");
    expect(teamSourceCollectionExtractionRecoveryPanelStyles.sourceCollectionExtractionRecoveryBody).toContain("[&_p]:m-0");
    expect(teamSourceCollectionExtractionRecoveryPanelStyles.sourceCollectionExtractionRecoveryPanel).toContain("grid-cols-[minmax(0,1fr)_auto]");
    expect(teamSourceCollectionExtractionRecoveryPanelStyles.sourceCollectionExtractionRecoveryPanelDanger).toContain("state-error");
    expect(teamSourceCollectionExtractionRecoveryPanelStyles.sourceCollectionExtractionRecoveryPanel).toContain("max-[760px]:grid-cols-[1fr]");
    expect(teamSourceCollectionExtractionRecoveryPanelStyles.sourceCollectionExtractionRecoveryStats).toBeTypeOf("string");
    expect(teamSourceCollectionExtractionRecoveryPanelStyles.sourceCollectionExtractionRecoveryStats).toContain("repeat(auto-fit,minmax(7rem,1fr))");
    expect(teamSourceCollectionExtractionRecoveryPanelStyles.sourceCollectionExtractionRecoveryActions).toBeTypeOf("string");
    expect(teamSourceCollectionExtractionRecoveryPanelStyles.sourceCollectionExtractionRecoveryActions).toContain("[&_[data-vui=native-button]]:w-fit");
    expect(teamSourceCollectionCandidatePanelStyles.sourceCollectionCandidateListShell).toContain("max-h-[44vh]");
    expect(teamSourceCollectionCandidatePanelStyles.sourceCollectionCandidateListShell).toContain("min-h-[220px]");
    expect(teamSourceCollectionScreeningPanelStyles.sourceCollectionScreeningListShell).toContain("max-h-[44vh]");
    expect(teamSourceCollectionScreeningPanelStyles.sourceCollectionScreeningListShell).toContain("[scrollbar-gutter:stable]");
    expect(routeStylesSource).not.toContain("grid-template-rows: auto minmax(0, 1fr) auto auto");
    expect(workflowGraphViewStyles.workflowGraphFrame).toContain("h-[var(--workflow-graph-height,360px)]");
    expect(workflowGraphViewStyles.workflowGraphFrame).not.toContain("h-full");
    expect(workflowGraphViewStyles.workflowGraphNode).toContain("w-[168px]");
    expect(workflowGraphViewStyles.workflowGraphNode).toContain("h-[58px]");
    expect(workflowGraphViewStyles.workflowGraphNode).toContain("overflow-hidden");
    expect(workflowGraphViewStyles.workflowGraphNode).toContain("[&_strong]:truncate");
    expect(workflowGraphViewStyles.workflowGraphNode).toContain("[&_span]:truncate");
    expect(teamSourceFilterBarSource).toContain("min-w-[76px]");
    expect(teamSourceFilterBarSource).toContain("flex-none");
    expect(routeStylesSource).not.toContain("min-height: 122px");
    expect(routeStylesSource).not.toContain("min-height: 96px");
    expect(routeStylesSource).not.toContain(".sourceCollectionTraceBody");
    expect(routeStylesSource).not.toContain("grid-cols-[58px_minmax(0,1fr)]");
    expect(routeStylesSource).not.toMatch(/\.sourceCollectionTraceBody p \{[\s\S]*?-webkit-line-clamp: 3/);
    expect(teamSourceCollectionPanelFrameStyles.sourceCollectionFocusedPanel).toContain(
      "grid-cols-[minmax(0,1fr)_clamp(320px,26vw,420px)]",
    );
    expect(teamSourceCollectionPanelFrameStyles.sourceCollectionFocusedPanel).toContain("isolate");
    expect(routeStyles.route).toContain("[--team-workbench-gap:4px]");
    expect(routeStyles.sourceCollectionPage).toContain("h-full");
    expect(routeStyles.sourceCollectionPage).toContain("flex-1");
    expect(routeStyles.sourceCollectionPage).toContain("overflow-hidden");
    expect(routeStyles.sourceCollectionPageHeader).toContain("w-full");
    expect(routeStyles.sourceCollectionPageHeader).toContain("max-w-none");
    expect(routeStyles.sourceCollectionPageHeader).not.toContain("mx-auto");
    expect(routeStyles.sourceCollectionPageHeader).not.toContain("max-w-[1480px]");
    expect(routeStyles.sourceCollectionPageHeader).toContain("grid-cols-[minmax(0,1fr)_auto]");
    expect(routeStyles.sourceCollectionPageHeader).toContain("gap-[var(--team-workbench-gap)]");
    expect(routeStyles.sourceCollectionPageHeader).toContain("px-[var(--team-workbench-gap)]");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspace).toContain("grid-rows-[auto_minmax(0,1fr)]");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspace).toContain("h-full");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspace).toContain("min-h-[360px]");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspace).toContain("overflow-hidden");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspaceCompact).toBeTypeOf("string");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspaceCompact).toContain("h-auto");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspaceCompact).toContain("min-h-0");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspaceCompact).toContain("shrink-0");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspaceCompact).toContain("grid-rows-[auto_auto]");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspaceCompact).toContain("overflow-visible");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspaceCompact).not.toContain("h-full");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspaceCompact).not.toContain("min-h-[360px]");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspace).toContain("gap-[var(--team-workbench-gap)]");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspace).toContain("p-[var(--team-workbench-gap)]");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspace).toContain("max-[760px]:!h-auto");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspace).toContain("max-[760px]:grid-rows-[auto_auto]");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspace).toContain("max-[760px]:overflow-visible");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspaceHeader).toContain("grid-cols-[minmax(0,1fr)_minmax(260px,0.7fr)_max-content]");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageChatActions).toContain("max-[720px]:!flex");
    expect(routeStyles.sourceCollectionPageBody).toContain("!grid");
    expect(routeStyles.sourceCollectionPageBody).toContain("h-full");
    expect(routeStyles.sourceCollectionPageBody).toContain("grid-rows-[auto_auto_auto_minmax(0,1fr)]");
    expect(routeStyles.sourceCollectionPageBody).toContain("max-[760px]:grid-rows-[auto_auto_auto_auto]");
    expect(routeStyles.sourceCollectionPageBody).toContain("max-[760px]:content-start");
    expect(routeStyles.sourceCollectionPageBody).toContain("w-full");
    expect(routeStyles.sourceCollectionPageBody).toContain("max-w-none");
    expect(routeStyles.sourceCollectionPageBody).not.toContain("mx-auto");
    expect(routeStyles.sourceCollectionPageBody).not.toContain("max-w-[1480px]");
    expect(routeStyles.sourceCollectionPageBody).toContain("gap-[var(--team-workbench-gap)]");
    expect(routeStyles.sourceCollectionPageBody).toContain("p-[var(--team-workbench-gap)]");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageBodyCompact).toBeTypeOf("string");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageBodyCompact).toContain("!flex");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageBodyCompact).toContain("flex-col");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageBodyCompact).toContain("overflow-auto");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageBodyCompact).toContain("[&>*]:shrink-0");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageBodyCompact).not.toContain("grid-rows-[auto_auto_auto_minmax(0,1fr)]");
    expect(teamSourceCollectionStandaloneStagePanelSource).toContain("compactActivePanel ? styles.sourceCollectionPageBodyCompact : styles.sourceCollectionPageBody");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionConversationPanel).toContain("h-full");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionConversationPanel).toContain("grid-rows-[auto_minmax(0,1fr)]");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionConversationPanel).toContain("overflow-hidden");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionConversationPanel).toContain("max-[760px]:!h-auto");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionConversationPanel).toContain("max-[760px]:grid-rows-[auto_auto]");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionConversationPanel).toContain("max-[760px]:overflow-visible");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageGrid).toContain("min-h-0");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageGrid).toContain("h-full");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageGrid).toContain("gap-[var(--team-workbench-gap)]");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageGrid).toContain("max-[760px]:!flex");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageGrid).toContain("max-[760px]:!h-auto");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageGrid).toContain("max-[760px]:flex-col");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageGrid).toContain("max-[760px]:content-start");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageGrid).toContain("max-[760px]:overflow-visible");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageGridCompact).toBeTypeOf("string");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageGridCompact).toContain("!flex");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageGridCompact).toContain("h-auto");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageGridCompact).toContain("flex-col");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageGridCompact).toContain("shrink-0");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageGridCompact).toContain("content-start");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageGridCompact).toContain("overflow-visible");
    expect(teamSourceCollectionStandaloneStagePanelStyles.sourceCollectionPageGridCompact).not.toContain("h-full");
    expect(teamSourceCollectionStandaloneStagePanelSource).toContain("compactActivePanel");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionResultsPanel).toContain("min-h-0");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionResultsPanel).toContain("!flex");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionResultsPanel).toContain("flex-col");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionResultsPanel).toContain("overflow-hidden");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionResultsPanel).toContain("max-[760px]:!h-auto");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionResultsPanel).toContain("max-[760px]:overflow-visible");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionResultsPanel).toContain("max-[760px]:min-h-0");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionResultsPanel).not.toContain("min-h-[260px]");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionResultsPanel).not.toContain("min-h-[210px]");
    expect(teamSourceCollectionConversationPanelSource).toContain("compact");
    expect(teamSourceCollectionConversationPanelSource).toContain("sourceCollectionResultsPanelCompact");
    expect(routeSource).toContain("const sourceCollectionConversationHasVisibleResults = visibleResults.length > 0");
    expect(routeSource).toContain("const sourceCollectionConversationCompact = !sourceCollectionConversationHasVisibleResults");
    expect(routeSource).toContain("compact={sourceCollectionConversationCompact}");
    expect(routeSource).toContain("const sourceCollectionActiveStageCompact =");
    expect(routeSource).toContain("compact={sourceCollectionActiveStageCompact}");
    expect(routeSource).toContain("const sourceCollectionFindingHasVisibleRecords =");
    expect(routeSource).toContain("&& !sourceCollectionFindingHasVisibleRecords");
    expect(routeSource).toContain("compactActivePanel={sourceCollectionFindingStageCompact}");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionConversationPanelCompact).toContain("h-auto");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionConversationPanelCompact).toContain("shrink-0");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionConversationPanelCompact).toContain("grid-rows-[auto_auto]");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionConversationPanelCompact).not.toContain("h-full");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionConversationPanelCompact).not.toContain("grid-rows-[auto_minmax(0,1fr)]");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionResultsPanelCompact).toContain("self-start");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionResultsPanelCompact).toContain("shrink-0");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionResultsPanelCompact).toContain("overflow-visible");
    expect(teamSourceCollectionConversationPanelStyles.sourceCollectionResultsPanelCompact).not.toContain("overflow-hidden");
    expect(teamSourceCollectionConversationPanelStylesSource).not.toContain("sourceCollectionConversationPanelCompact:\n    \"sourceCollectionConversationPanelCompact h-full");
    expect(teamSourceResultListSource).toContain("flex-1");
    expect(teamSourceResultListSource).toContain("overflow-auto");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionExtractionPanels).toContain("grid-cols-[minmax(0,1fr)]");
    expect(teamStageCommandBarSource).toContain('data-vui-product="team-stage-command-bar"');
    expect(teamStageCommandBarSource).toContain("flex flex-wrap items-center justify-between");
    expect(teamStageCardSource).toContain('data-vui-product="team-stage-card"');
    expect(teamStageCardSource).toContain("grid-cols-[minmax(0,1fr)_auto]");
    expect(teamStageCardSource).toContain("ACTION_ROW");
    expect(teamStageCardSource).toContain("ACTION_BUTTON");
    expect(teamStageCardSource).not.toContain("sourceCollectionStageProjection");
    expect(routeStyles.canvasLayoutModeSwitch).toContain("grid-cols-[repeat(auto-fit,minmax(86px,max-content))]");
    expect(routeSource).toContain("<VActionGroup");
    expect(routeStyles.canvasToolbar).toContain("grid-cols-[minmax(0,1fr)_max-content]");
    expect(routeStyles.canvasToolbar).toContain("max-[900px]:grid-cols-[minmax(0,1fr)]");
    expect(routeStyles.canvasToolbar).toContain("[&>div:first-child]:min-w-0");
    expect(routeStyles.toolbarActions).toContain("max-w-[min(100%,680px)]");
    expect(routeStyles.knowledgeCompletionFlowPanel).toContain("overflow-hidden");
    expect(routeStyles.knowledgeCompletionFlowHeader).toContain("grid-cols-[minmax(0,1fr)_auto]");
    expect(routeStyles.knowledgeCompletionFlowNodes).toContain("grid-cols-[repeat(auto-fit,minmax(280px,1fr))]");
    expect(routeStyles.knowledgeCompletionFlowNode).toContain("grid");
    expect(routeStyles.knowledgeCompletionFlowNode).toContain("rounded-[var(--radius-control)]");
    expect(routeStyles.knowledgeCompletionFlowNodeBody).toContain("[&_p]:max-w-[min(100%,72ch)]");
    expect(routeStyles.knowledgeCompletionFlowNodeBody).toContain("[&_p]:break-words");
    expect(routeStyles.workflowError).toContain("break-words");
    expect(routeStyles.knowledgeCompletionFlowError).toContain("break-words");
    expect(routeStyles.nodeRoleBadge).toContain("max-w-[128px]");
    expect(routeStyles.nodeRoleBadge).toContain("truncate");
    expect(teamMemoryIndexPanelStyles.teamMemoryRole).toContain("truncate");
    expect(teamStagePipelineSource).toContain("grid-cols-[repeat(auto-fit,minmax(220px,1fr))]");
    expect(teamStagePipelineSource).not.toContain("repeat(4");
    expect(teamStagePipelineSource).toContain("repeat(auto-fit,minmax(220px,1fr))");
    expect(teamStagePipelineSource).not.toContain("repeat(5");
    expect(teamSourceResultListSource).toContain("minmax(8rem,16rem)");
    expect(teamSourceResultListSource).not.toContain("max-h-[44vh]");
    expect(teamSourceResultListSource).not.toContain("max-h-[min(44vh,100%)]");
    expect(teamSourceResultListSource).not.toContain("minmax(120px,220px)");
    expect(teamSourceFilterBarSource).toContain("VButton");
    expect(teamSourceFilterBarSource).toContain("trailingIcon=");
    expect(teamSourceFilterBarSource).not.toContain("VNativeButton");
    expect(teamSourcePaginationSource).toContain("VButton");
    expect(teamSourcePaginationSource).not.toContain("VNativeButton");
    expect(teamCandidateCardSource).toContain("minmax(9rem,16rem)");
    expect(teamCandidateCardSource).toContain("row-span-3");
    expect(teamCandidateCardSource).toContain("VTooltip");
    expect(teamCandidateCardSource).not.toContain("title={activateTitle}");
    expect(teamCandidateCardSource).not.toContain("title={source.title}");
    expect(teamSourceResultListSource).toContain("VTooltip");
    expect(teamSourceResultListSource).not.toContain("title={activateTitle}");
    expect(teamSourceResultListSource).not.toContain("title={statusTitle}");
    expect(teamSourceResultListSource).not.toContain("title={titleTooltip}");
    expect(teamSourceResultListSource).not.toContain("title={source.title}");
    expect(teamStageCardSource).toContain("grid-cols-[minmax(0,1fr)_auto]");
    expect(teamStageCardSource).toContain("VTooltip");
    expect(teamStageCardSource).not.toContain("title={title}");
    expect(teamStageCardSource).toContain("ACTION_ROW");
    expect(teamStageCardSource).toContain("ACTION_BUTTON");
    expect(teamStageCardSource).toContain("text-[0.72rem]");
    expect(teamSourcePaginationSource).toContain("select-none");
    expect(teamSourcePaginationSource).toContain("whitespace-nowrap");
    expect(teamSourcePaginationSource).not.toContain("writing-mode:vertical");
    expect(teamSourceCollectionStorageActionsPanelStyles.workflowSourceCollectionStorageActions).toContain("grid-cols-[minmax(0,1fr)_auto]");
    expect(teamSourceCollectionStorageActionsPanelStyles.workflowSourceCollectionStorageButtons).toContain("justify-end");
    expect(teamSourceCollectionStorageActionsPanelStyles.workflowSourceCollectionStorageDetails).toContain("col-span-2");
    expect(teamSourceCollectionControlsPanelStyles.sourceCollectionControlPanel).toBeTypeOf("string");
    expect(teamStagePipelineSource).toContain("TeamStagePipeline");
    expect(teamStageCardSource).toContain("TeamStageCard");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspace).toBeTypeOf("string");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspaceHeader).toBeTypeOf("string");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageHandoff).toBeTypeOf("string");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageHandoffNext).toBeTypeOf("string");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageChatActions).toBeTypeOf("string");
    expect(routeStylesSource).not.toContain(".sourceCollectionStageTabs");
    expect(routeStylesSource).not.toContain(".sourceCollectionStageTabActive");
    expect(routeStylesSource).not.toContain(".sourceCollectionTraceHandoff");
    expect(teamSourcePaginationSource).toContain("TeamSourcePagination");
    expect(routeStylesSource).not.toContain(".sourceCollectionStageActionRow");
    expect(routeStylesSource).not.toContain(".sourceCollectionStageOperationPanel");
    expect(teamSourceCollectionScreeningPanelStyles.sourceCollectionPanelActions).toBeTypeOf("string");
    expect(teamSourceCollectionScreeningPanelStyles.sourceCollectionScreeningListShell).toBeTypeOf("string");
    expect(teamSourceCollectionScreeningPanelStyles.sourceCollectionScreeningList).toBeTypeOf("string");
    expect(teamSourceCollectionScreeningPanelStyles.sourceCollectionScreeningScrollHint).toBeTypeOf("string");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStagePrimaryAction).toBeTypeOf("string");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageSecondaryAction).toBeTypeOf("string");
    expect(teamSourceCollectionPanelFrameStyles.sourceCollectionFocusedPanel).toBeTypeOf("string");
    expect(routeStyles.sourceCollectionStepActive).toBeTypeOf("string");
    expect(routeStyles.sourceCollectionStepDone).toBeTypeOf("string");
    expect(routeStyles.sourceCollectionStepFailed).toBeTypeOf("string");
    expect(routeStyles.sourceCollectionStepIdle).toBeTypeOf("string");
    expect(routeStyles.sourceCollectionStepPending).toBeTypeOf("string");
    expect(routeStyles.sourceCollectionStepActive).toContain("accent-cool");
    expect(routeStyles.sourceCollectionStepDone).toContain("state-success");
    expect(routeStyles.sourceCollectionStepFailed).toContain("state-error");
    expect(routeStyles.sourceCollectionStepPending).toContain("state-warning");
    expect(teamSourceCollectionStorageActionsPanelStyles.workflowSourceCollectionStorageDetails).toBeTypeOf("string");
    expect(routeStyles.researchStagePage).toBeTypeOf("string");
    expect(routeStyles.researchStageHeroPanel).toBeTypeOf("string");
    expect(routeStyles.researchStageActionPanel).toBeTypeOf("string");
    expect(routeStyles.researchStageModuleGrid).toBeTypeOf("string");
    expect(routeStyles.researchStageBoundaryPanel).toBeTypeOf("string");
    expect(teamWorkflowStatusPanelStyles.workflowGraphPanel).toBeTypeOf("string");
    expect(workflowGraphViewStyles.workflowGraphFrame).toBeTypeOf("string");
    expect(workflowGraphViewStyles.workflowGraphNode).toBeTypeOf("string");
    expect(workflowGraphViewStyles.workflowGraphEdge).toBeTypeOf("string");
    expect(teamWorkflowStatusPanelStyles.workflowGraphBoundary).toBeTypeOf("string");
    expect(routeStylesSource).not.toContain("workflowCandidateList:");
    expect(teamSourceCollectionCandidatePanelStyles.workflowCandidateList).toBeTypeOf("string");
    expect(routeStylesSource).not.toContain("workflowCandidateListPanel");
    expect(routeStylesSource).not.toContain("workflowCandidateListHeader");
    expect(routeStylesSource).not.toContain("workflowCandidateListScroll");
    expect(routeStylesSource).not.toContain("workflowCandidateListScrollHint");
    expect(routeStylesSource).not.toContain("workflowCandidateActions");
    expect(teamWorkflowCandidatePreviewPanelStylesSource).toContain("workflowCandidateListPanel");
    expect(teamWorkflowCandidatePreviewPanelStylesSource).toContain("workflowCandidateListHeader");
    expect(teamWorkflowCandidatePreviewPanelStylesSource).toContain("workflowCandidateListScroll");
    expect(teamWorkflowCandidatePreviewPanelStylesSource).toContain("workflowCandidateListScrollHint");
    expect(routeStylesSource).not.toContain("workflowModelEvidencePanel");
    expect(routeStylesSource).not.toContain("workflowCoordinationPanel");
    expect(routeStylesSource).not.toContain("workflowIngestionPanel");
    expect(routeStylesSource).not.toContain("workflowGraphPanel");
    expect(routeStylesSource).not.toContain("workflowSourceQualityPanel");
    expect(routeStylesSource).not.toContain("workflowPaperNoteChunkPanel");
    expect(teamWorkflowStatusPanelStylesSource).toContain("workflowModelEvidencePanel");
    expect(teamWorkflowStatusPanelStylesSource).toContain("workflowCoordinationPanel");
    expect(teamWorkflowStatusPanelStylesSource).toContain("workflowIngestionPanel");
    expect(teamWorkflowStatusPanelStylesSource).toContain("workflowGraphPanel");
    expect(teamWorkflowStatusPanelStylesSource).toContain("workflowSourceQualityPanel");
    expect(teamWorkflowStatusPanelStylesSource).toContain("workflowPaperNoteChunkPanel");
    expect(routeStylesSource).not.toContain("workflowSourceCollectionPanel");
    expect(routeStylesSource).not.toContain("workflowSourceCollectionStats");
    expect(routeStylesSource).not.toContain("workflowSourceCollectionPlan");
    expect(routeStylesSource).not.toContain("workflowSourceCollectionForm");
    expect(routeStylesSource).not.toContain("workflowSourceCollectionOutputForm");
    expect(routeStylesSource).not.toContain("workflowSourceCollectionStorageActions");
    expect(teamSourceCollectionOverviewPanelStylesSource).toContain("workflowSourceCollectionPanel");
    expect(teamSourceCollectionOverviewPanelStylesSource).toContain("workflowSourceCollectionStats");
    expect(teamSourceCollectionOverviewPanelStylesSource).toContain("workflowSourceCollectionPlan");
    expect(routeStyles.workflowValidation).toBeTypeOf("string");
    expect(routeStyles.workspaceResearch).toBeTypeOf("string");
    expect(routeStyles.workspaceResearchCanvas).toBeTypeOf("string");
    expect(routeStyles.researchStageLauncher).toBeTypeOf("string");
    expect(routeStyles.researchStageHeaderActions).toBeTypeOf("string");
    expect(routeStyles.researchStageDegradedNotice).toBeTypeOf("string");
    expect(routeStyles.researchStageStatus).toBeTypeOf("string");
    expect(routeStyles.researchStageStatusLoading).toBeTypeOf("string");
    expect(routeStyles.researchStageStatusUnavailable).toBeTypeOf("string");
    expect(routeStyles.researchStageCard).toBeTypeOf("string");
    expect(routeStyles.researchStageCardHead).toBeTypeOf("string");
    expect(routeStyles.researchStageCardMetrics).toBeTypeOf("string");
    expect(routeStyles.researchStageAgentSummary).toBeTypeOf("string");
    expect(routeStyles.researchStageAgentSummaryLoading).toBeTypeOf("string");
    expect(routeStyles.researchStageAgentSummaryReady).toBeTypeOf("string");
    expect(routeStyles.researchStageAgentSummaryMissing).toBeTypeOf("string");
    expect(routeStyles.researchStageAgentSummaryBlocked).toBeTypeOf("string");
    expect(routeStyles.researchStageAgentPanel).toBeTypeOf("string");
    expect(routeStyles.researchStageAgentPanelCompact).toBeTypeOf("string");
    expect(routeStyles.researchStageAgentGrid).toBeTypeOf("string");
    expect(routeStyles.researchStageAgentCard).toBeTypeOf("string");
    expect(routeStyles.researchStageAgentCard_ready).toBeTypeOf("string");
    expect(routeStyles.researchStageAgentCard_warning).toBeTypeOf("string");
    expect(routeStyles.researchStageAgentCard_blocked).toBeTypeOf("string");
    expect(routeStyles.researchStageAgentCard_missing).toBeTypeOf("string");
    expect(teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentPanel).toBeTypeOf("string");
    expect(teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentHeader).toBeTypeOf("string");
    expect(teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentList).toBeTypeOf("string");
    expect(teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentCard).toBeTypeOf("string");
    expect(teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentCardBody).toBeTypeOf("string");
    expect(teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentCardActions).toBeTypeOf("string");
    expect(routeStyles.researchInspector).toBeTypeOf("string");
    expect(routeStyles.researchCanvasPanelHidden).toBeTypeOf("string");
    expect(routeStyles.canvasReadOnlyBadge).toBeTypeOf("string");
    expect(routeStyles.canvasReadOnlyPanel).toBeTypeOf("string");
    expect(routeStyles.canvasLayoutModeSwitch).toBeTypeOf("string");
    expect(routeStyles.canvasReadOnlyNotice).toBeTypeOf("string");
    expect(routeStyles.canvasReadOnlyNode).toBeTypeOf("string");
    expect(routeStyles.canvasReadOnlyNodeWide).toBeTypeOf("string");
    expect(routeStyles.nodeReadOnly).toBeTypeOf("string");
    expect(routeStyles.aiSearchScopePanel).toBeTypeOf("string");
    expect(routeStyles.aiSearchScopeStats).toBeTypeOf("string");
    expect(routeStyles.aiSearchSourceGroups).toBeTypeOf("string");
    expect(routeStyles.aiSearchSourceItem).toBeTypeOf("string");
    expect(routeStyles.aiSearchRunPanel).toBeTypeOf("string");
    expect(routeStyles.aiSearchRunHeader).toBeTypeOf("string");
    expect(routeStyles.aiSearchRunStats).toBeTypeOf("string");
    expect(routeStyles.aiSearchRunCard).toBeTypeOf("string");
    expect(routeStyles.aiSearchRunRefs).toBeTypeOf("string");
    expect(routeStyles.teamUnavailableSurface).not.toContain("place-items-center");
    expect(routeStyles.teamUnavailableSurface).toContain("justify-center");
    expect(routeStyles.teamUnavailableSurface).toContain("content-start");
    expect(routeStyles.teamUnavailableSurface).toContain("grid-cols-[minmax(0,720px)]");
    expect(routeStyles.teamUnavailableCard).toContain("max-w-[720px]");
    expect(routeStyles.workspace).toContain("grid-cols-[minmax(0,1fr)_clamp(320px,26vw,420px)]");
    expect(routeStyles.workspace).toContain("overflow-hidden");
    expect(routeStyles.workspace).toContain("max-[760px]:h-auto");
    expect(routeStyles.workspace).toContain("max-[760px]:grid-cols-[minmax(0,1fr)]");
    expect(routeStyles.workspace).toContain("max-[760px]:content-start");
    expect(routeStyles.workspace).toContain("max-[760px]:overflow-auto");
    expect(routeStyles.workspaceResearchCanvas).toContain("h-full");
    expect(routeStyles.workspaceResearchCanvas).toContain("grid-cols-[minmax(0,1fr)_clamp(320px,26vw,420px)]");
    expect(routeStyles.workspaceResearchCanvas).toContain("overflow-hidden");
    expect(routeStyles.workspaceResearchCanvas).toContain("max-[760px]:h-auto");
    expect(routeStyles.workspaceResearchCanvas).toContain("max-[760px]:grid-cols-[minmax(0,1fr)]");
    expect(routeStyles.workspaceResearchCanvas).toContain("max-[760px]:overflow-auto");
    expect(routeStyles.workspaceResearchCanvas).toContain("max-[760px]:content-start");
    expect(workflowGraphViewStyles.workflowGraphFrame).toContain("h-[var(--workflow-graph-height,360px)]");
    expect(workflowGraphViewStyles.workflowGraphFrame).not.toContain("h-full");
    expect(workflowGraphViewStyles.workflowGraphFrame).toContain("overflow-auto");
    expect(routeStyles.canvasPanel).toContain("!flex");
    expect(routeStyles.canvasPanel).not.toContain("bg-[var(--vui-surface-panel)]");
    expect(routeStyles.canvasPanel).not.toContain("bg-[var(--vui-surface-glass)]");
    expect(routeStyles.canvasPanel).not.toContain("shadow-[var(--vui-shadow-hairline)]");
    expect(routeStyles.canvas).toContain("bg-[var(--vui-surface-base)]");
    expect(routeStyles.canvas).toContain("[background-size:40px_40px]");
    expect(routeStyles.canvas).not.toContain("var(--vui-surface-glass)_94%");
    expect(routeStyles.inspector).toContain("!flex");
    expect(routeStylesSource).toContain(".canvasLayoutModeSwitch");
  });

  it("uses shared Phase 2 surfaces for Team unavailable and canvas states", () => {
    expect(routeSource).toContain("VActionGroup");
    expect(routeSource).toContain("VSurface");
    expect(routeSource).toContain('tone="unavailable"');
    expect(routeSource).toContain('tone="rail"');
    expect(routeSource).toContain('elevation="panel"');
    expect(routeSource).not.toContain("<section className={styles.teamUnavailableCard}");
    expect(routeStyles.canvasPanel).not.toContain("rounded-[var(--radius-panel)]");
    expect(routeStyles.canvasPanel).not.toContain("bg-[var(--vui-surface-panel)]");
    expect(routeStyles.teamUnavailableSurface).not.toContain("bg-[var(--vui-surface-panel)]");
  });

  it("uses quiet workbench panels instead of nested glass card walls in the Team canvas", () => {
    const quietSurfaceKeys = [
      "canvasPanel",
      "teamHistoryPanel",
      "teamRoundPanel",
      "workflowPanel",
      "teamMemoryMemberCard",
    ] as const;

    for (const key of quietSurfaceKeys) {
      expect(routeStyles[key]).not.toContain("bg-[var(--vui-surface-glass)]");
      expect(routeStyles[key]).not.toContain("shadow-[var(--vui-shadow-hairline)]");
    }

    expect(routeStyles.workflowPanel).toContain("bg-[var(--vui-surface-panel)]");
    expect(routeStyles.teamRoundPanel).toContain("bg-[var(--vui-surface-panel)]");
    expect(routeStyles.teamHistoryPanel).toContain("bg-[var(--vui-surface-panel)]");
  });

  it("keeps Teams route-level research and workflow surfaces operational instead of decorative", () => {
    const routeOperationalPanelKeys = [
      "aiSearchRunPanel",
      "aiSearchRunSummary",
      "aiSearchScopePanel",
      "aiSearchWorkflowSummary",
      "experimentKnowledgePanel",
      "experimentLedgerPanel",
      "experimentPlanSummary",
      "knowledgeCompletionFlowPanel",
      "researchDiscussionPanel",
      "researchLoopPanel",
      "researchLoopTemplateSummary",
      "researchStageActionPanel",
      "researchStageBoundaryPanel",
      "researchStageHeroPanel",
      "researchStageModuleCard",
      "teamRoundCard",
      "workflowPanel",
    ] as const;

    for (const key of routeOperationalPanelKeys) {
      expectOperationalSurface(routeStyles[key]);
    }

    const routeRowKeys = [
      "aiSearchRunCard",
      "aiSearchRunCardDegraded",
      "aiSearchRunCardDetails",
      "aiSearchRunCardHeader",
      "aiSearchRunCardReview",
      "researchStageAgentCard",
      "researchStageAgentPanel",
      "researchStageCard",
    ] as const;

    for (const key of routeRowKeys) {
      expectOperationalSurface(routeStyles[key], "bg-[var(--vui-surface-row)]");
    }

    expect(routeStyles.researchStageCard).toContain("rounded-[var(--radius-panel)]");
    expect(routeStyles.researchStageCard).not.toContain("hover:-translate-y-px");
    expect(routeStyles.researchStageHeroPanel).toContain("rounded-[var(--radius-panel)]");
    expect(routeStyles.sourceCollectionUnavailable).toContain("rounded-[var(--radius-panel)]");
    expect(routeStyles.sourceCollectionUnavailable).not.toContain("rounded-lg");
    expect(routeStyles.sourceCollectionUnavailable).not.toContain("bg-[image:var(--vui-gradient-route-soft)]");

    const researchAgentCardToneKeys = [
      "researchStageAgentCard_ready",
      "researchStageAgentCard_warning",
      "researchStageAgentCard_blocked",
      "researchStageAgentCard_missing",
      "researchStageAgentCard_error",
    ] as const;

    for (const key of researchAgentCardToneKeys) {
      const composedClassName = `${routeStyles.researchStageAgentCard} ${routeStyles[key]}`;
      expectOperationalSurface(composedClassName, "bg-[var(--vui-surface-row)]");
      expect(topLevelBackgroundTokenCount(composedClassName)).toBe(1);
      expect(composedClassName).not.toContain("bg-[color-mix");
    }

    const researchAgentSummaryToneKeys = [
      "researchStageAgentSummaryReady",
      "researchStageAgentSummaryMissing",
      "researchStageAgentSummaryBlocked",
    ] as const;

    for (const key of researchAgentSummaryToneKeys) {
      const composedClassName = `${routeStyles.researchStageAgentSummary} ${routeStyles[key]}`;
      expectOperationalSurface(composedClassName, "bg-[var(--vui-control-muted)]");
      expect(topLevelBackgroundTokenCount(composedClassName)).toBe(1);
      expect(composedClassName).not.toContain("bg-[color-mix");
    }

    const compactPanelClassName = `${routeStyles.researchStageAgentPanel} ${routeStyles.researchStageAgentPanelCompact}`;
    expectOperationalSurface(compactPanelClassName, "bg-[var(--vui-surface-row)]");
    expect(topLevelBackgroundTokenCount(compactPanelClassName)).toBe(1);
    expect(compactPanelClassName).not.toContain("bg-[color-mix");

    expectOperationalSurface(routeStyles.researchStageAgentPanelHeader, "bg-[var(--vui-surface-row)]");
    expect(topLevelBackgroundTokenCount(routeStyles.researchStageAgentPanelHeader)).toBe(1);
    expect(routeStyles.researchStageAgentPanelHeader).not.toContain("bg-[color-mix");

    const researchAgentInlineKeys = [
      "researchStageAgentActions",
      "researchStageAgentGrid",
      "researchStageAgentMeta",
      "researchStageAgentRole",
    ] as const;

    for (const key of researchAgentInlineKeys) {
      expect(topLevelBackgroundTokenCount(routeStyles[key])).toBe(0);
      expect(routeStyles[key]).not.toContain("bg-[color-mix");
    }
  });

  it("keeps Team source collection child panels flat and scan-first", () => {
    const sourceCollectionPanelSurfaces = [
      teamSourceCollectionPanelFrameStyles.sourceCollectionFocusedPanel,
      teamSourceCollectionPanelFrameStyles.workflowSourceCollectionDetails,
      teamSourceCollectionConversationPanelStyles.sourceCollectionConversationPanel,
      teamSourceCollectionConversationPanelStyles.sourceCollectionResultsPanel,
      teamSourceCollectionControlsPanelStyles.sourceCollectionControlPanel,
      teamSourceCollectionOverviewPanelStyles.workflowSourceCollectionPanel,
      teamSourceCollectionSourceDetailPanelStyles.sourceCollectionSourceDetailPanel,
      teamSourceCollectionSourceDetailPanelStyles.sourceCollectionSourceDetailNotice,
      teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentPanel,
      teamWorkflowStatusPanelStyles.workflowCoordinationBriefSummary,
      teamWorkflowStatusPanelStyles.workflowCoordinationPanel,
      teamWorkflowStatusPanelStyles.workflowGraphPanel,
      teamWorkflowStatusPanelStyles.workflowIngestionPanel,
      teamWorkflowStatusPanelStyles.workflowModelEvidencePanel,
      teamWorkflowStatusPanelStyles.workflowPaperNoteChunkPanel,
      teamWorkflowStatusPanelStyles.workflowSourceQualityPanel,
    ];

    for (const className of sourceCollectionPanelSurfaces) {
      expectOperationalSurface(className);
    }

    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspaceHeader).toContain("bg-[var(--vui-surface-panel)]");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspaceHeader).not.toContain(
      "bg-[color:var(--source-workbench-card)]",
    );
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageChatActions).not.toContain(
      "bg-[image:var(--vui-gradient-route-soft)]",
    );
    expect(teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentCard).toContain("bg-[var(--vui-surface-row)]");
    expect(teamSourceCollectionSourceDetailPanelStyles.sourceCollectionSourceDetailHeader).toContain("bg-[var(--vui-surface-row)]");
    expect(teamSourceCollectionSourceDetailPanelStyles.sourceCollectionSourceDetailFacts).toContain("bg-[var(--vui-surface-row)]");
  });

  it("prioritizes active stage task launch and interruption status over stale summaries", () => {
    const launchStateIndex = routeSource.indexOf("function sourceCollectionStageDisplayState");
    const extractionModuleStateIndex = routeSource.indexOf('state: sourceCollectionStageDisplayState("extraction"');
    expect(launchStateIndex).toBeGreaterThan(0);
    expect(extractionModuleStateIndex).toBeGreaterThan(launchStateIndex);

    const interruptedSummaryIndex = stageProjectionSource.indexOf("function sourceCollectionStageInterruptedSummary");
    const staleUserSummaryIndex = stageProjectionSource.indexOf('if (lang === "zh" && projection.userSummary)');
    expect(interruptedSummaryIndex).toBeGreaterThan(0);
    expect(staleUserSummaryIndex).toBeGreaterThan(interruptedSummaryIndex);
  });

  it("keeps restored TeamsRoute grids from the CSS module migration", () => {
    const restoredGridExpectations: Array<[string, string]> = [
      [routeStyles.aiSearchRunCards, "grid-cols-[repeat(auto-fit,minmax(220px,1fr))]"],
      [routeStyles.researchStageCardHead, "grid-cols-[auto_minmax(0,1fr)]"],
      [routeStyles.researchStageCardMetrics, "grid-cols-[repeat(3,minmax(0,1fr))]"],
      [routeStyles.researchStageAgentGrid, "grid-cols-[repeat(auto-fit,minmax(210px,1fr))]"],
      [teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentCard, "grid-cols-[minmax(0,1fr)_auto]"],
      [teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentCardBody, "grid-cols-[repeat(3,minmax(0,1fr))]"],
      [teamSourceCollectionSourceDetailPanelStyles.sourceCollectionSourceDetailFacts, "grid-cols-[repeat(auto-fit,minmax(180px,1fr))]"],
      [routeStyles.researchStageHeroStats, "grid-cols-[repeat(3,minmax(0,1fr))]"],
      [routeStyles.workflowStats, "grid-cols-[repeat(3,minmax(0,1fr))]"],
      [teamWorkflowStatusPanelStyles.workflowModelEvidenceStats, "grid-cols-[repeat(auto-fit,minmax(118px,1fr))]"],
      [teamWorkflowStatusPanelStyles.workflowModelEvidenceCoverage, "grid-cols-[repeat(auto-fit,minmax(118px,1fr))]"],
      [teamSourceCollectionRunSettingsPanelStyles.workflowSourceCollectionForm, "grid-cols-[repeat(2,minmax(0,1fr))]"],
      [teamSourceCollectionManualWritebackPanelStyles.workflowSourceCollectionOutputForm, "grid-cols-[repeat(2,minmax(0,1fr))]"],
      [teamWorkflowStatusPanelStyles.workflowIngestionStages, "grid-cols-[repeat(5,minmax(58px,1fr))]"],
      [teamWorkflowStatusPanelStyles.workflowSourceQualityStats, "grid-cols-[repeat(5,minmax(72px,1fr))]"],
      [teamWorkflowStatusPanelStyles.workflowSourceQualityQueue, "grid-cols-[repeat(3,minmax(0,1fr))]"],
      [teamWorkflowStatusPanelStyles.workflowPaperNoteChunkStats, "grid-cols-[repeat(4,minmax(86px,1fr))]"],
      [teamWorkflowStatusPanelStyles.workflowPaperNoteChunkPlans, "grid-cols-[repeat(2,minmax(0,1fr))]"],
    ];

    for (const [className, gridTemplate] of restoredGridExpectations) {
      expect(className).toContain("!grid");
      expect(className).toContain(gridTemplate);
    }

    expect(teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentCard).toContain("[&_a]:inline-flex");
    expect(teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentCard).toContain("[&_[data-vui=native-button]]:inline-flex");
  });

  it("keeps source collection subpanels compact, text-safe, and mobile-safe", () => {
    expect(teamSourceCollectionPanelFrameStyles.sourceCollectionFocusedPanel).toContain("max-[960px]:grid-cols-[minmax(0,1fr)]");
    expect(teamSourceCollectionControlsPanelStyles.sourceCollectionControlPanel).toContain("!grid");
    expect(teamSourceCollectionControlsPanelStyles.sourceCollectionControlPanel).toContain("grid-cols-[minmax(0,1fr)]");
    expect(teamSourceCollectionControlsPanelStyles.workflowIngestionHeader).toContain("grid-cols-[minmax(0,1fr)_auto]");
    expect(teamSourceCollectionControlsPanelStyles.workflowTag).toContain("truncate");

    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspaceHeader).toContain("max-[760px]:grid-cols-[minmax(0,1fr)]");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageWorkspaceHeader).toContain("[&>div>strong]:truncate");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageHandoff).toContain("[&>span]:min-w-0");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageHandoff).toContain("[&>span]:break-words");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageChatActions).toContain("[&_[data-vui=native-button]]:w-fit");
    expect(teamSourceCollectionActiveStagePanelStyles.sourceCollectionStageChatActions).not.toContain("max-[720px]:grid-cols-[1fr]");

    expect(teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentPanel).not.toContain("shadow-[var(--vui-shadow-hairline)]");
    expect(teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentCard).toContain("bg-[var(--vui-surface-row)]");
    expect(teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentCard).toContain("max-[720px]:grid-cols-[minmax(0,1fr)]");
    expect(teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentCardBody).not.toContain("shadow-[var(--vui-shadow-hairline)]");
    expect(teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentCardBody).toContain("max-[680px]:grid-cols-[minmax(0,1fr)]");
    expect(teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentCardBody).toContain("[&_strong]:truncate");
    expect(teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentCardActions).not.toContain("shadow-[var(--vui-shadow-hairline)]");
    expect(teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentCardActions).toContain("justify-end");
    expect(teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentCardActions).toContain("max-[720px]:justify-start");
    expect(teamSourceCollectionStageAgentsPanelStyles.sourceCollectionStageAgentCardActions).toContain("[&_a]:w-fit");

    for (const className of [
      teamWorkflowStatusPanelStyles.workflowIngestionStages,
      teamWorkflowStatusPanelStyles.workflowSourceQualityStats,
      teamWorkflowStatusPanelStyles.workflowSourceQualityQueue,
      teamWorkflowStatusPanelStyles.workflowPaperNoteChunkStats,
      teamWorkflowStatusPanelStyles.workflowPaperNoteChunkPlans,
    ]) {
      expect(className).toContain("max-[760px]:grid-cols-[minmax(0,1fr)]");
    }

    expect(teamWorkflowStatusPanelStyles.workflowIngestionStage).toContain("[&_strong]:truncate");
    expect(teamWorkflowStatusPanelStyles.workflowSourceQualityQueue).toContain("[&_strong]:truncate");
    expect(teamWorkflowStatusPanelStyles.workflowPaperNoteChunkPlans).toContain("[&_small]:break-words");
    expect(teamWorkflowStatusPanelStyles.workflowIngestionHeader).toContain("grid-cols-[minmax(0,1fr)_auto]");
    expect(teamWorkflowStatusPanelStyles.workflowIngestionActions).toContain("[&_span]:break-words");
  });

  it("keeps Teams graph and candidate child panels light, text-safe, and mobile-fit", () => {
    expect(teamWorkflowCandidatePreviewPanelStyles.workflowCandidateListPanel).toContain("bg-[var(--vui-surface-panel)]");
    expect(teamWorkflowCandidatePreviewPanelStyles.workflowCandidateListPanel).toContain("overflow-hidden");
    expect(teamWorkflowCandidatePreviewPanelStyles.workflowCandidateListPanel).not.toContain("bg-[var(--vui-surface-glass)]");
    expect(teamWorkflowCandidatePreviewPanelStyles.workflowCandidateListPanel).not.toContain("shadow-[var(--vui-shadow-hairline)]");
    expect(teamWorkflowCandidatePreviewPanelStyles.workflowCandidateListHeader).toContain("grid-cols-[minmax(0,1fr)_auto]");
    expect(teamWorkflowCandidatePreviewPanelStyles.workflowCandidateListHeader).toContain("max-[760px]:grid-cols-[minmax(0,1fr)]");
    expect(teamWorkflowCandidatePreviewPanelStyles.workflowCandidateListHeader).toContain("[&>div:first-child>strong]:truncate");
    expect(teamWorkflowCandidatePreviewPanelStyles.workflowCandidateListHeader).toContain("[&>div:first-child>span]:break-words");
    expect(teamWorkflowCandidatePreviewPanelStyles.workflowCandidateListHeader).toContain("[&_[data-vui=native-button]]:w-fit");
    expect(teamWorkflowCandidatePreviewPanelStyles.workflowCandidateListHeader).toContain("[&_[data-vui=native-button]]:whitespace-nowrap");
    expect(teamWorkflowCandidatePreviewPanelStyles.workflowCandidateListScroll).toContain("[scrollbar-gutter:stable]");
    expect(teamWorkflowCandidatePreviewPanelStyles.workflowCandidateList).toContain("[&_[data-vui-product=team-candidate-card]]:max-w-full");

    expect(classTokenCount(teamMemoryIndexPanelStyles.teamMemoryActionRail, "flex")).toBe(1);
    expect(classTokenCount(teamMemoryIndexPanelStyles.teamMemoryActionRail, "grid")).toBe(0);
    expect(classTokenCount(teamMemoryIndexPanelStyles.teamMemoryActionRail, "min-w-0")).toBe(1);
    expect(teamMemoryIndexPanelStyles.teamMemoryActionRail).toContain("[&_a]:w-fit");
    expect(classTokenCount(teamMemoryIndexPanelStyles.teamMemoryMemberActions, "flex")).toBe(1);
    expect(teamMemoryIndexPanelStyles.teamMemoryMemberActions).toContain("[&_a]:flex-none");

    expect(workflowGraphViewStyles.workflowGraphFrame).toContain("max-w-full");
    expect(workflowGraphViewStyles.workflowGraphFrame).toContain("overflow-auto");
    expect(workflowGraphViewStyles.workflowGraphFrame).toContain("[scrollbar-gutter:stable]");
    expect(workflowGraphViewStyles.workflowGraphCanvas).toContain("min-w-[var(--workflow-graph-width,720px)]");
    expect(workflowGraphViewStyles.workflowGraphNode).toContain("bg-[var(--vui-surface-row)]");
    expect(workflowGraphViewStyles.workflowGraphNode).toContain("shadow-none");
    expect(workflowGraphViewStyles.workflowGraphNode).not.toContain("shadow-[var(--vui-shadow-hairline)]");

    expect(teamSourceCollectionGraphPanelStyles.sourceCollectionGraphNodeListShell).toContain("max-w-full");
    expect(teamSourceCollectionGraphPanelStyles.sourceCollectionGraphNodeListShell).toContain("bg-[var(--vui-surface-panel)]");
    expect(teamSourceCollectionGraphPanelStyles.workflowCandidateList).toContain("[&_[data-vui-product=team-candidate-card]]:max-w-full");
    expect(teamSourceCollectionGraphPanelStyles.workflowCandidateList).toContain("[&_[data-vui=native-button]]:w-fit");

    expect(teamSourceCollectionFindingDetailsPanelStyles.workflowSourceCollectionAssignments).toContain(
      "grid-cols-[repeat(auto-fit,minmax(9rem,max-content))]",
    );
    expect(teamSourceCollectionFindingDetailsPanelStyles.workflowSourceCollectionAssignments).toContain("max-[640px]:grid-cols-[minmax(0,1fr)]");
    expect(teamSourceCollectionFindingDetailsPanelStyles.workflowSourceCollectionAssignments).toContain("[&_[data-vui=native-button]]:w-fit");
    expect(teamSourceCollectionFindingDetailsPanelStyles.workflowSourceCollectionAssignments).toContain("[&_[data-vui=native-button]_strong]:truncate");
    expect(teamSourceCollectionFindingDetailsPanelStyles.workflowSourceCollectionAssignments).toContain("[&_[data-vui=native-button]_span]:break-words");
    expect(teamSourceCollectionFindingDetailsPanelStyles.workflowSourceCollectionQueries).toContain("[&_strong]:truncate");
    expect(teamSourceCollectionFindingDetailsPanelStyles.workflowSourceCollectionQueries).toContain("[&_small]:break-words");
  });

  it("uses a subtle mesh canvas background instead of repeated horizontal route stripes", () => {
    for (const className of [routeStyles.canvas, routeStyles.emptyCanvasPanel]) {
      expect(className).toContain("[background-image:linear-gradient(to_right");
      expect(className).toContain("linear-gradient(to_bottom");
      expect(className).toContain("[background-size:40px_40px]");
      expect(className).toContain("var(--vui-border-subtle)_24%");
      expect(className).not.toContain("vui-gradient-route-soft");
    }
  });

  it("keeps one knowledge collection loop CTA on the phase card and leaves manual work in stage details", () => {
    const launcherSource = routeSource.slice(
      routeSource.indexOf("function renderResearchStageLauncher"),
      routeSource.indexOf("function renderResearchStageStandalonePage"),
    );
    expect(launcherSource).toContain("runKnowledgeCollectionLoopAction");
    expect(launcherSource).toContain("sourceCollectionLoopActionLabel");
    expect(launcherSource).toContain("sourceCollectionLoopActionDisabled");
    expect(launcherSource).toContain("手动控制");
    expect(routeSource).toContain("开始第一轮闭环");
    expect(routeSource).toContain("继续本轮闭环");
    expect(routeSource).toContain("开始下一轮闭环");
    expect(launcherSource).not.toContain("一键完成知识搜集");
    expect(launcherSource).not.toContain("新一轮搜集");

    const stageModuleSource = routeSource.slice(
      routeSource.indexOf("const sourceCollectionStageModules"),
      routeSource.indexOf("const sourceCollectionBoardCurrentModule"),
    );
    const ingestionModuleSource = stageModuleSource.slice(
      stageModuleSource.indexOf('id: "ingestion"'),
      stageModuleSource.indexOf("];"),
    );
    expect(ingestionModuleSource).toContain('onAction: () => void startSourceCollectionStageSessionTask("ingestion")');
    expect(ingestionModuleSource).not.toContain("runKnowledgeCollectionCompletionAction");
    expect(ingestionModuleSource).not.toContain("runKnowledgeCollectionCompletionMutation");
    expect(ingestionModuleSource).not.toContain("runKnowledgeCollectionIngestMutation.mutate");
  });

  it("starts a new source collection run before completion when the loop CTA represents the next loop", () => {
    const loopActionSource = routeSource.slice(
      routeSource.indexOf("const runKnowledgeCollectionLoopAction ="),
      routeSource.indexOf("const runSourceCollectionSearchFromHeader ="),
    );
    expect(loopActionSource).toContain("sourceCollectionLoopStartsNewRun");
    expect(loopActionSource).toContain("startSourceCollectionRunMutation.mutateAsync");
    expect(loopActionSource).toContain("const startedRunId =");
    expect(loopActionSource).toContain("startKnowledgeCollectionCompletionForRun(startedRunId");
    expect(loopActionSource).toContain("startKnowledgeCollectionCompletionForRun(sourceCollectionActionRunId");
  });

  it("lets a completed knowledge collection work run clear stale one-click mutation errors", () => {
    const completionStateSource = routeSource.slice(
      routeSource.indexOf("const selectedTeamKnowledgeCollectionWorkRun ="),
      routeSource.indexOf("const selectedTeamKnowledgeCollectionIngestResult ="),
    );
    expect(completionStateSource).toContain("selectedTeamKnowledgeCollectionCompleted");
    expect(completionStateSource).toContain('selectedTeamKnowledgeCollectionWorkRunStatus === "completed"');
    expect(completionStateSource).toContain('selectedTeamKnowledgeCollectionFlowStatus === "completed"');

    const ingestErrorSource = routeSource.slice(
      routeSource.indexOf("const selectedTeamKnowledgeCollectionIngestError ="),
      routeSource.indexOf("const selectedTeamKnowledgeCollectionIngestResult ="),
    );
    expect(ingestErrorSource).toContain("!selectedTeamKnowledgeCollectionCompleted");
  });

  it("does not treat a completed knowledge work run from another source run as the selected loop completion", () => {
    const completionStateSource = routeSource.slice(
      routeSource.indexOf("const selectedTeamKnowledgeCollectionWorkRun ="),
      routeSource.indexOf("const selectedTeamKnowledgeCollectionIngestResult ="),
    );
    expect(completionStateSource).toContain("selectedTeamKnowledgeCollectionSourceRunId");
    expect(completionStateSource).toContain("selectedTeamKnowledgeCollectionMatchesSelectedRun");
    expect(completionStateSource).toContain(
      "selectedTeamKnowledgeCollectionSourceRunId === selectedSourceCollectionRunEffectiveId",
    );

    const loopStateSource = routeSource.slice(
      routeSource.indexOf("const sourceCollectionLoopStartsNewRun ="),
      routeSource.indexOf("const sourceCollectionLoopStartReadiness ="),
    );
    expect(loopStateSource).toContain("selectedTeamKnowledgeCollectionCompletedForSelectedRun");
  });

  it("keeps side-effect source collection actions behind initial-data readiness gates", () => {
    expect(routeSource).toContain("type SourceCollectionActionReadiness");
    expect(routeSource).toContain("sourceCollectionActionInitialDataPending");
    expect(routeSource).toContain("sourceCollectionActionDataError");
    expect(routeSource).toContain("sourceCollectionSearchActionReadiness");
    expect(routeSource).toContain("sourceCollectionCompletionActionReadiness");
    expect(routeSource).toContain("sourceCollectionCandidateExtractionActionReadiness");
    expect(routeSource).toContain("sourceCollectionScreeningActionReadiness");
    expect(routeSource).toContain("sourceCollectionGraphActionReadiness");
    expect(routeSource).toContain("sourceCollectionMemoryActionReadiness");
    expect(routeSource).toContain("sourceCollectionStageTaskActionReadiness");
    expect(routeSource).toContain("sourceCollectionActionDisabledTitle");

    const readinessSource = routeSource.slice(
      routeSource.indexOf("const sourceCollectionActionInitialDataPending = Boolean("),
      routeSource.indexOf("const sourceCollectionLoopActionLabel ="),
    );
    expect(readinessSource).toContain("sourceCollectionRecordsDataLoading");
    expect(readinessSource).toContain("sourceCollectionAssignmentsDataLoading");
    expect(readinessSource).toContain("sourceCollectionPrimaryDataLoading");
    expect(readinessSource).toContain("sourceCollectionSourceQualityLoading");
    expect(routeSource).toContain("teamWorkflowCandidateGraphQuery.isPending && !teamWorkflowCandidateGraphQuery.data");
    expect(routeSource).toContain("teamWorkflowKnowledgeIngestionStatusQuery.isPending && !teamWorkflowKnowledgeIngestionStatusQuery.data");
    expect(readinessSource).not.toContain("sourceCollectionSummaryQuery.isFetching");
    expect(readinessSource).not.toContain("sourceCollectionRecordsQuery.isFetching");
    expect(readinessSource).not.toContain("sourceCollectionAssignmentsQuery.isFetching");

    const launcherSource = routeSource.slice(
      routeSource.indexOf("function renderResearchStageLauncher"),
      routeSource.indexOf("function renderResearchStageStandalonePage"),
    );
    expect(launcherSource).toContain("sourceCollectionSearchActionReadiness.disabled");
    expect(launcherSource).toContain("disabled={sourceCollectionLoopActionDisabled}");
    expect(routeSource).toContain("const sourceCollectionLoopActionDisabled = sourceCollectionLoopActionReadiness.disabled");
    expect(routeSource).toContain("const sourceCollectionCompletionActionDisabled = sourceCollectionCompletionActionReadiness.disabled");
    expect(launcherSource).toContain("title={sourceCollectionActionDisabledTitle(sourceCollectionLoopActionReadiness, sourceCollectionLoopActionLabel)}");

    const stageModuleSource = routeSource.slice(
      routeSource.indexOf("const sourceCollectionStageModules"),
      routeSource.indexOf("const sourceCollectionBoardCurrentModule"),
    );
    expect(stageModuleSource).toContain('sourceCollectionStageActionReadinessFor("finding").disabled');
    expect(stageModuleSource).toContain('sourceCollectionStageActionReadinessFor("extraction").disabled');
    expect(stageModuleSource).toContain('sourceCollectionStageActionReadinessFor("relations").disabled');
    expect(stageModuleSource).toContain('sourceCollectionStageActionReadinessFor("ingestion").disabled');
    expect(stageModuleSource.match(/sourceCollectionStageActionLabelFor/g) ?? []).toHaveLength(4);
    expect(stageModuleSource).toContain('"finding", sourceCollectionCollectionActionLabel');
    expect(stageModuleSource).toContain('"extraction",');
    expect(stageModuleSource).toContain('"relations", sourceCollectionGraphActionLabel');
    expect(stageModuleSource).toContain('"ingestion", sourceCollectionMemoryActionLabel');
  });

  it("keeps source collection stage status stable while the selected run is still loading", () => {
    const stageRoundSource = routeSource.slice(
      routeSource.indexOf("const sourceCollectionSummaryStageRound = useMemo<ResearchStageRound | null>(() => {"),
      routeSource.indexOf("const experimentPlanningStatus = experimentPlanningStatusQuery.data ?? null;"),
    );
    expect(stageRoundSource).toContain("summaryRunId");
    expect(stageRoundSource).toContain("selectedSourceCollectionRunEffectiveId && summaryRunId && summaryRunId !== selectedSourceCollectionRunEffectiveId");
    expect(stageRoundSource).toContain("const matchingRound = rounds.find((round) => (round.sourceRunIds ?? []).includes(selectedSourceCollectionRunEffectiveId))");
    expect(stageRoundSource).toContain("return matchingRound ?? null");
    expect(stageRoundSource).not.toContain("?? rounds[0] ?? null");

    const candidateListLoadingSource = routeSource.slice(
      routeSource.indexOf("const sourceCollectionCandidateListDataLoading = Boolean("),
      routeSource.indexOf("const sourceCollectionPrimaryDataLoading = Boolean("),
    );
    expect(candidateListLoadingSource).toContain("teamWorkflowCandidateListEnabled");
    expect(candidateListLoadingSource).toContain("sourceCollectionNeedsCandidateList");
    expect(candidateListLoadingSource).toContain("!teamWorkflowCandidatesQuery.data");

    const sourceCollectionPrimaryLoadingSource = routeSource.slice(
      routeSource.indexOf("const sourceCollectionPrimaryDataLoading = Boolean("),
      routeSource.indexOf("const sourceCollectionSourceQualityLoading = Boolean("),
    );
    expect(sourceCollectionPrimaryLoadingSource).toContain("sourceCollectionCandidateListDataLoading");

    expect(routeSource).toContain("sourceCollectionDataSyncText");
    expect(routeSource).toContain("sourceCollectionStableCountText");
    expect(routeSource).toContain("loading={sourceCollectionPrimaryDataLoading}");

    const displayLoadingSource = routeSource.slice(
      routeSource.indexOf("const sourceCollectionFindingDisplayLoading"),
      routeSource.indexOf("const sourceCollectionStageModules"),
    );
    expect(displayLoadingSource).toContain("const sourceCollectionRelationsDisplayLoading = sourceCollectionGraphDataLoading");
    expect(displayLoadingSource).toContain("const sourceCollectionIngestionDisplayLoading = sourceCollectionSourceQualityLoading || sourceCollectionKnowledgeIngestionDataLoading");
    expect(displayLoadingSource).toContain("sourceCollectionCandidateSyncStatusText");
    expect(displayLoadingSource).not.toContain("sourceCollectionPrimaryDataLoading || sourceCollectionGraphDataLoading");
    expect(displayLoadingSource).not.toContain("sourceCollectionPrimaryDataLoading || sourceCollectionSourceQualityLoading || sourceCollectionKnowledgeIngestionDataLoading");

    const stageModuleSource = routeSource.slice(
      routeSource.indexOf("const sourceCollectionStageModules"),
      routeSource.indexOf("const sourceCollectionBoardCurrentModule"),
    );
    const extractionModuleSource = stageModuleSource.slice(
      stageModuleSource.indexOf('id: "extraction"'),
      stageModuleSource.indexOf('id: "relations"'),
    );
    expect(extractionModuleSource).toContain("sourceCollectionExtractionDisplayLoading");
    expect(extractionModuleSource).toContain('summary: sourceCollectionStageLaunchActive("extraction")');
    expect(extractionModuleSource.indexOf('summary: sourceCollectionStageLaunchActive("extraction")')).toBeLessThan(
      extractionModuleSource.indexOf("sourceCollectionExtractionDisplayLoading"),
    );
    expect(extractionModuleSource.indexOf("sourceCollectionExtractionDisplayLoading")).toBeLessThan(
      extractionModuleSource.indexOf("sourceCollectionStageUserSummary(sourceCollectionExtractionProjection, lang)"),
    );
    expect(extractionModuleSource).toContain('state: sourceCollectionStageDisplayState("extraction", sourceCollectionExtractionCanProceedAfterExclusions');
    expect(extractionModuleSource).toContain('status: sourceCollectionStageDisplayStatus(');
    expect(extractionModuleSource).toContain("sourceCollectionExtractionDisplayLoading");
    expect(extractionModuleSource).toContain("sourceCollectionCandidateSyncStatusText");
    expect(extractionModuleSource).toContain("sourceCollectionExtractionExcludedRecoveryState.statusLabel");
  });

  it("keeps the source collection workspace in a simple status-board mode", () => {
    const standaloneSource = routeSource.slice(
      routeSource.indexOf("if (sourceCollectionStandalone)"),
      routeSource.indexOf("if (stageStandaloneView)"),
    );
    expect(standaloneSource).toContain("sourceCollectionBoardNextStepLabel");
    expect(standaloneSource).not.toContain("{renderSourceCollectionControlsPanel()}");
    expect(routeSource).toContain("sourceCollectionFilterLoadingCount");
    expect(routeSource).toContain('filter === "all" ? sourceCollectionLoadingText : "..."');
    expect(routeSource).not.toContain("count: loading ? loadingValue");

    const commandStatsSource = standaloneSource.slice(
      standaloneSource.indexOf("<TeamSourceCollectionStandaloneStagePanel"),
      standaloneSource.indexOf("stagePipelineId=\"source-collection-stage-status\""),
    );
    expect(commandStatsSource).toContain("sourceCollectionConsoleStatusText");
    expect(commandStatsSource).toContain("sourceCollectionBoardNextStepLabel");
    expect(commandStatsSource).toContain("sourceCollectionCollectedCountLabel");
    expect(commandStatsSource).not.toContain("sourceCollectionSearchOpenAssignmentCountLabel");
    expect(commandStatsSource).not.toContain("sourceCollectionDownstreamOpenAssignmentCountLabel");
    expect(commandStatsSource).not.toContain("sourceCollectionQueryCountLabel");
    expect(commandStatsSource).not.toContain("sourceCollectionPromptCacheStatusLabel");

    const stageModuleViewModelSource = routeSource.slice(
      routeSource.indexOf("const sourceCollectionStandaloneStageModules"),
      routeSource.indexOf("const activeWorkflowItemCount"),
    );
    expect(stageModuleViewModelSource).toContain("tone: module.state");
    expect(stageModuleViewModelSource).toContain("status: module.status");
    expect(stageModuleViewModelSource).toContain("metric: module.metric");
    expect(stageModuleViewModelSource).toContain("nextLabel: `${lang === \"zh\" ? \"下一步：\" : \"Next: \"}${module.nextLabel}`");
    expect(stageModuleViewModelSource).toContain("sourceCollectionActionDisabledTitle(cardActionReadiness, module.actionLabel)");
    expect(stageModuleViewModelSource).not.toContain("summary: module.summary");
    expect(stageModuleViewModelSource).not.toContain("sourceCollectionStageProjectionTaskMetric");
    expect(stageModuleViewModelSource).not.toContain("sourceCollectionStageTechnicalDetails");

    const stageCardSource = teamSourceCollectionStandaloneStagePanelSource.slice(
      teamSourceCollectionStandaloneStagePanelSource.indexOf("<TeamStagePipeline"),
      teamSourceCollectionStandaloneStagePanelSource.indexOf("<div className={compactActivePanel"),
    );
    expect(stageCardSource).toContain("TeamStageCard");
    expect(stageCardSource).toContain("tone={module.tone}");
    expect(stageCardSource).toContain("module.status");
    expect(stageCardSource).toContain("module.metric");
    expect(stageCardSource).toContain("module.nextLabel");
    expect(stageCardSource).toContain("module.onAction");
    expect(stageCardSource).toContain("module.actionDisabled");
    expect(stageCardSource).toContain("module.actionTitle");

    const rawRecordSource = routeSource.slice(
      routeSource.indexOf("function renderSourceCollectionConversation"),
      routeSource.indexOf("function renderSourceCollectionStorageActions"),
    );
    expect(rawRecordSource).toContain("sourceCollectionSimpleRecordStatusLabel");
    expect(rawRecordSource).not.toContain("<p title={record.summary || record.recordId}>");
    expect(rawRecordSource).not.toContain("formatTime(record.updatedAt || record.createdAt");

    const candidatePanelSource = routeSource.slice(
      routeSource.indexOf("function renderSourceCollectionCandidatePanel"),
      routeSource.indexOf("function renderSourceCollectionGraphPanel"),
    );
    expect(candidatePanelSource).toContain("sourceCollectionSimpleCandidateStatusLabel");
    expect(candidatePanelSource).not.toContain("<p>{candidate.summary || candidate.candidateId}</p>");
    expect(candidatePanelSource).not.toContain("formatTime(candidate.updatedAt");
    expect(candidatePanelSource).not.toContain("sourceCollectionStageTechnicalDetails");
    expect(candidatePanelSource).not.toContain("candidateLatestTask?.summary");
    expect(candidatePanelSource).not.toContain("blockingReasons");
  });

  it("surfaces source extraction Evidence Ledger in cards, details, and relation mapping", () => {
    expect(routeSource).toContain("sourceCollectionEvidenceLedgerSummary");
    expect(evidenceModelSource).toContain("metadata.contentExtraction");
    expect(evidenceModelSource).toContain("extraction.evidenceLedger");
    expect(evidenceModelSource).toContain("Evidence Ledger ${summary.status}");
    expect(evidenceModelSource).toContain("evidence_ready");
    expect(evidenceModelSource).toContain("missing_evidence_anchor");
    expect(routeSource).toContain("sourceCollectionEvidenceReadyCandidateCount");
    expect(routeSource).toContain("sourceCollectionMissingEvidenceAnchorCount");

    const selectedSourceDetailSource = routeSource.slice(
      routeSource.indexOf("function renderSourceCollectionSelectedSourcePanel"),
      routeSource.indexOf("function renderSourceCollectionScreeningPanel"),
    );
    expect(selectedSourceDetailSource).toContain("sourceCollectionEvidenceLedgerDetailItems");
    expect(selectedSourceDetailSource).toContain("evidenceLedger={evidenceLedgerSummary");
    expect(teamSourceCollectionSourceDetailPanelSource).toContain("Evidence Ledger");
    expect(teamSourceCollectionSourceDetailPanelSource).toContain("evidenceLedger.map");

    const candidatePanelSource = routeSource.slice(
      routeSource.indexOf("function renderSourceCollectionCandidatePanel"),
      routeSource.indexOf("function renderSourceCollectionGraphPanel"),
    );
    expect(candidatePanelSource).toContain("sourceCollectionEvidenceLedgerCardLabel");
    expect(candidatePanelSource).toContain("sourceCollectionEvidenceLedgerTone");

    const graphPanelSource = routeSource.slice(
      routeSource.indexOf("function renderSourceCollectionGraphPanel"),
      routeSource.indexOf("function renderSourceCollectionMemoryPanel"),
    );
    expect(graphPanelSource).toContain("visibleGraphMissingEvidenceAnchorCount");
    expect(graphPanelSource).toContain("sourceCollectionEvidenceLedgerActionLabel");
    expect(graphPanelSource).toContain("待补证据");
  });

  it("keeps Team actions scoped to the selected Team or message event", () => {
    expect(routeSource).toContain("canvasSavePendingForTeam");
    expect(routeSource).toContain("saveCanvasMutation.variables?.teamId === teamId");
    expect(routeSource).toContain("selectedTeamSyncPending");
    expect(routeSource).toContain("syncTeamChatRoomMutation.variables === selectedTeam?.teamId");
    expect(routeSource).toContain("selectedTeamStartRoundPending");
    expect(routeSource).toContain("startTeamRoundMutation.variables?.teamId === selectedTeam?.teamId");
    expect(routeSource).toContain("selectedTeamMessagePending");
    expect(routeSource).toContain("sendTeamMessageMutation.variables?.teamId === selectedTeam?.teamId");
    expect(routeSource).toContain("revokeTeamMessageMutation.variables?.eventId === event.eventId");
    expect(routeSource).toContain("revokeTeamMessageMutation.mutate({ teamId: selectedTeam.teamId, eventId: event.eventId })");
    expect(routeSource).not.toContain("chatWorkspaceCache.afterTeamChanged(selectedTeamId || undefined)");
    expect(routeSource).not.toContain("revokeTeamMessageMutation.mutate(event.eventId)");
  });

  it("renders visible directional communication edges on the Team canvas", () => {
    expect(routeSource).toContain("<marker");
    expect(routeSource).toContain('id="team-edge-arrow"');
    expect(routeSource).toContain("key={edge.id}");
    expect(routeSource).toContain("Q ${line.cx} ${line.cy}");
    expect(routeSource).toContain("nodeBoundaryPoint");
    expect(routeSource).toContain("distanceToRectEdge");
    expect(routeSource).toContain("edgeLine(edge, displayCanvasNodes, visibleEdges)");
    expect(routeSource).toContain("sourceFanSpread");
    expect(routeSource).not.toContain("<line key={edge.id}");
    expect(routeSource).toContain("className={styles.edges}");
  });

  it("separates organization lines from information lines by default", () => {
    expect(routeSource).toContain("showCommunicationEdges");
    expect(routeSource).toContain("isCommunicationEdge(edge)");
    expect(routeSource).toContain("organizationEdges");
    expect(routeSource).toContain("communicationEdges");
    expect(routeSource).toContain("visibleCommunicationEdges");
    expect(routeSource).toContain("visibleCommunicationEdgeCount");
    expect(routeSource).toContain("visibleEdges");
    expect(routeSource).toContain("edge.type === \"communication\"");
    expect(routeSource).toContain("edge.type === \"collaborates_with\"");
    expect(routeSource).toContain("styles.edgeOrganization");
    expect(routeSource).toContain("styles.edgeCommunication");
    expect(routeSource).toContain("信息线");
    expect(routeSource).toContain("信息线已收起（");
    expect(routeSource).toContain("展开信息线");
    expect(routeSource).toContain("暂无信息线");
    expect(routeSource).toContain("没有可展开的信息线");
    expect(routeSource).toContain("收起信息线");
    expect(routeSource).toContain("Info");
    expect(routeSource).toContain('type: "reports_to"');
    expect(routeSource).not.toContain("canvas?.edges.map((edge)");
  });

  it("centers compact Team canvases and renders function role badges", () => {
    expect(routeSource).toContain("canvasViewStyle");
    expect(routeSource).toContain("type TeamsRouteDynamicStyle");
    expect(routeSource).toContain("CANVAS_VIEWPORT_WIDTH");
    expect(routeSource).toContain("CANVAS_VIEWPORT_HEIGHT");
    expect(routeSource).toContain("canvasViewportStyle");
    expect(routeSource).toContain("lockedCanvasViewportStyle");
    expect(routeSource).toContain("setLockedCanvasViewportStyle(canvasViewportStyle)");
    expect(routeSource).toContain("canvasFrameSize");
    expect(routeSource).toContain("canvasViewStyle(displayCanvasNodes, canvasFrameSize)");
    expect(routeSource).toContain("ResizeObserver");
    expect(routeSource).toContain("styles.canvasViewport");
    expect(routeSource).toContain("--canvas-offset-x");
    expect(routeSource).toContain("--canvas-scale");
    expect(routeSource).toContain("--node-x");
    expect(routeSource).toContain("teamCanvasNodeStyle(node)");
    expect(routeSource).toContain("roleBadgeTone");
    expect(routeSource).toContain("teamNodeFunctionLabel");
    expect(routeSource).toContain("能力管家");
    expect(routeSource).toContain("styles.nodeRoleBadge");
    expect(routeSource).toContain("styles.nodeRoleBadgeLead");
    expect(routeSource).toContain("styles.nodeRoleBadgeAdvisor");
    expect(routeSource).toContain("styles.nodeRoleBadgeSteward");
    expect(routeStyles.canvasViewport).toContain("h-[760px]");
    expect(routeStyles.canvasViewport).toContain("w-[1180px]");
    expect(routeStyles.canvasViewport).toContain("[transform:scale(var(--canvas-scale,1))]");
    expect(routeStyles.edges).toContain("absolute");
    expect(routeStyles.edges).toContain("[transform:translate(var(--canvas-offset-x,0px),var(--canvas-offset-y,0px))]");
    expect(routeStyles.node).toContain("!absolute");
    expect(routeStyles.node).toContain("left-[calc(var(--canvas-offset-x,0px)+var(--node-x,0px))]");
    expect(routeStyles.node).toContain("top-[calc(var(--canvas-offset-y,0px)+var(--node-y,0px))]");
  });

  it("keeps Teams dynamic layout values behind typed CSS variable helpers", () => {
    expect(routeSource).toContain("TeamWorkflowGraphView");
    expect(routeSource.match(/<TeamWorkflowGraphView/g)?.length ?? 0).toBe(1);
    expect(teamWorkflowStatusPanelsSource.match(/<TeamWorkflowGraphView/g)?.length ?? 0).toBe(1);
    expect(routeSource).not.toContain("workflowGraphFrameStyle(visibleGraphLayout)");
    expect(routeSource).not.toContain("workflowGraphFrameStyle(teamWorkflowCandidateGraphLayout)");
    expect(routeSource).not.toContain("className={styles.workflowGraphSvg}");
    expect(workflowGraphViewSource).toContain("workflowGraphFrameStyle(layout)");
    expect(workflowGraphViewSource).toContain("workflowGraphNodeStyle(node)");
    expect(workflowGraphViewSource).toContain("className={styles.workflowGraphSvg}");
    expect(routeSource).toContain("teamCanvasNodeStyle(node)");
    expect(routeSource).not.toContain("style={{");
    expect(workflowGraphViewSource).not.toContain("style={{");
    expect(workflowGraphViewStyles.workflowGraphFrame).toContain("min-h-[var(--workflow-graph-height");
    expect(workflowGraphViewStyles.workflowGraphFrame).toContain("w-[var(--workflow-graph-width");
    expect(workflowGraphViewStyles.workflowGraphCanvas).toContain("relative");
    expect(workflowGraphViewStyles.workflowGraphSvg).toContain("h-full");
    expect(workflowGraphViewStyles.workflowGraphSvg).toContain("w-full");
    expect(workflowGraphViewStyles.workflowGraphNode).toContain("absolute");
    expect(workflowGraphViewStyles.workflowGraphNode).toContain("left-[var(--workflow-graph-node-x");
    expect(workflowGraphViewStyles.workflowGraphNode).toContain("top-[var(--workflow-graph-node-y");
  });

  it("keeps read-only research canvas auto layout visual-only and deterministic", () => {
    expect(routeSource).toContain("function autoLayoutResearchCanvasNodes");
    expect(routeSource).toContain("researchCanvasRoleLayer");
    expect(routeSource).toContain("RESEARCH_CANVAS_AUTO_LAYOUT_LAYER_GAP");
    expect(routeSource).toContain("RESEARCH_CANVAS_AUTO_LAYOUT_ROW_GAP");
    expect(routeSource).toContain("teamCanvasNodeSortKey");
    expect(routeSource).toContain("positions.set(node.id");
    expect(routeSource).toContain("return nodes.map((node) => ({");
    expect(routeSource).toContain("displayCanvasNodes.map((node)");
    expect(routeSource).not.toContain("saveCanvas(autoLayoutCanvasNodes");
    expect(routeSource).not.toContain("saveCanvas(displayCanvasNodes");
    expect(routeStyles.canvasLayoutModeSwitch).toBeTypeOf("string");
  });

  it("lets users drag canvas nodes and persist their positions", () => {
    expect(routeSource).toContain("nodePositionDrafts");
    expect(routeSource).toContain("dragStateRef");
    expect(routeSource).toContain("dragFrameRef");
    expect(routeSource).toContain("startNodeDrag");
    expect(routeSource).toContain("moveNodeDrag");
    expect(routeSource).toContain("finishNodeDrag");
    expect(routeSource).toContain("requestNodeDragFrame");
    expect(routeSource).toContain("window.requestAnimationFrame");
    expect(routeSource).toContain("window.cancelAnimationFrame");
    expect(routeSource).toContain("commitNodeDragPosition(dragState)");
    expect(routeSource).toContain("setPointerCapture(event.pointerId)");
    expect(routeSource).toContain("releasePointerCapture(event.pointerId)");
    expect(routeSource).toContain("nodes: durableCanvas.nodes.map((node) => (node.id === dragState.nodeId");
    expect(routeSource).toContain("onPointerDown={researchCanvasReadOnly ? undefined : (event) => startNodeDrag(event, node)}");
    expect(routeSource).toContain("onPointerMove={researchCanvasReadOnly ? undefined : moveNodeDrag}");
    expect(routeSource).toContain("onPointerUp={researchCanvasReadOnly ? undefined : finishNodeDrag}");
    expect(routeSource).toContain("edgeLine(edge, displayCanvasNodes, visibleEdges)");
  });

  it("keeps Team detail loading inside the workspace shell during cold loading", () => {
    expect(routeSource).toContain("const selectedTeamReference = visibleTeams.find((team) => team.teamId === effectiveTeamId) ?? null");
    expect(routeSource).toContain("const selectedTeamDetailLoading = Boolean(");
    expect(routeSource).toContain("const researchTeamDetailDegraded = Boolean(");
    expect(routeSource).toContain("selectedTeamDetailLoading && !researchWorkflowTeamSelected");
    expect(routeSource).toContain("selectedTeamDetailUnavailable && !researchWorkflowTeamSelected");
    expect(routeSource).toContain("researchStageDegradedNotice");
    expect(routeSource).toContain("团队详情暂时不可用；当前保留已读取的科研状态。");
    expect(routeSource).toContain("const agentDirectoryHydrating = bindings.some(");
    expect(routeSource).toContain("正在读取成员配置");
    expect(routeSource).toContain("状态同步中");
    expect(routeSource).toContain("状态暂不可用");
    expect(routeSource).toContain("const showTeamLoadingSurface =");
    expect(routeSource).toContain("const showTeamDetailUnavailableSurface =");
    expect(routeSource).toContain("VStateSurface");
    expect(routeStyles.teamLoadingInlineSurface).toBeTypeOf("string");
    expect(routeStyles.teamLoadingInlineSurface).toContain("min-h-[96px]");

    const mainRenderSource = routeSource.slice(
      routeSource.indexOf("showTeamUnavailableSurface ? ("),
      routeSource.indexOf("className={canvasPanelClassName}"),
    );
    expect(mainRenderSource).not.toContain("showTeamLoadingSurface ? (");
    expect(mainRenderSource).toContain("showTeamDetailUnavailableSurface ? (");
    expect(mainRenderSource.indexOf("showTeamDetailUnavailableSurface ? (")).toBeLessThan(
      mainRenderSource.indexOf("<div className={workspaceClassName}>"),
    );
    expect(routeSource).toContain("teamWorkspaceLoadingTitle");
    expect(routeSource).toContain("className={styles.teamLoadingInlineSurface}");
    expect(routeSource.indexOf("className={styles.teamLoadingInlineSurface}")).toBeGreaterThan(
      routeSource.indexOf("<div className={workspaceClassName}>"),
    );

    const standaloneSource = routeSource.slice(
      routeSource.indexOf("if (sourceCollectionStandalone)"),
      routeSource.indexOf("if (stageStandaloneView)"),
    );
    expect(standaloneSource).toContain("researchWorkflowTeamSelected && !showTeamDetailUnavailableSurface ? (");
    expect(standaloneSource).toContain("teamWorkspaceLoadingTitle");
    expect(standaloneSource).not.toContain("researchWorkflowTeamSelected && !showTeamLoadingSurface && !showTeamDetailUnavailableSurface ? (");
  });

  it("routes the source collection ingestion step to the single source ingestion Agent", () => {
    expect(routeSource).toContain('ingestion: ["source_ingestor"]');
    expect(routeSource).toContain("资料入库");
    expect(routeSource).toContain("资料入库 Agent 私聊");
    expect(routeSource).toContain("sourceCollectionIngestorAgentId");
    expect(routeSource).not.toContain("知识库管理员入库审核");
    expect(routeSource).not.toContain("共享记忆前审");
    expect(routeSource).not.toContain('ingestion: ["source_ingestor", "source_relation_mapper"]');
  });

  it("shows only the selected run's close gate and lets users locate its unfinished stage", () => {
    expect(stageProjectionSource).toContain("sourceCollectionPhaseCloseGateForRun");
    expect(stageProjectionSource).toContain('scope.kind !== "source_run"');
    expect(stageProjectionSource).toContain("scope.includesHistorical === true");
    expect(routeSource).toContain("const sourceCollectionPhaseCloseGate = sourceCollectionPhaseCloseGateForRun(");
    expect(routeSource).toContain("<TeamSourceCollectionPhaseCloseGatePanel");
    expect(routeSource).toContain("onOpenStage={selectSourceCollectionStage}");
    expect(teamSourceCollectionStandaloneStagePanelSource).toContain("phaseCloseGate?: ReactNode");
    expect(teamSourceCollectionStandaloneStagePanelSource).toContain("styles.sourceCollectionRunContext");
    expect(teamSourceCollectionOverviewPanelSource).toContain("phaseCloseGate?: ReactNode");
    expect(teamSourceCollectionOverviewPanelSource).toContain("{phaseCloseGate}");
    expect(teamSourceCollectionPhaseCloseGatePanelSource).toContain('data-vui-product="source-collection-phase-close-gate"');
    expect(teamSourceCollectionPhaseCloseGatePanelSource).toContain("不会用全局历史统计替代");
    expect(teamSourceCollectionPhaseCloseGatePanelSource).toContain("onOpenStage(nextStage)");
    expect(teamSourceCollectionPhaseCloseGatePanelStyles.phaseCloseGateAction).toContain("w-fit");
    expect(teamSourceCollectionPhaseCloseGatePanelStyles.phaseCloseGateHeader).toContain("max-[640px]");
  });
});
