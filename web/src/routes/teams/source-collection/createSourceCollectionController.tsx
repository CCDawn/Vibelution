/**
 * Clarity P5 / F1 — Source-collection domain controller.
 * Owns stage advance handler, inject factory, and standalone workbench render.
 */
import type { ReactNode } from "react";

import { RESEARCH_STAGE_TERMS } from "../research-workflow/researchTerminology";
import { createSourceCollectionInjectRenderers } from "../teamSourceCollectionInjectRenderers";
import { SourceCollectionComposer } from "../SourceCollectionComposer";
import { SourceCollectionPresentationProvider } from "./SourceCollectionPresentationContext";
import {
  preflightSourceCollectionStageAdvance,
  sourceCollectionStageAdvanceFailureTitle,
} from "./stageAdvancePreflight";
import {
  sourceCollectionPhaseCloseGateNextStage,
  type SourceCollectionStageModuleId,
} from "./stageProjection";
import type { ResearchStageRoundStartPayload } from "../workflowStartMutationModel";
import type { ResearchWorkspaceView } from "../researchWorkspaceModel";
import type { ResearchStageUnlock } from "../researchPrimaryActionModel";
import { isChallengeCupResearchWorkflowTeam } from "../teamKindModel";
import { researchStageAgentManagementRoute } from "../researchStageAgentPresentation";
import {
  compactSourceCollectionQuerySeeds,
  splitDraftList,
} from "./presentationModel";
import { sourceCollectionRunTitleLabel } from "./runModel";

export type SourceCollectionControllerContext = {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [key: string]: any;
};

