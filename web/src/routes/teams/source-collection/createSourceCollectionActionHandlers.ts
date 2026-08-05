/**
 * F3 — SC mutation action handlers (run/open/select/scroll/*).
 * Pure factory: no React hooks; presentation hook only wires deps.
 */
import type { KeyboardEvent as ReactKeyboardEvent, MutableRefObject, RefObject } from "react";
import type { NavigateFunction, SetURLSearchParams } from "react-router-dom";
import type { UseMutationResult } from "@tanstack/react-query";

import type { Team, TeamWorkflowCandidate } from "../../../api/types";
import type { SourceCollectionDraft } from "./presentationModel";
import {
  SOURCE_COLLECTION_SEARCH_EXECUTION_ROLES,
  type SourceCollectionStorageOpenTarget,
} from "./presentationModel";
import type { SourceCollectionActionReadiness, SourceCollectionStageModuleId } from "./stageProjection";
import type { SourceCollectionStepState } from "./runModel";
import type { SourceCollectionStageCardProjection } from "./stageProjection";
import {
  sourceCollectionStageDisplayState as sourceCollectionStageDisplayStatePure,
  sourceCollectionStageDisplayStatus as sourceCollectionStageDisplayStatusPure,
  sourceCollectionStageDisplaySummary as sourceCollectionStageDisplaySummaryPure,
  sourceCollectionStageLaunchActive as sourceCollectionStageLaunchActivePure,
  sourceCollectionStageLaunchSummary as sourceCollectionStageLaunchSummaryPure,
} from "../teamSourceCollectionShellModel";
import { sourceCollectionStageUserStatusLabel } from "./stageProjection";
import type { ResearchWorkspaceView } from "../researchWorkspaceModel";
import { sourceCollectionActionReadinessOf } from "./actionChrome";

export type SourceCollectionActionHandlersContext = {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [key: string]: any;
};