export function createSourceCollectionStageAdvance(ctx: SourceCollectionControllerContext) {
  const {
    lang, navigate, selectedTeam, selectedSourceCollectionRunEffectiveId,
    startSourceCollectionStageSessionTaskMutation, resetResearchProjectSourceCollectionMutation,
    setSourceCollectionStageAdvanceFailure, teamWorkflowKnowledgeIngestionStatus,
    sourceCollectionProjectedCollectedCount, sourceCollectionCollectedCount,
    sourceCollectionProjectedApprovedCount, sourceCollectionRunApprovedCount,
    sourceCollectionDisplayedCandidateCount, teamWorkflowCandidateGraph,
    candidateGraphNodeCount, sourceCollectionProjectedGraphNodeCount,
    candidateGraphEdgeCount, sourceCollectionProjectedGraphEdgeCount,
    sourceCollectionFindingDisplayState, sourceCollectionExtractionDisplayState,
    sourceCollectionRelationsDisplayState, sourceCollectionStageActionReadinessFor,
    openSourceCollectionStage, sourceCollectionStageAgentChatState,
    repairSelectedWorkflowTeamAgentsIfNeeded, knowledgeExpansionWorkflowTeamSelected,
    sourceCollectionCanStart, selectedTeamStartSourceCollectionPending,
    startSourceCollectionRunMutation, sourceCollectionDraft, researchStageCanLaunch,
    selectedTeamStartResearchStagePending, startResearchStageRoundMutation,
    sourceCollectionStageReturnRoute, sourceCollectionStageChatReturnLabel,
    sourceCollectionOwnerAgentId, sourceCollectionStageTaskClickKey,
    sourceCollectionStageFormalRetryRequired,
  } = ctx;

  return async function startSourceCollectionStageSessionTask(
    stageId: SourceCollectionStageModuleId,
    options: { formalRetry?: boolean } = {},
  ) {
    if (!selectedTeam?.teamId || startSourceCollectionStageSessionTaskMutation.isPending || resetResearchProjectSourceCollectionMutation.isPending) {
      setSourceCollectionStageAdvanceFailure(lang === "zh"
        ? `${sourceCollectionStageAdvanceFailureTitle("zh")}：系统忙或未选择团队，推进未启动。`
        : `${sourceCollectionStageAdvanceFailureTitle("en")}: system busy or no team selected.`);
      return;
    }
    const initialChatState = sourceCollectionStageAgentChatState(stageId);
    const initialBinding = initialChatState.binding;
    const initialAgentId = String(initialBinding?.agent?.agentId || "").trim();
    const initialBoundAgentId = String(initialBinding?.agentId || "").trim();
    if (
      isChallengeCupResearchWorkflowTeam(selectedTeam)
      && !initialAgentId
      && initialChatState.status !== "loading"
    ) {
      navigate(
        initialBoundAgentId
          ? researchStageAgentManagementRoute(initialBoundAgentId)
          : "/agents?pane=config",
      );
      return;
    }
    const knowledgeActionItemCodes = (teamWorkflowKnowledgeIngestionStatus?.actionItems || [])
      .map((item: { code?: string }) => String(item?.code || "").trim()).filter(Boolean);
    const preflight = preflightSourceCollectionStageAdvance({
      stageId,
      hasRun: Boolean(selectedSourceCollectionRunEffectiveId),
      rawRecordCount: Number(sourceCollectionProjectedCollectedCount || sourceCollectionCollectedCount || 0),
      approvedCandidateCount: Number(sourceCollectionProjectedApprovedCount || sourceCollectionRunApprovedCount || 0),
      displayedCandidateCount: Number(sourceCollectionDisplayedCandidateCount || 0),
      graphNodeCount: Number(teamWorkflowCandidateGraph?.summary?.nodeCount ?? candidateGraphNodeCount ?? sourceCollectionProjectedGraphNodeCount ?? 0),
      graphEdgeCount: Number(teamWorkflowCandidateGraph?.summary?.edgeCount ?? candidateGraphEdgeCount ?? sourceCollectionProjectedGraphEdgeCount ?? 0),
      graphMissingLinkCount: Number(teamWorkflowCandidateGraph?.summary?.missingLinkCount ?? teamWorkflowCandidateGraph?.missingLinks?.length ?? teamWorkflowKnowledgeIngestionStatus?.summary?.missingLinkCount ?? 0),
      knowledgeActionItemCodes,
      findingState: sourceCollectionFindingDisplayState,
      extractionState: sourceCollectionExtractionDisplayState,
      relationsState: sourceCollectionRelationsDisplayState,
    });
    if (!preflight.ok) {
      setSourceCollectionStageAdvanceFailure(lang === "zh" ? preflight.reasonZh : preflight.reasonEn);
      openSourceCollectionStage(preflight.redirectStageId);
      return;
    }
    const actionReadiness = sourceCollectionStageActionReadinessFor(stageId);
    if (actionReadiness.disabled) {
      setSourceCollectionStageAdvanceFailure(lang === "zh"
        ? `${sourceCollectionStageAdvanceFailureTitle("zh")}：${actionReadiness.reason || "当前阶段操作不可用"}`
        : `${sourceCollectionStageAdvanceFailureTitle("en")}: ${actionReadiness.reason || "stage action unavailable"}`);
      return;
    }
    openSourceCollectionStage(stageId);
    const chatState = sourceCollectionStageAgentChatState(stageId);
    const binding = chatState.binding;
    const agentId = String(binding?.agent?.agentId || "").trim();
    const boundAgentId = String(binding?.agentId || "").trim();
    const agentRole = String(binding?.key || "").trim();
    if (!agentId) {
      if (isChallengeCupResearchWorkflowTeam(selectedTeam)) {
        navigate(
          boundAgentId
            ? researchStageAgentManagementRoute(boundAgentId)
            : "/agents?pane=config",
        );
        return;
      }
      setSourceCollectionStageAdvanceFailure(lang === "zh"
        ? `${sourceCollectionStageAdvanceFailureTitle("zh")}：缺少阶段 Agent，请配置对应 Agent。`
        : `${sourceCollectionStageAdvanceFailureTitle("en")}: stage Agent missing; configure the Agent.`);
      if (chatState.status === "repair") repairSelectedWorkflowTeamAgentsIfNeeded();
      return;
    }
    let runId = selectedSourceCollectionRunEffectiveId;
    if (!runId && stageId === "finding") {
      if (knowledgeExpansionWorkflowTeamSelected) {
        if (!sourceCollectionCanStart || selectedTeamStartSourceCollectionPending) {
          setSourceCollectionStageAdvanceFailure(lang === "zh"
            ? `${sourceCollectionStageAdvanceFailureTitle("zh")}：无法创建资料批次。`
            : `${sourceCollectionStageAdvanceFailureTitle("en")}: cannot create a source-collection run.`);
          return;
        }
        try {
          const runPayload = await startSourceCollectionRunMutation.mutateAsync({ teamId: selectedTeam.teamId, draft: sourceCollectionDraft });
          runId = runPayload.run.runId;
        } catch (error) {
          setSourceCollectionStageAdvanceFailure(lang === "zh"
            ? `${sourceCollectionStageAdvanceFailureTitle("zh")}：${error instanceof Error ? error.message : "创建批次失败"}`
            : `${sourceCollectionStageAdvanceFailureTitle("en")}: ${error instanceof Error ? error.message : "failed to create run"}`);
          return;
        }
      } else {
        if (!researchStageCanLaunch || selectedTeamStartResearchStagePending) {
          setSourceCollectionStageAdvanceFailure(lang === "zh"
            ? `${sourceCollectionStageAdvanceFailureTitle("zh")}：科研阶段无法启动。`
            : `${sourceCollectionStageAdvanceFailureTitle("en")}: research stage cannot launch.`);
          return;
        }
        try {
          const stagePayload: ResearchStageRoundStartPayload = await startResearchStageRoundMutation.mutateAsync({
            teamId: selectedTeam.teamId, stageType: "knowledge_collection", draft: sourceCollectionDraft,
          });
          runId = stagePayload.run?.runId || stagePayload.stageRound.sourceRunIds?.[0] || "";
        } catch (error) {
          setSourceCollectionStageAdvanceFailure(lang === "zh"
            ? `${sourceCollectionStageAdvanceFailureTitle("zh")}：${error instanceof Error ? error.message : "启动失败"}`
            : `${sourceCollectionStageAdvanceFailureTitle("en")}: ${error instanceof Error ? error.message : "start failed"}`);
          return;
        }
      }
    }
    if (!runId) {
      setSourceCollectionStageAdvanceFailure(lang === "zh"
        ? `${sourceCollectionStageAdvanceFailureTitle("zh")}：没有可用资料批次。`
        : `${sourceCollectionStageAdvanceFailureTitle("en")}: no source-collection run available.`);
      return;
    }
    try {
      setSourceCollectionStageAdvanceFailure("");
      const payload = await startSourceCollectionStageSessionTaskMutation.mutateAsync({
        teamId: selectedTeam.teamId, runId, stageId, agentId, agentRole,
        returnTo: sourceCollectionStageReturnRoute(stageId),
        returnLabel: sourceCollectionStageChatReturnLabel(stageId),
        requestedByAgent: sourceCollectionOwnerAgentId,
        idempotencyKey: sourceCollectionStageTaskClickKey(stageId),
        formalRetry: options.formalRetry ?? sourceCollectionStageFormalRetryRequired(stageId),
      });
      if (payload.chatRoute) { navigate(payload.chatRoute); return; }
      setSourceCollectionStageAdvanceFailure(lang === "zh"
        ? `${sourceCollectionStageAdvanceFailureTitle("zh")}：已创建任务但没有会话路由，阶段未真正推进。`
        : `${sourceCollectionStageAdvanceFailureTitle("en")}: task created without chat route; stage did not advance.`);
    } catch (error) {
      setSourceCollectionStageAdvanceFailure(lang === "zh"
        ? `${sourceCollectionStageAdvanceFailureTitle("zh")}：${error instanceof Error ? error.message : "启动阶段任务失败"}`
        : `${sourceCollectionStageAdvanceFailureTitle("en")}: ${error instanceof Error ? error.message : "failed to start stage task"}`);
    }
  };
}