export function createSourceCollectionActionHandlers(ctx: SourceCollectionActionHandlersContext) {
  const {
    lang,
    selectedTeam,
    selectedSourceCollectionRunEffectiveId,
    openSourceCollectionStorageMutation,
    setSelectedSourceCollectionCandidateId,
    setSelectedSourceCollectionStageId,
    sourceCollectionStandalone,
    searchParams,
    setSearchParams,
    setSourceCollectionFocusedPanelId,
    setSourceCollectionExpandedPanelId,
    sourceCollectionControlPanelRef,
    scrollSourceCollectionPanelIntoViewRef,
    sourceCollectionScreeningDisabled,
    sourceCollectionScreeningActionReadiness,
    sourceCollectionRunPendingScreeningCount,
    sourceCollectionDisplayedCandidateCount,
    assessSourceQualityBatchMutation,
    sourceCollectionExtractorAgentId,
    selectedTeamSourceQualityPending,
    sourceCollectionUnverifiableCandidateIds,
    assessSourceQualityMutation,
    sourceCollectionCandidateExtractionActionReadiness,
    extractSourceCollectionCandidatesMutation,
    sourceCollectionPendingCandidateImportCount,
    sourceCollectionRawRecordCount,
    sourceCollectionGraphActionReadiness,
    buildCandidateGraphMutation,
    sourceCollectionRelationMapperAgentId,
    sourceCollectionIngestCandidateCount,
    sourceCollectionRunApprovedCount,
    sourceCollectionIngestorAgentId,
    sourceCollectionDefaultKnowledgeBaseId,
    sourceCollectionDraft,
    sourceCollectionSearchOpenAssignmentCount,
    sourceCollectionPrecheckCandidateCount,
    selectResearchWorkspaceView,
    runKnowledgeCollectionCompletionMutation,
    sourceCollectionCompletionActionReadiness,
    sourceCollectionActionRunId,
    sourceCollectionLoopActionReadiness,
    sourceCollectionLoopStartsNewRun,
    startSourceCollectionRunMutation,
    sourceCollectionSearchActionReadiness,
    selectedSourceCollectionAssignment,
    executeSourceCollectionSearchMutation,
    selectedSourceCollectionRun,
    launchResearchStage,
    sourceCollectionStageWritebackSyncActive,
    sourceCollectionStageCardById,
    sourceCollectionStageSessionTaskPendingStageId,
    sourceCollectionPendingStageTaskIds,
    selectedTeamStartResearchStagePending,
    selectedTeamStartSourceCollectionStageTaskPending,
    researchStageCanLaunch,
    sourceCollectionActionBusyReason,
    sourceCollectionActionNoInputReason,
    sourceCollectionAssignmentsDataLoading,
    sourceCollectionActionDataError,
    sourceCollectionActionLoadingReason,
    sourceCollectionActionErrorReason,
    selectedTeamExecuteSourceCollectionSearchPending,
    sourceCollectionAcceptedBackgroundActive,
    sourceCollectionActionReadiness,
    styles,
  } = ctx;

  const openSourceCollectionStorageTarget = (
    target: SourceCollectionStorageOpenTarget,
    runIdOverride?: string,
  ) => {
    const runId = runIdOverride || selectedSourceCollectionRunEffectiveId;
    if (!selectedTeam?.teamId || !runId) {
      return;
    }
    openSourceCollectionStorageMutation.mutate({
      teamId: selectedTeam.teamId,
      runId,
      target,
    });
  };

  const selectSourceCollectionCandidate = (candidate: TeamWorkflowCandidate) => {
    setSelectedSourceCollectionCandidateId(candidate.candidateId);
  };

  const sourceCollectionCandidateCardKeyDown = (
    event: ReactKeyboardEvent<HTMLElement>,
    candidate: TeamWorkflowCandidate,
  ) => {
    if (event.key !== "Enter" && event.key !== " ") {
      return;
    }
    event.preventDefault();
    selectSourceCollectionCandidate(candidate);
  };

  const sourceCollectionStageForPanel = (panelId: string): SourceCollectionStageModuleId => {
    if (panelId === "source-collection-screening-panel") {
      return "extraction";
    }
    if (panelId === "source-collection-graph-panel") {
      return "relations";
    }
    if (panelId === "source-collection-memory-panel") {
      return "ingestion";
    }
    return "finding";
  };

  const selectSourceCollectionStage = (stageId: SourceCollectionStageModuleId) => {
    setSelectedSourceCollectionStageId(stageId);
    if (!sourceCollectionStandalone) {
      return;
    }
    const nextParams = new URLSearchParams(searchParams);
    nextParams.set("researchView", "knowledge_collection");
    nextParams.set("collectionStage", stageId);
    setSearchParams(nextParams, { replace: true });
  };

  const openSourceCollectionStage = (stageId: SourceCollectionStageModuleId) => {
    selectSourceCollectionStage(stageId);
    setSourceCollectionFocusedPanelId("");
  };

  const scrollSourceCollectionPanelIntoView = (panelId: string) => {
    selectSourceCollectionStage(sourceCollectionStageForPanel(panelId));
    setSourceCollectionExpandedPanelId(panelId);
    setSourceCollectionFocusedPanelId(panelId);
    window.setTimeout(() => {
      setSourceCollectionFocusedPanelId((current: string) => (current === panelId ? "" : current));
    }, 2200);
    window.requestAnimationFrame(() => {
      const target = document.getElementById(panelId);
      if (!target) {
        return;
      }
      if (target instanceof HTMLDetailsElement) {
        target.open = true;
      }
      const container = (sourceCollectionControlPanelRef as RefObject<HTMLElement | null>)?.current;
      if (container && container.contains(target)) {
        const containerTop = container.getBoundingClientRect().top;
        const targetTop = target.getBoundingClientRect().top;
        const nextTop = Math.max(0, container.scrollTop + targetTop - containerTop - 10);
        container.scrollTo({
          top: nextTop,
          behavior: "smooth",
        });
        target.focus({ preventScroll: true });
        return;
      }
      target.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
      target.focus({ preventScroll: true });
    });
  };

  if (scrollSourceCollectionPanelIntoViewRef) {
    (scrollSourceCollectionPanelIntoViewRef as MutableRefObject<(panelId: string) => void>).current =
      scrollSourceCollectionPanelIntoView;
  }

  const openSourceCollectionScreeningPanel = () => {
    if (!selectedTeam?.teamId || sourceCollectionScreeningDisabled) {
      return;
    }
    scrollSourceCollectionPanelIntoView("source-collection-screening-panel");
  };

  const runSourceCollectionScreeningAction = () => {
    openSourceCollectionStage("extraction");
    if (sourceCollectionScreeningActionReadiness.disabled || !selectedTeam?.teamId) {
      return;
    }
    const forceRescreen = sourceCollectionRunPendingScreeningCount <= 0 && sourceCollectionDisplayedCandidateCount > 0;
    const maxCandidates = forceRescreen ? sourceCollectionDisplayedCandidateCount : sourceCollectionRunPendingScreeningCount;
    assessSourceQualityBatchMutation.mutate({
      teamId: selectedTeam.teamId,
      assessedByAgent: sourceCollectionExtractorAgentId,
      maxCandidates: Math.max(1, Math.min(200, maxCandidates)),
      force: forceRescreen,
      notes: forceRescreen
        ? "Source Extractor Agent re-ran quality scoring on already assessed source_manifest candidates (no content rewrite)."
        : "Source Extractor Agent ran quality scoring on pending source_manifest candidates.",
    });
  };

  const excludeUnverifiableSourceCollectionCandidates = async () => {
    if (
      !selectedTeam?.teamId
      || selectedTeamSourceQualityPending
      || sourceCollectionUnverifiableCandidateIds.length <= 0
    ) {
      return;
    }
    for (const candidateId of sourceCollectionUnverifiableCandidateIds) {
      await assessSourceQualityMutation.mutateAsync({
        teamId: selectedTeam.teamId,
        candidateId,
        decision: "rejected",
      });
    }
  };

  const openSourceCollectionCandidatePanel = () => {
    if (!selectedTeam?.teamId) {
      return;
    }
    scrollSourceCollectionPanelIntoView("source-collection-screening-panel");
  };

  const runSourceCollectionCandidateExtractionAction = () => {
    openSourceCollectionStage("extraction");
    if (
      sourceCollectionCandidateExtractionActionReadiness.disabled
      || !selectedTeam?.teamId
      || !selectedSourceCollectionRunEffectiveId
    ) {
      return;
    }
    const forceExtraction = sourceCollectionPendingCandidateImportCount <= 0 && sourceCollectionDisplayedCandidateCount > 0;
    const targetRecordCount = forceExtraction
      ? Math.max(sourceCollectionRawRecordCount, sourceCollectionDisplayedCandidateCount)
      : Math.max(sourceCollectionPendingCandidateImportCount, sourceCollectionRawRecordCount);
    extractSourceCollectionCandidatesMutation.mutate({
      teamId: selectedTeam.teamId,
      runId: selectedSourceCollectionRunEffectiveId,
      extractionAgentId: sourceCollectionExtractorAgentId,
      maxRecords: Math.max(1, Math.min(500, targetRecordCount)),
      force: forceExtraction,
      notes: forceExtraction
        ? "Source Extractor Agent re-checked the DataRecord to source_manifest bridge without creating duplicate candidates."
        : "Source Extractor Agent imported pending DataRecords into source_manifest candidates.",
    });
  };

  const runSourceCollectionGraphAction = () => {
    if (sourceCollectionGraphActionReadiness.disabled || !selectedTeam?.teamId) {
      return;
    }
    buildCandidateGraphMutation.mutate({
      teamId: selectedTeam.teamId,
      title: "Agent curated candidate graph",
      createdByAgent: sourceCollectionRelationMapperAgentId,
      sourceQualityAgentId: sourceCollectionExtractorAgentId,
      curationMode: "agent_approved_only",
      maxCandidates: Math.max(1, Math.min(80, sourceCollectionIngestCandidateCount)),
      forceReview: sourceCollectionRunApprovedCount <= 0 && sourceCollectionDisplayedCandidateCount > 0,
    });
    openSourceCollectionStage("relations");
  };

  const startKnowledgeCollectionCompletionForRun = (
    runId: string,
    options: {
      displayedCandidateCount?: number;
      ingestCandidateCount?: number;
      precheckCandidateCount?: number;
      rawRecordCount?: number;
      searchOpenAssignmentCount?: number;
    } = {},
  ) => {
    if (!selectedTeam?.teamId || !runId) {
      return;
    }
    const searchOpenAssignmentCount = options.searchOpenAssignmentCount ?? sourceCollectionSearchOpenAssignmentCount;
    const rawRecordCount = options.rawRecordCount ?? sourceCollectionRawRecordCount;
    const displayedCandidateCount = options.displayedCandidateCount ?? sourceCollectionDisplayedCandidateCount;
    const ingestCandidateCount = options.ingestCandidateCount ?? sourceCollectionIngestCandidateCount;
    const precheckCandidateCount = options.precheckCandidateCount ?? sourceCollectionPrecheckCandidateCount;
    selectResearchWorkspaceView("canvas" as ResearchWorkspaceView);
    const nextParams = new URLSearchParams(searchParams);
    nextParams.set("team", selectedTeam.teamId);
    nextParams.set("researchView", "canvas");
    setSearchParams(nextParams, { replace: false });
    runKnowledgeCollectionCompletionMutation.mutate({
      teamId: selectedTeam.teamId,
      runId,
      extractionAgentId: sourceCollectionExtractorAgentId,
      sourceQualityAgentId: sourceCollectionExtractorAgentId,
      candidateGraphAgentId: sourceCollectionRelationMapperAgentId,
      stewardAgentId: sourceCollectionIngestorAgentId,
      knowledgeBaseId: sourceCollectionDefaultKnowledgeBaseId,
      targetDomain: sourceCollectionDraft.topic || "神经机制启发神经网络算法",
      maxCandidates: Math.max(1, Math.min(80, ingestCandidateCount)),
      maxSearchBatches: 20,
      maxQueriesPerBatch: Math.max(1, Math.min(50, searchOpenAssignmentCount || 4)),
      maxResultsPerQuery: Math.max(1, Math.min(5, sourceCollectionDraft.maxResultsPerQuery || 3)),
      maxRecords: Math.max(1, Math.min(1000, Math.max(rawRecordCount, displayedCandidateCount, 100))),
      forceReview: precheckCandidateCount <= 0 && displayedCandidateCount > 0,
    });
  };

  const runKnowledgeCollectionCompletionAction = () => {
    if (sourceCollectionCompletionActionReadiness.disabled || !sourceCollectionActionRunId) {
      return;
    }
    startKnowledgeCollectionCompletionForRun(sourceCollectionActionRunId);
  };

  const runKnowledgeCollectionLoopAction = async () => {
    if (sourceCollectionLoopActionReadiness.disabled || !selectedTeam?.teamId) {
      return;
    }
    if (sourceCollectionLoopStartsNewRun) {
      try {
        const started = await startSourceCollectionRunMutation.mutateAsync({
          teamId: selectedTeam.teamId,
          draft: sourceCollectionDraft,
        });
        const startedRunId = started.run.runId;
        const startedAssignmentCount = Math.max(started.assignmentCount, started.assignments.length);
        startKnowledgeCollectionCompletionForRun(startedRunId, {
          displayedCandidateCount: 0,
          ingestCandidateCount: 0,
          precheckCandidateCount: 0,
          rawRecordCount: 0,
          searchOpenAssignmentCount: startedAssignmentCount || 4,
        });
      } catch {
        return;
      }
      return;
    }
    if (!sourceCollectionActionRunId) {
      return;
    }
    startKnowledgeCollectionCompletionForRun(sourceCollectionActionRunId);
  };

  const runSourceCollectionSearchFromHeader = () => {
    if (sourceCollectionSearchActionReadiness.disabled || !selectedTeam?.teamId || !selectedSourceCollectionRunEffectiveId) {
      return;
    }
    const selectedAssignmentIsRunnable = selectedSourceCollectionAssignment
      ? ["open", "in_progress", "returned"].includes(selectedSourceCollectionAssignment.status)
        && SOURCE_COLLECTION_SEARCH_EXECUTION_ROLES.has(selectedSourceCollectionAssignment.agentRole)
      : false;
    executeSourceCollectionSearchMutation.mutate({
      teamId: selectedTeam.teamId,
      runId: selectedSourceCollectionRunEffectiveId,
      assignmentId: selectedAssignmentIsRunnable ? selectedSourceCollectionAssignment?.assignmentId : "",
      maxQueries: 4,
      maxResultsPerQuery: Math.max(1, Math.min(5, sourceCollectionDraft.maxResultsPerQuery || 2)),
    });
  };

  const sourceCollectionStageProjectionSyncing = (
    projection: SourceCollectionStageCardProjection | null | undefined,
  ) => {
    if (!sourceCollectionStageWritebackSyncActive || !projection) {
      return false;
    }
    const latestTaskStatus = String(projection.latestTask?.status || "").toLowerCase();
    return projection.status === "agent_running" || latestTaskStatus === "queued" || latestTaskStatus === "running";
  };

  const sourceCollectionStageProjectionLabel = (
    projection: SourceCollectionStageCardProjection | null | undefined,
  ) => {
    if (!projection?.status) {
      return "";
    }
    return sourceCollectionStageUserStatusLabel(projection, lang, sourceCollectionStageProjectionSyncing(projection));
  };

  function sourceCollectionStageLaunchActive(stageId: SourceCollectionStageModuleId) {
    const projection = sourceCollectionStageCardById.get(stageId);
    return sourceCollectionStageLaunchActivePure(stageId, {
      pendingStageId: sourceCollectionStageSessionTaskPendingStageId,
      pendingTaskIds: sourceCollectionPendingStageTaskIds[stageId] ?? [],
      writebackSyncActive: sourceCollectionStageWritebackSyncActive,
      latestTaskId: projection?.latestTask?.taskId || "",
      latestTaskStatus: String(projection?.latestTask?.status || "").toLowerCase(),
      projectionStatus: String(projection?.status || "").toLowerCase(),
    });
  }

  function sourceCollectionStageFormalRetryRequired(stageId: SourceCollectionStageModuleId) {
    const latestTaskStatus = String(
      sourceCollectionStageCardById.get(stageId)?.latestTask?.status || "",
    ).trim().toLowerCase();
    return new Set(["failed", "error", "blocked", "cancelled", "canceled", "incomplete"]).has(
      latestTaskStatus,
    );
  }

  function sourceCollectionStageLaunchSummary(stageId: SourceCollectionStageModuleId) {
    return sourceCollectionStageLaunchSummaryPure(stageId, sourceCollectionStageSessionTaskPendingStageId, lang);
  }

  function sourceCollectionStageDisplayState(stageId: SourceCollectionStageModuleId, fallback: SourceCollectionStepState) {
    return sourceCollectionStageDisplayStatePure(sourceCollectionStageLaunchActive(stageId), fallback);
  }

  function sourceCollectionStageDisplayStatus(stageId: SourceCollectionStageModuleId, fallback: string) {
    return sourceCollectionStageDisplayStatusPure(
      stageId,
      sourceCollectionStageLaunchActive(stageId),
      sourceCollectionStageSessionTaskPendingStageId,
      fallback,
      lang,
    );
  }

  function sourceCollectionStageDisplaySummary(stageId: SourceCollectionStageModuleId, fallback: string) {
    return sourceCollectionStageDisplaySummaryPure(
      sourceCollectionStageLaunchActive(stageId),
      sourceCollectionStageLaunchSummary(stageId),
      fallback,
    );
  }

  const sourceCollectionStepClassName = (state: SourceCollectionStepState) => ({
    active: styles.sourceCollectionStepActive,
    done: styles.sourceCollectionStepDone,
    failed: styles.sourceCollectionStepFailed,
    idle: styles.sourceCollectionStepIdle,
    pending: styles.sourceCollectionStepPending,
  }[state]);

  const sourceCollectionCollectionActionLabel = !selectedSourceCollectionRun
    ? sourceCollectionStageSessionTaskPendingStageId === "finding"
      ? (lang === "zh" ? "启动 Agent 中" : "Starting Agent")
      : (lang === "zh" ? "开始搜集" : "Start")
    : selectedTeamExecuteSourceCollectionSearchPending || sourceCollectionAcceptedBackgroundActive
      ? (lang === "zh" ? "搜索中" : "Searching")
      : sourceCollectionSearchOpenAssignmentCount > 0
        ? (lang === "zh" ? "搜索下一批" : "Search next")
        : (lang === "zh" ? "新一轮搜集" : "New round");

  const sourceCollectionCollectionActionReadiness: SourceCollectionActionReadiness = !selectedSourceCollectionRun
    ? sourceCollectionActionReadinessOf(
      selectedTeamStartResearchStagePending || selectedTeamStartSourceCollectionStageTaskPending || !researchStageCanLaunch,
      selectedTeamStartResearchStagePending || selectedTeamStartSourceCollectionStageTaskPending
        ? sourceCollectionActionBusyReason
        : sourceCollectionActionNoInputReason,
      selectedTeamStartResearchStagePending || selectedTeamStartSourceCollectionStageTaskPending,
    )
    : sourceCollectionAssignmentsDataLoading || sourceCollectionActionDataError
      ? sourceCollectionActionReadinessOf(
        true,
        sourceCollectionAssignmentsDataLoading ? sourceCollectionActionLoadingReason : sourceCollectionActionErrorReason,
        sourceCollectionAssignmentsDataLoading,
      )
      : sourceCollectionSearchOpenAssignmentCount > 0
        ? sourceCollectionSearchActionReadiness
        : sourceCollectionActionReadinessOf(
          selectedTeamStartResearchStagePending || selectedTeamStartSourceCollectionStageTaskPending || !researchStageCanLaunch,
          selectedTeamStartResearchStagePending || selectedTeamStartSourceCollectionStageTaskPending
            ? sourceCollectionActionBusyReason
            : sourceCollectionActionNoInputReason,
          selectedTeamStartResearchStagePending || selectedTeamStartSourceCollectionStageTaskPending,
        );

  const runSourceCollectionCollectionAction = () => {
    if (sourceCollectionCollectionActionReadiness.disabled || !selectedTeam?.teamId) {
      return;
    }
    openSourceCollectionStage("finding");
    if (!selectedSourceCollectionRun) {
      launchResearchStage("knowledge_collection");
      return;
    }
    if (sourceCollectionSearchOpenAssignmentCount > 0) {
      runSourceCollectionSearchFromHeader();
      return;
    }
    launchResearchStage("knowledge_collection", "new_round");
  };

  return {
    openSourceCollectionStorageTarget,
    selectSourceCollectionCandidate,
    sourceCollectionCandidateCardKeyDown,
    sourceCollectionStageForPanel,
    selectSourceCollectionStage,
    openSourceCollectionStage,
    scrollSourceCollectionPanelIntoView,
    openSourceCollectionScreeningPanel,
    runSourceCollectionScreeningAction,
    excludeUnverifiableSourceCollectionCandidates,
    openSourceCollectionCandidatePanel,
    runSourceCollectionCandidateExtractionAction,
    runSourceCollectionGraphAction,
    startKnowledgeCollectionCompletionForRun,
    runKnowledgeCollectionCompletionAction,
    runKnowledgeCollectionLoopAction,
    runSourceCollectionSearchFromHeader,
    runSourceCollectionCollectionAction,
    sourceCollectionStageProjectionSyncing,
    sourceCollectionStageProjectionLabel,
    sourceCollectionStageLaunchActive,
    sourceCollectionStageFormalRetryRequired,
    sourceCollectionStageLaunchSummary,
    sourceCollectionStageDisplayState,
    sourceCollectionStageDisplayStatus,
    sourceCollectionStageDisplaySummary,
    sourceCollectionStepClassName,
    sourceCollectionCollectionActionLabel,
    sourceCollectionCollectionActionReadiness,
  };
}