export type SourceCollectionStandaloneChrome = {
  researchStageUnlock: ResearchStageUnlock;
  /** Full research workspace switcher (includes overview). */
  selectResearchWorkspaceView: (view: ResearchWorkspaceView) => void;
  linkedChatRoomId?: string;
  syncTeamChatRoomMutation: { mutate: (teamId: string) => void };
  selectedTeamSyncPending: boolean;
  activeTeamMemberCount: number;
  sourceCollectionRunsQuery: { refetch: () => unknown; isFetching: boolean };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  styles: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionStepClassName: (state: any) => string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionConsoleState: any;
  sourceCollectionConsoleStatusText: string;
  researchWorkflowTeamSelected: boolean;
  showTeamDetailUnavailableSurface: boolean;
  showTeamLoadingSurface: boolean;
  teamWorkspaceLoadingTitle: ReactNode;
  teamWorkspaceLoadingMessage: ReactNode;
  teamWorkspaceUnavailableTitle: ReactNode;
  teamWorkspaceUnavailableDetail?: ReactNode;
  teamWorkspaceUnavailableMessage: ReactNode;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  teamDetailQuery: any;
  sourceCollectionSelectedRunTopic: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  selectedSourceCollectionRun: any;
  sourceCollectionSelectedRunQueryCount: number;
  sourceCollectionBoardNextStepLabel: string;
  sourceCollectionCollectedCountLabel: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionPhaseCloseGate: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionSummaryQuery: any;
  selectSourceCollectionStage: (stageId: SourceCollectionStageModuleId) => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionStandaloneStageModules: any[];
  sourceCollectionFindingStageCompact: boolean;
};

export function createSourceCollectionController(ctx: SourceCollectionControllerContext) {
  const {
    lang, selectedTeam, selectedSourceCollectionRunEffectiveId, sourceCollectionDraft,
    startSourceCollectionStageSessionTask,
  } = ctx;

  const inject = createSourceCollectionInjectRenderers({
    ...ctx,
    startSourceCollectionStageSessionTask,
  });

  function renderStandalonePage(chrome: SourceCollectionStandaloneChrome): ReactNode {
    // R2-q: provide presentation bag so inject panels can opt into context over prop spray.
    const presentationValue = ctx as import("../useSourceCollectionPresentationCore").SourceCollectionPresentationApi;
    return (
      <SourceCollectionPresentationProvider value={presentationValue}>
        <SourceCollectionComposer
          lang={lang}
          unlock={chrome.researchStageUnlock}
          onSelectStage={(view) => chrome.selectResearchWorkspaceView(view)}
          onOverview={() => chrome.selectResearchWorkspaceView("overview")}
          teamId={selectedTeam?.teamId}
          linkedChatRoomId={chrome.linkedChatRoomId}
          onSyncChat={
            selectedTeam?.teamId
              ? () => chrome.syncTeamChatRoomMutation.mutate(selectedTeam.teamId)
              : undefined
          }
          chatSyncPending={chrome.selectedTeamSyncPending}
          chatSyncDisabled={!selectedTeam || chrome.activeTeamMemberCount === 0}
          onRefresh={() => void chrome.sourceCollectionRunsQuery.refetch()}
          refreshDisabled={chrome.sourceCollectionRunsQuery.isFetching}
          statusBadge={chrome.sourceCollectionConsoleStatusText}
          statusBadgeClassName={`${chrome.styles.sourceCollectionRunBadge} ${chrome.sourceCollectionStepClassName(chrome.sourceCollectionConsoleState)}`}
          ready={chrome.researchWorkflowTeamSelected && !chrome.showTeamDetailUnavailableSurface}
          loadingTitle={chrome.showTeamLoadingSurface ? chrome.teamWorkspaceLoadingTitle : undefined}
          loadingMessage={chrome.showTeamLoadingSurface ? chrome.teamWorkspaceLoadingMessage : undefined}
          unavailableTitle={
            chrome.showTeamDetailUnavailableSurface
              ? chrome.teamWorkspaceUnavailableTitle
              : (lang === "zh" ? "正在读取 挑战杯ai科研团队" : "Loading Challenge Cup AI research team")
          }
          unavailableDetail={
            chrome.showTeamDetailUnavailableSurface
              ? (chrome.teamWorkspaceUnavailableDetail || chrome.teamWorkspaceUnavailableMessage)
              : chrome.teamDetailQuery.error instanceof Error
                ? chrome.teamDetailQuery.error.message
                : (lang === "zh"
                  ? "这个一级页只绑定 research-team，不会展示给普通团队。"
                  : "This workspace is bound to research-team and is hidden from ordinary teams.")
          }
          commandAriaLabel={lang === "zh" ? `${RESEARCH_STAGE_TERMS.knowledge_collection.zh}操作台` : "Knowledge collection command bar"}
          commandTone={chrome.sourceCollectionConsoleState}
          commandTitle={
            chrome.sourceCollectionSelectedRunTopic
            || sourceCollectionDraft.topic.trim()
            || sourceCollectionRunTitleLabel(
              chrome.selectedSourceCollectionRun?.title || sourceCollectionDraft.title,
              lang,
            )
          }
          commandSubtitle={
            lang === "zh"
              ? `${chrome.sourceCollectionSelectedRunQueryCount || compactSourceCollectionQuerySeeds(sourceCollectionDraft.topic, sourceCollectionDraft.querySeeds).length} 个搜索问题 · ${splitDraftList(sourceCollectionDraft.searchLanguages, 8).length || 1} 种语言 · ${splitDraftList(sourceCollectionDraft.sourceTypes, 12).length || 1} 类来源`
              : `${chrome.sourceCollectionSelectedRunQueryCount || compactSourceCollectionQuerySeeds(sourceCollectionDraft.topic, sourceCollectionDraft.querySeeds).length} queries · ${splitDraftList(sourceCollectionDraft.searchLanguages, 8).length || 1} languages · ${splitDraftList(sourceCollectionDraft.sourceTypes, 12).length || 1} source types`
          }
          commandStats={(() => {
            const gate = chrome.sourceCollectionPhaseCloseGate;
            const stageCount = typeof gate?.stageCount === "number" && gate.stageCount > 0
              ? gate.stageCount
              : (gate?.stages?.length || 4);
            const closedLoopCount = typeof gate?.closedLoopCount === "number" ? gate.closedLoopCount : 0;
            const nextStageId = sourceCollectionPhaseCloseGateNextStage(gate);
            const selectedModule = (chrome.sourceCollectionStandaloneStageModules || []).find(
              (module: { selected?: boolean }) => module.selected,
            );
            const goNext = () => {
              if (selectedModule && !selectedModule.actionDisabled && typeof selectedModule.onAction === "function") {
                selectedModule.onAction();
                return;
              }
              if (nextStageId) {
                chrome.selectSourceCollectionStage(nextStageId);
              }
            };
            return [
              {
                key: "status",
                label: lang === "zh" ? "当前" : "status",
                value: chrome.sourceCollectionConsoleStatusText,
              },
              {
                key: "progress",
                label: lang === "zh" ? "进度" : "progress",
                value: gate ? `${closedLoopCount}/${stageCount}` : `0/${stageCount}`,
                title: lang === "zh" ? "阶段闭环进度" : "Stage close progress",
              },
              {
                key: "next",
                label: lang === "zh" ? "下一步" : "next",
                value: chrome.sourceCollectionBoardNextStepLabel,
                emphasis: "accent" as const,
                title: lang === "zh" ? "点击进入下一步" : "Open next step",
                onClick: goNext,
              },
              {
                key: "sources",
                label: lang === "zh" ? "资料" : "sources",
                value: chrome.sourceCollectionCollectedCountLabel,
              },
            ];
          })()}
          searchBrief={inject.renderSourceCollectionSearchBrief()}
          runSwitcher={inject.renderSourceCollectionRunSwitcher()}
          runHistoryLabel={lang === "zh" ? "切换历史批次" : "Switch historical run"}
          // Progress is unified into the top command bar (steps + stats); do not re-render left rail.
          phaseCloseGate={null}
          progressPlacement="command-bar"
          modules={chrome.sourceCollectionStandaloneStageModules}
          activePanel={inject.renderSourceCollectionActiveStagePanel()}
          compactActivePanel={chrome.sourceCollectionFindingStageCompact}
        />
      </SourceCollectionPresentationProvider>
    );
  }

  return {
    ...inject,
    startSourceCollectionStageSessionTask,
    renderStandalonePage,
  };
}
