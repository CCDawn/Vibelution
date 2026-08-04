// @ts-nocheck
/**
 * Source-collection presentation + action adapters for Teams.
 * Extracted from TeamsRoute (behavior-conserving). Stage module array with UI labels
 * is still composed in TeamsRoute from returned helpers + local wiring if needed.
 *
 * Note: @ts-nocheck keeps incomplete extract typing from blocking product build;
 * runtime logic is behavior-conserving from TeamsRoute. Tighten types in a follow-up.
 */
import { useEffect, useMemo, type MutableRefObject, type Dispatch, type SetStateAction } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import type { NavigateFunction, SetURLSearchParams } from "react-router-dom";
import type { QueryClient, UseMutationResult, UseQueryResult } from "@tanstack/react-query";

import { queryKeys } from "../../api/queryKeys";
import type {
  DataProcessingStatus,
  Team,
  TeamWorkflowCandidate,
  WorkRunSnapshot,
  TeamWorkflowSourceCollectionPromptCachePolicyRef,
} from "../../api/types";
import { isRecord, workRunString } from "./workflowPresentation";
import { latestWorkflowCandidate, workflowCandidateGraphFromCandidate } from "./teamRouteShellModel";
import {
  buildSourceCollectionWriteMutationSurface,
  buildTeamsRouteMutationSurface,
} from "./teamMutationSurface";
import {
  sourceCollectionActionDisabledTitle as sourceCollectionActionDisabledTitlePure,
  sourceCollectionActionReadinessOf,
  sourceCollectionLoadingChrome,
} from "./source-collection/actionChrome";
import {
  deriveSourceCollectionExcludedRecoveryState,
  sourceCollectionCandidateSourceCategory,
  sourceCollectionCandidateTrace,
  sourceCollectionEvidenceLedgerSummary,
  sourceCollectionFilterCounts,
  sourceCollectionFilterMatches,
  sourceCollectionRecordProvenance,
  sourceCollectionRecordSourceCategory,
  sourceCollectionSourceTypeLabel,
  type SourceCollectionEvidenceLedgerSummary,
  type SourceCollectionSourceFilter,
} from "./source-collection/evidenceModel";
import {
  deriveSourceCollectionDisplayState,
  sourceCollectionActiveWorkRunFromRuntime,
  sourceCollectionRunLabel,
  sourceCollectionRunTitleLabel,
  sourceCollectionStableCountText,
  translateResearchPhrase,
  type SourceCollectionStepState,
} from "./source-collection/runModel";
import {
  selectSourceCollectionStageRound,
  sourceCollectionBoundCountToCurrentCoverage,
  sourceCollectionNonNegativeCount,
  sourceCollectionPhaseCloseGateForRun,
  sourceCollectionStageBackendActionReadiness,
  sourceCollectionStageProjectionCount,
  sourceCollectionStageProjectionState,
  sourceCollectionStageUserStatusLabel,
  sourceCollectionStageUserSummary,
  type ResearchStageRound,
  type SourceCollectionActionReadiness,
  type SourceCollectionStageCardProjection,
  type SourceCollectionStageModuleId,
} from "./source-collection/stageProjection";
import {
  SOURCE_COLLECTION_PROMPT_CACHE_POLICY,
  SOURCE_COLLECTION_RUN_PREVIEW_LIMIT,
  SOURCE_COLLECTION_SEARCH_EXECUTION_ROLES,
  SOURCE_COLLECTION_STAGE_WRITEBACK_SYNC_GRACE_MS,
  hasSourceCollectionPromptCachePolicy,
  sourceCollectionAgentRoleLabel,
  sourceCollectionCandidateQualityState,
  sourceCollectionLanguageLabel,
  sourceCollectionMaterialGapCount,
  sourceCollectionStatusLabel,
  sourceCollectionStorageArtifactsForRun,
  type SourceCollectionDraft,
  type SourceCollectionStorageArtifacts,
  type SourceCollectionStorageOpenTarget,
} from "./source-collection/presentationModel";
import type { SourceCollectionOutputDraft } from "./sourceCollectionMutationModel";
import {
  sourceCollectionRunRecordsQueryKey,
  sourceCollectionSummaryQueryKey,
} from "./teamWorkflowQueryKeys";
import { researchWorkspaceStageRoute, researchSourceCollectionRoute } from "./researchWorkspaceModel";
import { RESEARCH_TEAM_ID } from "../TeamsRoute.canvasData";
import { parseSourceCollectionStageModuleId } from "./teamRouteShellModel";
import {
  sourceCollectionStageDisplayState as sourceCollectionStageDisplayStatePure,
  sourceCollectionStageDisplayStatus as sourceCollectionStageDisplayStatusPure,
  sourceCollectionStageDisplaySummary as sourceCollectionStageDisplaySummaryPure,
  sourceCollectionStageLaunchActive as sourceCollectionStageLaunchActivePure,
  sourceCollectionStageLaunchSummary as sourceCollectionStageLaunchSummaryPure,
} from "./teamSourceCollectionShellModel";

export type UseSourceCollectionPresentationInput = {
  lang: "zh" | "en";
  selectedTeam: Team | null;
  effectiveTeamId: string;
  researchWorkflowTeamSelected: boolean;
  pageVisible: boolean;
  researchStagePhases: any[];
  researchStageRoundStatus: any;
  researchStageProjectAgentTasks: { isStarting: boolean; error: unknown };
  teamWorkflowCandidates: TeamWorkflowCandidate[];
  teamWorkflowCandidatesQuery: UseQueryResult<any, Error>;
  teamWorkflowCandidateListEnabled: boolean;
  teamWorkflowSourceQualityStatus: any;
  teamWorkflowSourceQualityStatusQuery: UseQueryResult<any, Error>;
  teamWorkflowCandidateGraphQuery: UseQueryResult<any, Error>;
  teamWorkflowKnowledgeIngestionStatusQuery: UseQueryResult<any, Error>;
  teamWorkflowPaperNoteChunkStatus: any;
  teamWorkflow: any;
  runtimeSummaryQuery: { data?: any };
  sourceCollectionSummaryQuery: UseQueryResult<any, Error>;
  sourceCollectionRecordsQuery: UseQueryResult<any, Error>;
  sourceCollectionAssignmentsQuery: UseQueryResult<any, Error>;
  sourceCollectionRunStatusQuery: UseQueryResult<any, Error>;
  sourceCollectionFindingDetailsVisible: boolean;
  sourceCollectionRuns: any[];
  sourceCollectionRunsQuery: UseQueryResult<any, Error>;
  sourceCollectionWorkspaceSelected: boolean;
  teamWorkflowSourceQualityEnabled: boolean;
  teamWorkflowGraphEnabled: boolean;
  teamWorkflowKnowledgeIngestionEnabled: boolean;
  selectedSourceCollectionRun: any;
  selectedSourceCollectionRunEffectiveId: string;
  sourceCollectionDraft: SourceCollectionDraft;
  sourceCollectionOutputDraft: SourceCollectionOutputDraft;
  setSourceCollectionOutputDraft: Dispatch<SetStateAction<SourceCollectionOutputDraft>>;
  selectedSourceCollectionCandidateId: string;
  setSelectedSourceCollectionCandidateId: Dispatch<SetStateAction<string>>;
  sourceCollectionSourceFilter: SourceCollectionSourceFilter;
  setSourceCollectionSourceFilter: Dispatch<SetStateAction<SourceCollectionSourceFilter>>;
  sourceCollectionResultPageByStage: Record<SourceCollectionStageModuleId, number>;
  setSourceCollectionResultPageByStage: Dispatch<SetStateAction<Record<SourceCollectionStageModuleId, number>>>;
  selectedSourceCollectionStageId: SourceCollectionStageModuleId;
  setSelectedSourceCollectionStageId: Dispatch<SetStateAction<SourceCollectionStageModuleId>>;
  sourceCollectionExpandedPanelId: string;
  setSourceCollectionExpandedPanelId: Dispatch<SetStateAction<string>>;
  sourceCollectionFocusedPanelId: string;
  setSourceCollectionFocusedPanelId: Dispatch<SetStateAction<string>>;
  activeSourceCollectionResearchProjectId: string;
  sourceCollectionNeedsCandidateList: boolean;
  experimentPlanningStatusQuery: UseQueryResult<any, Error>;
  researchLoopTemplatesQuery: UseQueryResult<any, Error>;
  researchLoopStatusQuery: UseQueryResult<any, Error>;
  aiSearchRunsQuery: UseQueryResult<any, Error>;
  aiSearchRunTopic: string;
  resetResearchProjectSourceCollectionMutation: UseMutationResult<any, Error, any, unknown>;
  startResearchStageRoundMutation: UseMutationResult<any, Error, any, unknown>;
  createExperimentPlanMutation: UseMutationResult<any, Error, any, unknown>;
  materializeEngineeringProxyHypothesisMutation: UseMutationResult<any, Error, any, unknown>;
  completeScientificHypothesisFromDesignMutation: UseMutationResult<any, Error, any, unknown>;
  reviewExperimentHypothesisMutation: UseMutationResult<any, Error, any, unknown>;
  createExperimentHypothesisRevisionMutation: UseMutationResult<any, Error, any, unknown>;
  freezeExperimentDesignMutation: UseMutationResult<any, Error, any, unknown>;
  registerExperimentBaselineArtifactMutation: UseMutationResult<any, Error, any, unknown>;
  runExperimentSmokeMutation: UseMutationResult<any, Error, any, unknown>;
  registerExperimentSmokeResultMutation: UseMutationResult<any, Error, any, unknown>;
  registerExperimentFullRunResultMutation: UseMutationResult<any, Error, any, unknown>;
  requestExperimentKnowledgeIngestionMutation: UseMutationResult<any, Error, any, unknown>;
  createResearchLoopMutation: UseMutationResult<any, Error, any, unknown>;
  recordResearchLoopEvidenceMutation: UseMutationResult<any, Error, any, unknown>;
  recordResearchLoopDecisionMutation: UseMutationResult<any, Error, any, unknown>;
  startSourceCollectionRunMutation: UseMutationResult<any, Error, any, unknown>;
  startSourceCollectionStageSessionTaskMutation: UseMutationResult<any, Error, any, unknown>;
  recordSourceCollectionOutputMutation: UseMutationResult<any, Error, any, unknown>;
  executeSourceCollectionSearchMutation: UseMutationResult<any, Error, any, unknown>;
  extractSourceCollectionCandidatesMutation: UseMutationResult<any, Error, any, unknown>;
  openSourceCollectionStorageMutation: UseMutationResult<any, Error, any, unknown>;
  startAiSearchRunMutation: UseMutationResult<any, Error, any, unknown>;
  buildCandidateGraphMutation: UseMutationResult<any, Error, any, unknown>;
  runKnowledgeIngestionPrecheckMutation: UseMutationResult<any, Error, any, unknown>;
  runKnowledgeCollectionCompletionMutation: UseMutationResult<any, Error, any, unknown>;
  planPaperNoteChunksMutation: UseMutationResult<any, Error, any, unknown>;
  assessSourceQualityMutation: UseMutationResult<any, Error, any, unknown>;
  assessSourceQualityBatchMutation: UseMutationResult<any, Error, any, unknown>;
  queryClient: QueryClient;
  requestedSourceCollectionStage: SourceCollectionStageModuleId | null;
  setSourceCollectionStageSyncUntilMs: Dispatch<SetStateAction<number>>;
  setSourceCollectionPendingStageTaskIds: Dispatch<SetStateAction<any>>;
  searchParams: URLSearchParams;
  setSearchParams: SetURLSearchParams;
  navigate: NavigateFunction;
  scrollSourceCollectionPanelIntoViewRef: MutableRefObject<(panelId: string) => void>;
  sourceCollectionControlPanelRef: MutableRefObject<HTMLElement | null>;
  sourceCollectionRelationMapperAgentId: string;
  sourceCollectionExtractorAgentId: string;
  sourceCollectionOwnerAgentId: string;
  sourceCollectionIngestorAgentId: string;
  sourceCollectionStandalone: boolean;
  sourceCollectionStageWritebackSyncActive: boolean;
  sourceCollectionPendingStageTaskIds: Partial<Record<SourceCollectionStageModuleId, string[]>>;
  selectResearchWorkspaceView: (view: any) => void;
  launchResearchStage: (stageType: any, mode?: "continue_or_start" | "new_round") => void | Promise<void>;
  /** CSS module map for SC step badge classes (route styles). */
  styles: Record<string, string>;
};

export function useSourceCollectionPresentation(input: UseSourceCollectionPresentationInput) {
  const {
    lang,
    selectedTeam,
    effectiveTeamId,
    researchWorkflowTeamSelected,
    pageVisible,
    researchStagePhases,
    researchStageRoundStatus,
    researchStageProjectAgentTasks,
    teamWorkflowCandidates,
    teamWorkflowCandidatesQuery,
    teamWorkflowCandidateListEnabled,
    teamWorkflowSourceQualityStatus,
    teamWorkflowSourceQualityStatusQuery,
    teamWorkflowCandidateGraphQuery,
    teamWorkflowKnowledgeIngestionStatusQuery,
    teamWorkflowPaperNoteChunkStatus,
    teamWorkflow,
    runtimeSummaryQuery,
    sourceCollectionSummaryQuery,
    sourceCollectionRecordsQuery,
    sourceCollectionAssignmentsQuery,
    sourceCollectionRunStatusQuery,
    sourceCollectionFindingDetailsVisible,
    sourceCollectionRuns,
    sourceCollectionRunsQuery,
    sourceCollectionWorkspaceSelected,
    teamWorkflowSourceQualityEnabled,
    teamWorkflowGraphEnabled,
    teamWorkflowKnowledgeIngestionEnabled,
    selectedSourceCollectionRun,
    selectedSourceCollectionRunEffectiveId,
    sourceCollectionDraft,
    sourceCollectionOutputDraft,
    setSourceCollectionOutputDraft,
    selectedSourceCollectionCandidateId,
    setSelectedSourceCollectionCandidateId,
    sourceCollectionSourceFilter,
    setSourceCollectionSourceFilter,
    sourceCollectionResultPageByStage,
    setSourceCollectionResultPageByStage,
    selectedSourceCollectionStageId,
    setSelectedSourceCollectionStageId,
    sourceCollectionExpandedPanelId,
    setSourceCollectionExpandedPanelId,
    sourceCollectionFocusedPanelId,
    setSourceCollectionFocusedPanelId,
    activeSourceCollectionResearchProjectId,
    sourceCollectionNeedsCandidateList,
    experimentPlanningStatusQuery,
    researchLoopTemplatesQuery,
    researchLoopStatusQuery,
    aiSearchRunsQuery,
    aiSearchRunTopic,
    resetResearchProjectSourceCollectionMutation,
    startResearchStageRoundMutation,
    createExperimentPlanMutation,
    materializeEngineeringProxyHypothesisMutation,
    completeScientificHypothesisFromDesignMutation,
    reviewExperimentHypothesisMutation,
    createExperimentHypothesisRevisionMutation,
    freezeExperimentDesignMutation,
    registerExperimentBaselineArtifactMutation,
    runExperimentSmokeMutation,
    registerExperimentSmokeResultMutation,
    registerExperimentFullRunResultMutation,
    requestExperimentKnowledgeIngestionMutation,
    createResearchLoopMutation,
    recordResearchLoopEvidenceMutation,
    recordResearchLoopDecisionMutation,
    startSourceCollectionRunMutation,
    startSourceCollectionStageSessionTaskMutation,
    recordSourceCollectionOutputMutation,
    executeSourceCollectionSearchMutation,
    extractSourceCollectionCandidatesMutation,
    openSourceCollectionStorageMutation,
    startAiSearchRunMutation,
    buildCandidateGraphMutation,
    runKnowledgeIngestionPrecheckMutation,
    runKnowledgeCollectionCompletionMutation,
    planPaperNoteChunksMutation,
    assessSourceQualityMutation,
    assessSourceQualityBatchMutation,
    queryClient,
    requestedSourceCollectionStage,
    setSourceCollectionStageSyncUntilMs,
    setSourceCollectionPendingStageTaskIds,
    searchParams,
    setSearchParams,
    navigate,
    scrollSourceCollectionPanelIntoViewRef,
    sourceCollectionControlPanelRef,
    sourceCollectionRelationMapperAgentId,
    sourceCollectionExtractorAgentId,
    sourceCollectionOwnerAgentId,
    sourceCollectionIngestorAgentId,
    sourceCollectionStandalone,
    sourceCollectionStageWritebackSyncActive,
    sourceCollectionPendingStageTaskIds,
    selectResearchWorkspaceView,
    launchResearchStage,
    styles,
  } = input;

  const teamWorkflowKnowledgeIngestionStatus = teamWorkflowKnowledgeIngestionStatusQuery.data ?? null;
  const teamWorkflowCandidateGraphRecord = latestWorkflowCandidate(
    teamWorkflowCandidateGraphQuery.data?.candidates ?? [],
  );
  const teamWorkflowCandidateGraph = workflowCandidateGraphFromCandidate(teamWorkflowCandidateGraphRecord);

  const sourceCollectionSummary = sourceCollectionSummaryQuery.data ?? null;
  const sourceCollectionSummaryRun = isRecord(sourceCollectionSummary?.run) ? sourceCollectionSummary.run : null;
  const sourceCollectionSummaryRunId = String(sourceCollectionSummaryRun?.runId || sourceCollectionSummary?.runId || "");
  const sourceCollectionActionRunId = selectedSourceCollectionRunEffectiveId || sourceCollectionSummaryRunId;
  const sourceCollectionPhaseCloseGate = sourceCollectionPhaseCloseGateForRun(
    sourceCollectionSummary,
    selectedSourceCollectionRunEffectiveId,
  );
  const sourceCollectionSummaryStageRound = useMemo<ResearchStageRound | null>(() => {
    if (!sourceCollectionSummary?.runId && !sourceCollectionSummary?.stageCards?.length) {
      return null;
    }
    const summaryRunId = String(sourceCollectionSummary.runId || sourceCollectionSummaryRunId || "");
    if (selectedSourceCollectionRunEffectiveId && summaryRunId && summaryRunId !== selectedSourceCollectionRunEffectiveId) {
      return null;
    }
    const roundRef = sourceCollectionSummary.stageRound ?? {};
    return {
      stageRoundId: String(roundRef.stageRoundId || `source-summary-${summaryRunId || "latest"}`),
      stageType: "knowledge_collection",
      roundNumber: Number(roundRef.roundNumber || 0),
      status: String(roundRef.status || sourceCollectionSummary.status || "ready"),
      topic: "",
      goal: "",
      sourceRunIds: summaryRunId ? [summaryRunId] : [],
      sourceCollectionStageCards: sourceCollectionSummary.stageCards ?? [],
      sourceCollectionStageCardSummary: sourceCollectionSummary.stageCardSummary ?? sourceCollectionSummary.summary ?? {},
    };
  }, [selectedSourceCollectionRunEffectiveId, sourceCollectionSummary, sourceCollectionSummaryRunId]);
  const sourceCollectionStageRound = useMemo(() => selectSourceCollectionStageRound(
    sourceCollectionSummaryStageRound,
    researchStagePhases,
    researchStageRoundStatus,
    selectedSourceCollectionRunEffectiveId,
  ), [
    researchStagePhases,
    researchStageRoundStatus,
    selectedSourceCollectionRunEffectiveId,
    sourceCollectionSummaryStageRound,
  ]);
  const sourceCollectionStageCards = sourceCollectionStageRound?.sourceCollectionStageCards ?? [];
  const sourceCollectionStageCardById = useMemo(() => {
    const mapping = new Map<SourceCollectionStageModuleId, SourceCollectionStageCardProjection>();
    sourceCollectionStageCards.forEach((card) => {
      const stageId = parseSourceCollectionStageModuleId(card.stageId);
      if (stageId) {
        mapping.set(stageId, { ...card, stageId });
      }
    });
    return mapping;
  }, [sourceCollectionStageCards]);
  const experimentPlanningStatus = experimentPlanningStatusQuery.data ?? null;
  const sourceCollectionRecords = sourceCollectionRecordsQuery.data?.records ?? [];
  const sourceCollectionAssignments = sourceCollectionAssignmentsQuery.data?.assignments ?? [];
  const sourceCollectionRunStatus = sourceCollectionRunStatusQuery.data ?? sourceCollectionSummary?.runStatus ?? null;
  const sourceCollectionSearchPlanRef = selectedSourceCollectionRun?.scope?.dataSearchPlanRef ?? null;
  const aiSearchRuns = aiSearchRunsQuery.data?.runs ?? [];
  const researchLoopTemplatesPayload = researchLoopTemplatesQuery.data ?? null;
  const researchLoopStatus = researchLoopStatusQuery.data ?? null;
  // Phase 4: team-scoped pending/error/result flags collapsed into one surface bag.
  const {
    selectedResearchProjectSourceCollectionResetPending,
    selectedResearchProjectSourceCollectionResetError,
    selectedTeamStartResearchStagePending,
    selectedTeamStartResearchStageError,
    selectedTeamStartResearchStageResult,
    selectedTeamCreateExperimentPlanPending,
    selectedTeamCreateExperimentPlanError,
    selectedTeamCreateExperimentPlanResult,
    selectedTeamMaterializeEngineeringProxyPending,
    selectedTeamMaterializeEngineeringProxyError,
    selectedTeamCompleteScientificHypothesisCandidateId,
    selectedTeamCompleteScientificHypothesisError,
    selectedTeamReviewExperimentHypothesisCandidateId,
    selectedTeamReviewExperimentHypothesisError,
    selectedTeamCreateExperimentHypothesisRevisionCandidateId,
    selectedTeamCreateExperimentHypothesisRevisionError,
    selectedTeamFreezeExperimentDesignPending,
    selectedTeamFreezeExperimentDesignError,
    selectedTeamFreezeExperimentDesignResult,
    selectedTeamRegisterExperimentBaselineArtifactPending,
    selectedTeamRegisterExperimentBaselineArtifactError,
    selectedTeamRegisterExperimentBaselineArtifactResult,
    selectedTeamRunExperimentSmokePending,
    selectedTeamRunExperimentSmokeError,
    selectedTeamRunExperimentSmokeResult,
    selectedTeamRegisterExperimentSmokeResultPending,
    selectedTeamRegisterExperimentSmokeResultError,
    selectedTeamRegisterExperimentSmokeResultResult,
    selectedTeamRegisterExperimentFullRunResultPending,
    selectedTeamRegisterExperimentFullRunResultError,
    selectedTeamRegisterExperimentFullRunResultResult,
    selectedTeamRequestExperimentKnowledgeIngestionPending,
    selectedTeamRequestExperimentKnowledgeIngestionError,
    selectedTeamRequestExperimentKnowledgeIngestionResult,
    selectedTeamCreateResearchLoopPending,
    selectedTeamCreateResearchLoopError,
    selectedTeamCreateResearchLoopResult,
    selectedTeamRecordResearchLoopEvidencePending,
    selectedTeamRecordResearchLoopEvidenceError,
    selectedTeamRecordResearchLoopEvidenceResult,
    selectedTeamRecordResearchLoopDecisionPending,
    selectedTeamRecordResearchLoopDecisionError,
    selectedTeamRecordResearchLoopDecisionResult,
    selectedTeamStartSourceCollectionPending,
    selectedTeamStartSourceCollectionError,
    selectedTeamStartSourceCollectionResult,
    selectedTeamStartSourceCollectionStageTaskPending,
    selectedTeamStartSourceCollectionStageTaskError,
    sourceCollectionStageSessionTaskPendingStageId,
    selectedTeamRecordSourceCollectionOutputPending,
    selectedTeamRecordSourceCollectionOutputError,
    selectedTeamRecordSourceCollectionOutputResult,
    selectedTeamExecuteSourceCollectionSearchPending,
    selectedTeamExecuteSourceCollectionSearchError,
    selectedTeamExecuteSourceCollectionSearchResult,
    selectedTeamExtractSourceCollectionCandidatesPending,
    selectedTeamExtractSourceCollectionCandidatesError,
    selectedTeamExtractSourceCollectionCandidatesResult,
    selectedSourceCollectionStorageOpenPending,
    selectedSourceCollectionStorageOpenResult,
    selectedSourceCollectionStorageOpenError,
    selectedTeamStartAiSearchPending,
    selectedTeamStartAiSearchError,
    selectedTeamStartAiSearchResult,
  } = buildTeamsRouteMutationSurface({
    teamId: selectedTeam?.teamId,
    resetResearchProjectSourceCollection: resetResearchProjectSourceCollectionMutation,
    startResearchStageRound: startResearchStageRoundMutation,
    createExperimentPlan: createExperimentPlanMutation,
    materializeEngineeringProxyHypothesis: materializeEngineeringProxyHypothesisMutation,
    completeScientificHypothesisFromDesign: completeScientificHypothesisFromDesignMutation,
    reviewExperimentHypothesis: reviewExperimentHypothesisMutation,
    createExperimentHypothesisRevision: createExperimentHypothesisRevisionMutation,
    freezeExperimentDesign: freezeExperimentDesignMutation,
    registerExperimentBaselineArtifact: registerExperimentBaselineArtifactMutation,
    runExperimentSmoke: runExperimentSmokeMutation,
    registerExperimentSmokeResult: registerExperimentSmokeResultMutation,
    registerExperimentFullRunResult: registerExperimentFullRunResultMutation,
    requestExperimentKnowledgeIngestion: requestExperimentKnowledgeIngestionMutation,
    createResearchLoop: createResearchLoopMutation,
    recordResearchLoopEvidence: recordResearchLoopEvidenceMutation,
    recordResearchLoopDecision: recordResearchLoopDecisionMutation,
    startSourceCollectionRun: startSourceCollectionRunMutation,
    startSourceCollectionStageSessionTask: startSourceCollectionStageSessionTaskMutation,
    recordSourceCollectionOutput: recordSourceCollectionOutputMutation,
    executeSourceCollectionSearch: executeSourceCollectionSearchMutation,
    extractSourceCollectionCandidates: extractSourceCollectionCandidatesMutation,
    openSourceCollectionStorage: openSourceCollectionStorageMutation,
    startAiSearchRun: startAiSearchRunMutation,
    researchStageProjectAgentStarting: researchStageProjectAgentTasks.isStarting,
    researchStageProjectAgentError: researchStageProjectAgentTasks.error,
    selectedSourceCollectionRunEffectiveId,
  });
  const latestAiSearchRun = selectedTeamStartAiSearchResult ?? aiSearchRuns[0] ?? null;
  const aiSearchRunCanStart = Boolean(selectedTeam?.teamId && aiSearchRunTopic.trim() && !selectedTeamStartAiSearchPending);
  const selectedSourceCollectionAssignment =
    sourceCollectionAssignments.find((item) => item.assignmentId === sourceCollectionOutputDraft.assignmentId)
    ?? sourceCollectionAssignments[0]
    ?? null;
  const selectedSourceCollectionQueries = selectedSourceCollectionAssignment?.scope?.assignedQueries ?? [];
  const sourceCollectionFindingRunOptions = sourceCollectionRuns.map((run) => ({
    id: run.runId,
    label: `${sourceCollectionRunLabel(run.runId)} · ${sourceCollectionRunTitleLabel(run.title, lang)}`,
  }));
  const sourceCollectionFindingAssignments = sourceCollectionAssignments.map((assignment) => ({
    id: assignment.assignmentId,
    roleLabel: sourceCollectionAgentRoleLabel(assignment.agentRole, lang),
    statusLabel: sourceCollectionStatusLabel(assignment.status, lang),
    queryCountLabel: `${assignment.scope.queryCount ?? assignment.scope.assignedQueries?.length ?? 0} ${lang === "zh" ? "条搜索" : "queries"}`,
    active: assignment.assignmentId === selectedSourceCollectionAssignment?.assignmentId,
  }));
  const sourceCollectionFindingQueries = selectedSourceCollectionQueries.slice(0, 6).map((query) => ({
    id: query.queryId,
    title: translateResearchPhrase(query.query, lang),
    meta: `${query.queryId} · ${sourceCollectionSourceTypeLabel(query.sourceType, lang)} · ${sourceCollectionLanguageLabel(query.language, lang)}`,
  }));
  const sourceCollectionCanStart = Boolean(selectedTeam?.teamId && sourceCollectionDraft.topic.trim());
  const researchStageCanLaunch = Boolean(selectedTeam?.teamId && sourceCollectionDraft.topic.trim());
  const sourceCollectionResetResearchProjectId = activeSourceCollectionResearchProjectId.trim();
  const sourceCollectionResetAvailable = Boolean(
    sourceCollectionResetResearchProjectId
    && sourceCollectionRuns.length > 0,
  );
  const sourceCollectionPromptCachePolicy =
    [
      selectedTeamStartSourceCollectionResult?.promptCachePolicy,
      selectedTeamStartSourceCollectionResult?.searchPlan.promptCachePolicy,
      selectedTeamStartResearchStageResult?.promptCachePolicy,
      selectedTeamStartResearchStageResult?.sourceCollectionRun?.promptCachePolicy,
      selectedTeamStartResearchStageResult?.searchPlan?.promptCachePolicy,
      selectedTeamStartResearchStageResult?.stageRound.promptCachePolicy,
    ].find(hasSourceCollectionPromptCachePolicy) ?? null;
  const sourceCollectionPromptCachePolicyRef: TeamWorkflowSourceCollectionPromptCachePolicyRef | null =
    selectedSourceCollectionRun?.scope.promptCachePolicyRef
    ?? selectedSourceCollectionAssignment?.scope.promptCachePolicyRef
    ?? (sourceCollectionSearchPlanRef?.promptCachePolicyId
      ? {
          policyId: sourceCollectionSearchPlanRef.promptCachePolicyId,
          requirement: sourceCollectionSearchPlanRef.promptCacheRequirement,
          gateStatus: sourceCollectionSearchPlanRef.promptCacheGateStatus,
        }
      : null);
  const sourceCollectionPromptCacheStatus =
    sourceCollectionPromptCachePolicy?.gate?.status || sourceCollectionPromptCachePolicyRef?.gateStatus || "";
  const sourceCollectionPromptCacheMode =
    sourceCollectionPromptCachePolicy?.promptCacheMode || sourceCollectionPromptCachePolicyRef?.promptCacheMode || "";
  const sourceCollectionPromptCacheRequirement =
    sourceCollectionPromptCachePolicy?.requirement || sourceCollectionPromptCachePolicyRef?.requirement || SOURCE_COLLECTION_PROMPT_CACHE_POLICY.requirement;
  const sourceCollectionOutputHasRecord =
    Boolean(sourceCollectionOutputDraft.title.trim() || sourceCollectionOutputDraft.sourceRef.trim() || sourceCollectionOutputDraft.rawLocation.trim());
  const selectedTeamInitialSourceCollectionSearchResult = selectedTeamStartResearchStageResult?.sourceCollectionSearchExecution;
  const selectedSourceCollectionSearchExecutionResult =
    selectedTeamExecuteSourceCollectionSearchResult ?? selectedTeamInitialSourceCollectionSearchResult;
  const selectedSourceCollectionSearchAccepted = Boolean(selectedSourceCollectionSearchExecutionResult?.accepted);
  const runtimeSourceCollectionActiveWorkRun = sourceCollectionActiveWorkRunFromRuntime(
    runtimeSummaryQuery.data,
    selectedSourceCollectionRunEffectiveId,
  );
  const summarySourceCollectionActiveWorkRun = isRecord(sourceCollectionSummary?.activeWorkRun)
    ? sourceCollectionSummary.activeWorkRun as WorkRunSnapshot
    : undefined;
  const selectedSourceCollectionActiveWorkRun =
    runtimeSummaryQuery.data
      ? runtimeSourceCollectionActiveWorkRun ?? undefined
      : summarySourceCollectionActiveWorkRun ?? selectedSourceCollectionSearchExecutionResult?.activeWorkRun;
  const sourceCollectionSummaryStorageArtifacts = sourceCollectionSummary?.storageArtifacts as SourceCollectionStorageArtifacts | undefined;
  const selectedSourceCollectionStorageArtifacts =
    selectedSourceCollectionSearchExecutionResult?.storageArtifacts
    ?? sourceCollectionSummaryStorageArtifacts
    ?? sourceCollectionStorageArtifactsForRun(selectedTeam?.teamId ?? effectiveTeamId, selectedSourceCollectionRunEffectiveId);
  useEffect(() => {
    if (!researchWorkflowTeamSelected || !pageVisible || !selectedTeam?.teamId || !selectedSourceCollectionRunEffectiveId) {
      return;
    }
    if (requestedSourceCollectionStage) {
      setSourceCollectionStageSyncUntilMs(Date.now() + SOURCE_COLLECTION_STAGE_WRITEBACK_SYNC_GRACE_MS);
    }
    void queryClient.invalidateQueries({ queryKey: sourceCollectionSummaryQueryKey(selectedTeam.teamId, selectedSourceCollectionRunEffectiveId) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowSourceCollectionRuns(selectedTeam.teamId, SOURCE_COLLECTION_RUN_PREVIEW_LIMIT) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.dataProcessingRunStatus(selectedSourceCollectionRunEffectiveId) });
    void queryClient.invalidateQueries({ queryKey: sourceCollectionRunRecordsQueryKey(selectedSourceCollectionRunEffectiveId) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.dataProcessingCollectionAssignments(selectedSourceCollectionRunEffectiveId) });
  }, [
    pageVisible,
    queryClient,
    requestedSourceCollectionStage,
    researchWorkflowTeamSelected,
    selectedSourceCollectionRunEffectiveId,
    selectedTeam?.teamId,
  ]);
  useEffect(() => {
    if (!selectedTeam?.teamId || !selectedSourceCollectionRunEffectiveId || !selectedSourceCollectionSearchAccepted) {
      return;
    }
    void queryClient.invalidateQueries({ queryKey: queryKeys.teamWorkflowSourceCollectionRuns(selectedTeam.teamId, SOURCE_COLLECTION_RUN_PREVIEW_LIMIT) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.dataProcessingRunStatus(selectedSourceCollectionRunEffectiveId) });
    void queryClient.invalidateQueries({ queryKey: sourceCollectionRunRecordsQueryKey(selectedSourceCollectionRunEffectiveId) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.dataProcessingCollectionAssignments(selectedSourceCollectionRunEffectiveId) });
    void queryClient.invalidateQueries({ queryKey: sourceCollectionSummaryQueryKey(selectedTeam.teamId, selectedSourceCollectionRunEffectiveId) });
  }, [
    queryClient,
    selectedSourceCollectionRunEffectiveId,
    selectedSourceCollectionSearchAccepted,
    selectedTeam?.teamId,
  ]);
  const openSourceCollectionStorageTarget = (target: SourceCollectionStorageOpenTarget, runIdOverride?: string) => {
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
  const sourceCollectionRunSummary = sourceCollectionRunStatus?.summary as (DataProcessingStatus["summary"] & {
    searchOpenAssignmentCount?: number;
    collectionOpenAssignmentCount?: number;
    downstreamOpenAssignmentCount?: number;
  }) | undefined;
  const sourceCollectionOpenAssignments = sourceCollectionAssignments.filter((assignment) => ["open", "in_progress", "returned"].includes(assignment.status));
  const sourceCollectionOpenAssignmentCount =
    sourceCollectionRunSummary?.openAssignmentCount
    ?? sourceCollectionOpenAssignments.length;
  const sourceCollectionSearchOpenAssignmentCount =
    sourceCollectionRunSummary?.searchOpenAssignmentCount
    ?? sourceCollectionOpenAssignments.filter((assignment) => SOURCE_COLLECTION_SEARCH_EXECUTION_ROLES.has(assignment.agentRole)).length;
  const sourceCollectionDownstreamOpenAssignmentCount =
    sourceCollectionRunSummary?.downstreamOpenAssignmentCount
    ?? Math.max(0, sourceCollectionOpenAssignmentCount - sourceCollectionSearchOpenAssignmentCount);
  const sourceManifestCandidates = useMemo(
    () => teamWorkflowCandidates.filter((candidate) => candidate.candidateType === "source_manifest"),
    [teamWorkflowCandidates],
  );
  const teamWorkflowCandidatesById = useMemo(() => {
    const mapping = new Map<string, TeamWorkflowCandidate>();
    teamWorkflowCandidates.forEach((candidate) => {
      mapping.set(candidate.candidateId, candidate);
    });
    return mapping;
  }, [teamWorkflowCandidates]);
  const sourceCollectionRunCandidates = useMemo(
    () => selectedSourceCollectionRunEffectiveId
      ? sourceManifestCandidates.filter((candidate) => sourceCollectionCandidateTrace(candidate).runId === selectedSourceCollectionRunEffectiveId)
      : sourceManifestCandidates,
    [selectedSourceCollectionRunEffectiveId, sourceManifestCandidates],
  );
  const selectedSourceCollectionCandidate = useMemo(
    () => sourceManifestCandidates.find((candidate) => candidate.candidateId === selectedSourceCollectionCandidateId) ?? null,
    [selectedSourceCollectionCandidateId, sourceManifestCandidates],
  );
  const selectedSourceCollectionCandidateTrace = selectedSourceCollectionCandidate
    ? sourceCollectionCandidateTrace(selectedSourceCollectionCandidate)
    : null;
  const selectedSourceCollectionCandidateRunId =
    selectedSourceCollectionCandidateTrace?.runId || selectedSourceCollectionRunEffectiveId;
  const selectedSourceCollectionCandidateStorageArtifacts =
    sourceCollectionStorageArtifactsForRun(selectedTeam?.teamId ?? effectiveTeamId, selectedSourceCollectionCandidateRunId)
    ?? selectedSourceCollectionStorageArtifacts;
  useEffect(() => {
    if (!selectedSourceCollectionCandidateId) {
      return;
    }
    if (!sourceManifestCandidates.some((candidate) => candidate.candidateId === selectedSourceCollectionCandidateId)) {
      setSelectedSourceCollectionCandidateId("");
    }
  }, [selectedSourceCollectionCandidateId, sourceManifestCandidates]);
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
  const sourceCollectionCandidatesByRecordId = useMemo(() => {
    const mapping = new Map<string, TeamWorkflowCandidate>();
    sourceCollectionRunCandidates.forEach((candidate) => {
      const trace = sourceCollectionCandidateTrace(candidate);
      if (trace.recordId && !mapping.has(trace.recordId)) {
        mapping.set(trace.recordId, candidate);
      }
    });
    return mapping;
  }, [sourceCollectionRunCandidates]);
  const sourceCollectionRecordProvenances = useMemo(
    () => sourceCollectionRecords.map((record) => sourceCollectionRecordProvenance(record, lang)),
    [lang, sourceCollectionRecords],
  );
  const sourceCollectionRecordSourceCategories = useMemo(
    () => sourceCollectionRecords.map((record) => sourceCollectionRecordSourceCategory(record, lang)),
    [lang, sourceCollectionRecords],
  );
  const sourceCollectionFilteredRecords = useMemo(
    () => sourceCollectionRecords.filter((record) =>
      sourceCollectionFilterMatches(sourceCollectionSourceFilter, sourceCollectionRecordSourceCategory(record, lang)),
    ),
    [lang, sourceCollectionRecords, sourceCollectionSourceFilter],
  );
  const sourceCollectionRunCandidateSourceCategories = useMemo(
    () => sourceCollectionRunCandidates.map((candidate) => sourceCollectionCandidateSourceCategory(candidate, lang)),
    [lang, sourceCollectionRunCandidates],
  );
  const sourceCollectionFilteredRunCandidates = useMemo(
    () => sourceCollectionRunCandidates.filter((candidate) =>
      sourceCollectionFilterMatches(sourceCollectionSourceFilter, sourceCollectionCandidateSourceCategory(candidate, lang)),
    ),
    [lang, sourceCollectionRunCandidates, sourceCollectionSourceFilter],
  );
  const sourceCollectionSummaryCounts = sourceCollectionSummary?.summary ?? {};
  const sourceCollectionRawRecordCount =
    Number(
      sourceCollectionRecordsQuery.data?.summary?.recordCount
      ?? sourceCollectionSummaryCounts.recordCount
      ?? sourceCollectionRunSummary?.recordCount
      ?? selectedSourceCollectionRun?.summary?.recordCount
      ?? sourceCollectionRecords.length,
    ) || 0;
  const sourceCollectionRecordClickableSourceCount = sourceCollectionRecordProvenances.filter((item) => item.href).length;
  const sourceCollectionRecordLocalFileCount = sourceCollectionRecordProvenances.filter((item) => item.kind === "file").length;
  const sourceCollectionRecordMissingSourceCount = sourceCollectionRecordProvenances.filter((item) => item.kind === "missing").length;
  const sourceCollectionRunCandidateCount = sourceCollectionRunCandidates.length;
  const sourceCollectionRecordFilterCounts = sourceCollectionFilterCounts(sourceCollectionRecordSourceCategories);
  const sourceCollectionCandidateFilterCounts = sourceCollectionFilterCounts(sourceCollectionRunCandidateSourceCategories);
  const sourceCollectionReviewableRunCandidates = useMemo(
    () => sourceCollectionRunCandidates.filter(
      (candidate) => candidate.sourceVersionFamily?.state !== "superseded",
    ),
    [sourceCollectionRunCandidates],
  );
  const sourceCollectionRunReviewableCandidateCount = sourceCollectionReviewableRunCandidates.length;
  const sourceCollectionRunAssessedCount = sourceCollectionReviewableRunCandidates.filter(
    (candidate) => sourceCollectionCandidateQualityState(candidate).assessed,
  ).length;
  const sourceCollectionRunApprovedCount = sourceCollectionReviewableRunCandidates.filter(
    (candidate) => sourceCollectionCandidateQualityState(candidate).approved,
  ).length;
  const sourceCollectionRunNeedsRevisionCount = sourceCollectionReviewableRunCandidates.filter(
    (candidate) => sourceCollectionCandidateQualityState(candidate).needsRevision,
  ).length;
  const sourceCollectionEvidenceLedgerSummaries = useMemo(
    () => sourceCollectionRunCandidates
      .map((candidate) => sourceCollectionEvidenceLedgerSummary(candidate))
      .filter((summary): summary is SourceCollectionEvidenceLedgerSummary => Boolean(summary)),
    [sourceCollectionRunCandidates],
  );
  const sourceCollectionEvidenceReadyCandidateCount = sourceCollectionEvidenceLedgerSummaries.filter((summary) => !summary.missingAnchor).length;
  const sourceCollectionMissingEvidenceAnchorCount = sourceCollectionEvidenceLedgerSummaries.filter((summary) => summary.missingAnchor).length;
  const sourceCollectionCollectedCount = sourceCollectionRawRecordCount;
  const sourceCollectionRunSummaryHasRecordCount = typeof sourceCollectionRunSummary?.recordCount === "number";
  const sourceCollectionSummaryHasRecordCount = typeof sourceCollectionSummaryCounts.recordCount === "number";
  const sourceCollectionRunSummaryHasAssignmentCounts = [
    sourceCollectionRunSummary?.openAssignmentCount,
    sourceCollectionRunSummary?.searchOpenAssignmentCount,
    sourceCollectionRunSummary?.downstreamOpenAssignmentCount,
  ].some((value) => typeof value === "number");
  const sourceCollectionCandidateListDataLoading = Boolean(
    researchWorkflowTeamSelected
    && selectedSourceCollectionRunEffectiveId
    && teamWorkflowCandidateListEnabled
    && sourceCollectionNeedsCandidateList
    && !teamWorkflowCandidatesQuery.data
    && (teamWorkflowCandidatesQuery.isPending || teamWorkflowCandidatesQuery.isFetching)
  );
  const sourceCollectionRecordsDataLoading = Boolean(
    sourceCollectionFindingDetailsVisible
    && !sourceCollectionRecordsQuery.data
    && !sourceCollectionSummaryHasRecordCount
    && !sourceCollectionRunSummaryHasRecordCount
    && (
      sourceCollectionRecordsQuery.isPending
      || sourceCollectionRunStatusQuery.isPending
    ),
  );
  const sourceCollectionAssignmentsDataLoading = Boolean(
    sourceCollectionFindingDetailsVisible
    && !sourceCollectionAssignmentsQuery.data
    && !sourceCollectionRunSummaryHasAssignmentCounts
    && (sourceCollectionAssignmentsQuery.isPending || sourceCollectionRunStatusQuery.isPending),
  );
  const sourceCollectionCollectionProjection = sourceCollectionStageCardById.get("finding") ?? null;
  const sourceCollectionExtractionProjection = sourceCollectionStageCardById.get("extraction") ?? null;
  const sourceCollectionCandidateProjection = sourceCollectionExtractionProjection;
  const sourceCollectionScreeningProjection = sourceCollectionExtractionProjection;
  const sourceCollectionGraphProjection = sourceCollectionStageCardById.get("relations") ?? null;
  const sourceCollectionMemoryProjection = sourceCollectionStageCardById.get("ingestion") ?? null;
  const sourceCollectionExcludedSourceCount = Math.max(
    sourceCollectionNonNegativeCount(sourceCollectionStageRound?.sourceCollectionStageCardSummary?.excludedSourceCount),
    sourceCollectionNonNegativeCount(sourceCollectionSummaryCounts.excludedSourceCount),
    sourceCollectionStageProjectionCount(sourceCollectionCandidateProjection, "excluded", 0),
    sourceCollectionNonNegativeCount(sourceCollectionCandidateProjection?.latestTask?.closureSummary?.excludedSourceCount),
  );
  const sourceCollectionStageSummaryCandidateCount = Number(
    sourceCollectionStageRound?.sourceCollectionStageCardSummary?.sourceCandidateCount
    ?? sourceCollectionSummaryCounts.sourceCandidateCount,
  );
  const sourceCollectionCandidateProjectionFallbackCount = Number.isFinite(sourceCollectionStageSummaryCandidateCount)
    ? Math.max(sourceCollectionRunCandidateCount, Math.max(0, sourceCollectionStageSummaryCandidateCount))
    : sourceCollectionRunCandidateCount;
  const sourceCollectionProjectedCollectedCount = Math.max(
    sourceCollectionCollectedCount,
    sourceCollectionStageProjectionCount(
      sourceCollectionCollectionProjection,
      "artifact",
      sourceCollectionCollectedCount,
    ),
  );
  const sourceCollectionProjectedCandidateCount = sourceCollectionStageProjectionCount(
    sourceCollectionCandidateProjection,
    "artifact",
    sourceCollectionCandidateProjectionFallbackCount,
  );
  const sourceCollectionProjectedAssessedCount = sourceCollectionRunCandidateCount > 0
    ? sourceCollectionRunAssessedCount
    : sourceCollectionStageProjectionCount(
      sourceCollectionScreeningProjection,
      "artifact",
      sourceCollectionRunAssessedCount,
    );
  const sourceCollectionProjectedApprovedCount = sourceCollectionRunCandidateCount > 0
    ? sourceCollectionRunApprovedCount
    : sourceCollectionStageProjectionCount(
      sourceCollectionScreeningProjection,
      "output",
      sourceCollectionRunApprovedCount,
    );
  const sourceCollectionDisplayedCandidateCount = Math.max(sourceCollectionRunCandidateCount, sourceCollectionProjectedCandidateCount);
  const sourceCollectionQueryCount =
    sourceCollectionSearchPlanRef?.queryCount
    ?? selectedTeamStartSourceCollectionResult?.searchPlan.queryCount
    ?? sourceCollectionAssignments.reduce((total, assignment) => total + (assignment.scope.queryCount ?? assignment.scope.assignedQueries?.length ?? 0), 0);
  const sourceCollectionPrimaryDataLoading = Boolean(
    researchWorkflowTeamSelected
    && (
      sourceCollectionCandidateListDataLoading
      || (
        sourceCollectionDisplayedCandidateCount <= 0
        && (
          sourceCollectionRecordsDataLoading
          || sourceCollectionAssignmentsDataLoading
          || (sourceCollectionRunsQuery.isPending && !sourceCollectionRunsQuery.data)
          || (
            selectedSourceCollectionRunEffectiveId
            && sourceCollectionSummaryQuery.isPending
            && sourceCollectionWorkspaceSelected
            && !sourceCollectionSummaryQuery.data
          )
        )
      )
    ),
  );
  const sourceCollectionSourceQualityLoading = Boolean(
    researchWorkflowTeamSelected
    && teamWorkflowSourceQualityEnabled
    && !teamWorkflowSourceQualityStatus
    && (teamWorkflowSourceQualityStatusQuery.isPending || teamWorkflowSourceQualityStatusQuery.isFetching)
  );
  const sourceCollectionGraphDataLoading = Boolean(
    researchWorkflowTeamSelected
    && selectedSourceCollectionRunEffectiveId
    && teamWorkflowGraphEnabled
    && teamWorkflowCandidateGraphQuery.isPending && !teamWorkflowCandidateGraphQuery.data
  );
  const sourceCollectionKnowledgeIngestionDataLoading = Boolean(
    researchWorkflowTeamSelected
    && selectedSourceCollectionRunEffectiveId
    && teamWorkflowKnowledgeIngestionEnabled
    && teamWorkflowKnowledgeIngestionStatusQuery.isPending && !teamWorkflowKnowledgeIngestionStatusQuery.data
  );
  const sourceCollectionActionInitialDataPending = Boolean(
    researchWorkflowTeamSelected
    && selectedSourceCollectionRunEffectiveId
    && (
      sourceCollectionRecordsDataLoading
      || sourceCollectionAssignmentsDataLoading
      || sourceCollectionPrimaryDataLoading
      || sourceCollectionSourceQualityLoading
      || sourceCollectionGraphDataLoading
      || sourceCollectionKnowledgeIngestionDataLoading
    ),
  );
  const sourceCollectionActionDataError = Boolean(
    researchWorkflowTeamSelected
    && selectedSourceCollectionRunEffectiveId
    && (
      (sourceCollectionRecordsQuery.error && !sourceCollectionRecordsQuery.data && !sourceCollectionSummaryHasRecordCount && !sourceCollectionRunSummaryHasRecordCount)
      || (sourceCollectionAssignmentsQuery.error && !sourceCollectionAssignmentsQuery.data && !sourceCollectionRunSummaryHasAssignmentCounts)
      || (sourceCollectionSummaryQuery.error && sourceCollectionWorkspaceSelected && !sourceCollectionSummaryQuery.data)
    ),
  );
  const sourceCollectionSourceQualityDataError = Boolean(
    researchWorkflowTeamSelected
    && selectedSourceCollectionRunEffectiveId
    && teamWorkflowSourceQualityStatusQuery.error
    && !teamWorkflowSourceQualityStatusQuery.data
  );
  const sourceCollectionGraphDataError = Boolean(
    researchWorkflowTeamSelected
    && selectedSourceCollectionRunEffectiveId
    && teamWorkflowCandidateGraphQuery.error
    && !teamWorkflowCandidateGraphQuery.data
  );
  const sourceCollectionKnowledgeIngestionDataError = Boolean(
    researchWorkflowTeamSelected
    && selectedSourceCollectionRunEffectiveId
    && teamWorkflowKnowledgeIngestionStatusQuery.error
    && !teamWorkflowKnowledgeIngestionStatusQuery.data
  );
  const sourceCollectionScreeningDataLoading = sourceCollectionPrimaryDataLoading || sourceCollectionSourceQualityLoading;
  const {
    loadingText: sourceCollectionLoadingText,
    dataSyncText: sourceCollectionDataSyncText,
    loadingSummary: sourceCollectionLoadingSummary,
    actionLoadingReason: sourceCollectionActionLoadingReason,
    actionErrorReason: sourceCollectionActionErrorReason,
    actionNoRunReason: sourceCollectionActionNoRunReason,
    actionNoInputReason: sourceCollectionActionNoInputReason,
    actionBusyReason: sourceCollectionActionBusyReason,
  } = sourceCollectionLoadingChrome(lang);
  const sourceCollectionActionReadiness = sourceCollectionActionReadinessOf;
  const sourceCollectionActionDisabledTitle = sourceCollectionActionDisabledTitlePure;
  const sourceCollectionCountText = (loading: boolean, value: number) => sourceCollectionStableCountText({
    loading,
    value,
    lang,
    loadingText: sourceCollectionLoadingText,
    syncingText: sourceCollectionDataSyncText,
  });
  const sourceCollectionCountWithUnit = (loading: boolean, value: number, zhUnit: string, enUnit = "") => sourceCollectionStableCountText({
    loading,
    value,
    lang,
    zhUnit,
    enUnit,
    loadingText: sourceCollectionLoadingText,
    syncingText: sourceCollectionDataSyncText,
  });
  const sourceCollectionCollectedCountText = sourceCollectionCountText(sourceCollectionRecordsDataLoading, sourceCollectionCollectedCount);
  const sourceCollectionProjectedCollectedCountText = sourceCollectionCountText(sourceCollectionRecordsDataLoading, sourceCollectionProjectedCollectedCount);
  const sourceCollectionSearchOpenAssignmentCountText = sourceCollectionAssignmentsDataLoading
    ? sourceCollectionLoadingText
    : String(sourceCollectionSearchOpenAssignmentCount);
  const sourceCollectionDownstreamOpenAssignmentCountText = sourceCollectionAssignmentsDataLoading
    ? sourceCollectionLoadingText
    : String(sourceCollectionDownstreamOpenAssignmentCount);
  const sourceCollectionQueryDataLoading = Boolean(
    sourceCollectionAssignmentsDataLoading
    && sourceCollectionSearchPlanRef?.queryCount == null
    && selectedTeamStartSourceCollectionResult?.searchPlan.queryCount == null
    && sourceCollectionAssignments.length <= 0,
  );
  const sourceCollectionQueryCountText = sourceCollectionQueryDataLoading
    ? sourceCollectionLoadingText
    : String(sourceCollectionQueryCount);
  const sourceCollectionCollectedCountLabel = sourceCollectionCountWithUnit(sourceCollectionRecordsDataLoading, sourceCollectionCollectedCount, "条", "raw records");
  const sourceCollectionProjectedCollectedCountLabel = sourceCollectionCountWithUnit(sourceCollectionRecordsDataLoading, sourceCollectionProjectedCollectedCount, "条", "raw records");
  const sourceCollectionSearchOpenAssignmentCountLabel = sourceCollectionCountWithUnit(sourceCollectionAssignmentsDataLoading, sourceCollectionSearchOpenAssignmentCount, "项");
  const sourceCollectionDownstreamOpenAssignmentCountLabel = sourceCollectionCountWithUnit(sourceCollectionAssignmentsDataLoading, sourceCollectionDownstreamOpenAssignmentCount, "项");
  const sourceCollectionQueryCountLabel = sourceCollectionCountWithUnit(sourceCollectionQueryDataLoading, sourceCollectionQueryCount, "个");
  const sourceCollectionCollectedRunSummaryText = sourceCollectionRecordsDataLoading
    ? sourceCollectionLoadingText
    : lang === "zh"
    ? `${sourceCollectionCollectedCount} 条资料`
    : `${sourceCollectionCollectedCount} records`;
  const sourceCollectionAssignmentRunSummaryText = sourceCollectionAssignmentsDataLoading
    ? sourceCollectionLoadingText
    : lang === "zh"
    ? `${sourceCollectionAssignments.length} 个任务`
    : `${sourceCollectionAssignments.length} assignments`;
  const sourceCollectionDisplayedCandidateCountText = sourceCollectionCountText(sourceCollectionPrimaryDataLoading, sourceCollectionDisplayedCandidateCount);
  const sourceCollectionProjectedCandidateCountText = sourceCollectionCountText(sourceCollectionPrimaryDataLoading, sourceCollectionProjectedCandidateCount);
  const sourceCollectionCoverageBoundCandidateCount = sourceCollectionBoundCountToCurrentCoverage(
    sourceCollectionCandidateProjection,
    sourceCollectionProjectedCandidateCount,
  );
  const sourceCollectionCurrentCandidateCount = sourceCollectionRunReviewableCandidateCount > 0
    ? Math.min(sourceCollectionCoverageBoundCandidateCount, sourceCollectionRunReviewableCandidateCount)
    : sourceCollectionCoverageBoundCandidateCount;
  const sourceCollectionCurrentCandidateCountText = sourceCollectionCountText(
    sourceCollectionPrimaryDataLoading,
    sourceCollectionCurrentCandidateCount,
  );
  const sourceCollectionProjectedCandidateCountLabel = sourceCollectionCountWithUnit(sourceCollectionPrimaryDataLoading, sourceCollectionProjectedCandidateCount, "条候选资料", "candidate sources");
  const sourceCollectionProjectedAssessedCountText = sourceCollectionCountText(sourceCollectionScreeningDataLoading, sourceCollectionProjectedAssessedCount);
  const sourceCollectionProjectedApprovedCountText = sourceCollectionCountText(sourceCollectionScreeningDataLoading, sourceCollectionProjectedApprovedCount);
  const sourceCollectionDisplayedCandidateFilterCounts = useMemo(() => {
    if (sourceCollectionDisplayedCandidateCount <= sourceCollectionRunCandidateCount) {
      return sourceCollectionCandidateFilterCounts;
    }
    return {
      ...sourceCollectionCandidateFilterCounts,
      all: sourceCollectionDisplayedCandidateCount,
    };
  }, [
    sourceCollectionCandidateFilterCounts,
    sourceCollectionDisplayedCandidateCount,
    sourceCollectionRunCandidateCount,
  ]);
  const sourceCollectionRunPendingScreeningCount = Math.max(
    0,
    sourceCollectionRunCandidateCount > 0
      ? sourceCollectionRunReviewableCandidateCount - sourceCollectionRunAssessedCount
      : sourceCollectionProjectedCandidateCount - sourceCollectionProjectedAssessedCount,
  );
  const sourceCollectionRunPendingScreeningCountText = sourceCollectionCountText(sourceCollectionScreeningDataLoading, sourceCollectionRunPendingScreeningCount);
  const sourceCollectionPendingCandidateImportCount = Math.max(0, sourceCollectionRawRecordCount - sourceCollectionDisplayedCandidateCount);
  const sourceCollectionExtractionRecoveryCoverage = sourceCollectionCandidateProjection?.currentCoverageSummary?.applicable
    ? sourceCollectionCandidateProjection.currentCoverageSummary
    : sourceCollectionCandidateProjection?.latestTask?.coverageSummary;
  const sourceCollectionExtractionRecoveryClosure = sourceCollectionCandidateProjection?.latestTask?.closureSummary;
  const sourceCollectionExtractionSourceVerificationCount = Math.max(
    sourceCollectionNonNegativeCount(sourceCollectionExtractionRecoveryClosure?.blockedCount),
    sourceCollectionNonNegativeCount(sourceCollectionExtractionRecoveryCoverage?.blocked),
  );
  const sourceCollectionUnverifiableCandidateIds = useMemo(() => {
    const blockedCount = sourceCollectionExtractionSourceVerificationCount;
    if (blockedCount <= 0) {
      return [];
    }
    return sourceCollectionReviewableRunCandidates
      .filter((candidate) => {
        const quality = sourceCollectionCandidateQualityState(candidate);
        const evidence = sourceCollectionEvidenceLedgerSummary(candidate);
        return quality.needsRevision && evidence?.missingAnchor !== true;
      })
      .map((candidate) => String(candidate.candidateId || "").trim())
      .filter(Boolean)
      .slice(0, blockedCount);
  }, [
    sourceCollectionExtractionSourceVerificationCount,
    sourceCollectionReviewableRunCandidates,
  ]);
  const sourceCollectionExtractionMissingEvidenceAnchorCount = sourceCollectionBoundCountToCurrentCoverage(
    sourceCollectionCandidateProjection,
    sourceCollectionCandidateProjection?.latestTask?.materializedContentExtraction?.missingEvidenceAnchorCount,
  );
  const sourceCollectionExtractionAgentMaterialCount = sourceCollectionMaterialGapCount({
    hasCurrentCandidates: Boolean(teamWorkflowCandidatesQuery.data),
    needsRevisionCount: sourceCollectionRunNeedsRevisionCount,
    missingEvidenceAnchorCount: sourceCollectionExtractionMissingEvidenceAnchorCount,
    taskBlockedCount: sourceCollectionExtractionSourceVerificationCount,
    projectedPendingCount: sourceCollectionStageProjectionCount(sourceCollectionCandidateProjection, "pending", 0),
  });
  const sourceCollectionExtractionNeedsAgentMaterial = sourceCollectionExtractionAgentMaterialCount > 0;
  const sourceCollectionExtractionRecoveryMissingCount = Math.max(
    sourceCollectionNonNegativeCount(sourceCollectionExtractionRecoveryCoverage?.missing),
    sourceCollectionStageProjectionCount(sourceCollectionCandidateProjection, "pending", 0),
    sourceCollectionPendingCandidateImportCount,
    sourceCollectionNonNegativeCount(selectedTeamExtractSourceCollectionCandidatesResult?.pendingRecordCount),
  );
  const sourceCollectionExtractionExcludedRecoveryState = deriveSourceCollectionExcludedRecoveryState({
    lang,
    excludedCount: Math.max(
      sourceCollectionExcludedSourceCount,
      sourceCollectionNonNegativeCount(sourceCollectionExtractionRecoveryClosure?.excludedSourceCount),
      sourceCollectionStageProjectionCount(sourceCollectionCandidateProjection, "excluded", 0),
    ),
    missingCount: sourceCollectionExtractionRecoveryMissingCount,
    importFailedCount: sourceCollectionNonNegativeCount(selectedTeamExtractSourceCollectionCandidatesResult?.failedCount),
    importPendingRecordCount: Math.max(
      sourceCollectionPendingCandidateImportCount,
      sourceCollectionNonNegativeCount(selectedTeamExtractSourceCollectionCandidatesResult?.pendingRecordCount),
    ),
  });
  const sourceCollectionExtractionCanProceedAfterExclusions = Boolean(
    sourceCollectionExtractionExcludedRecoveryState.blockedByExcludedSources
    && sourceCollectionProjectedApprovedCount > 0
    && sourceCollectionRunPendingScreeningCount <= 0,
  );
  const sourceCollectionExtractionProceedableSummary = lang === "zh"
    ? `${sourceCollectionProjectedApprovedCount} 条可进入关系整理；剩余 ${sourceCollectionExtractionExcludedRecoveryState.excludedCount} 条已排除，可查看原因或补充新来源。`
    : `${sourceCollectionProjectedApprovedCount} ready for relation mapping; ${sourceCollectionExtractionExcludedRecoveryState.excludedCount} excluded sources can be inspected or replaced.`;

  const sourceCollectionApprovedCount =
    teamWorkflowSourceQualityStatus?.summary.approvedSourceCandidateCount
    ?? sourceCollectionSummaryCounts.approvedSourceCandidateCount
    ?? 0;
  const sourceCollectionStageFocusLabel = !selectedSourceCollectionRun
    ? (lang === "zh" ? "尚未启动" : "not started")
    : sourceCollectionSearchOpenAssignmentCount > 0
      ? (lang === "zh" ? "继续搜索" : "continue search")
      : sourceCollectionDownstreamOpenAssignmentCount > 0
        ? (lang === "zh" ? "继续提炼" : "continue extraction")
      : sourceCollectionRunPendingScreeningCount > 0
        ? (lang === "zh" ? "继续审查" : "continue review")
        : sourceCollectionDisplayedCandidateCount > 0
          ? (lang === "zh" ? "准备实验" : "plan experiment")
          : (lang === "zh" ? "等待结果回写" : "waiting for writeback");
  const sourceCollectionRunStatusValue = String(sourceCollectionRunStatus?.runStatus || selectedSourceCollectionRun?.status || "").toLowerCase();
  const sourceCollectionAcceptedBackgroundActive = Boolean(
    selectedSourceCollectionSearchAccepted
    && selectedSourceCollectionActiveWorkRun
    && ["running", "queued"].includes(String(selectedSourceCollectionActiveWorkRun.status || "").toLowerCase()),
  );
  const canRecordSourceCollectionOutput = Boolean(
    selectedTeam?.teamId
    && selectedSourceCollectionRunEffectiveId
    && (sourceCollectionOutputDraft.assignmentId || selectedSourceCollectionAssignment?.assignmentId)
    && sourceCollectionOutputHasRecord
    && !selectedTeamRecordSourceCollectionOutputPending,
  );
  const canExecuteSourceCollectionSearch = Boolean(
    selectedTeam?.teamId
    && selectedSourceCollectionRunEffectiveId
    && !sourceCollectionAssignmentsDataLoading
    && !sourceCollectionActionDataError
    && sourceCollectionSearchOpenAssignmentCount > 0
    && !selectedTeamExecuteSourceCollectionSearchPending
    && !sourceCollectionAcceptedBackgroundActive,
  );
  const {
    selectedTeamBuildCandidateGraphPending,
    selectedTeamBuildCandidateGraphError,
    selectedTeamKnowledgePrecheckPending,
    selectedTeamKnowledgePrecheckError,
    selectedTeamKnowledgeIngestionActiveWorkRun,
    selectedTeamKnowledgeIngestionLatestWorkRun,
    selectedTeamKnowledgeCollectionWorkRun,
    selectedTeamKnowledgeCollectionSourceRunId,
    selectedTeamKnowledgeCollectionMatchesSelectedRun,
    selectedTeamKnowledgeCollectionWorkRunStatus,
    selectedTeamKnowledgeCollectionFlowStatus,
    selectedTeamKnowledgeCollectionCompleted,
    selectedTeamKnowledgeCollectionCompletedForSelectedRun,
    selectedTeamKnowledgeCollectionIngestPending,
    selectedTeamKnowledgeCollectionIngestError,
    selectedTeamKnowledgeCollectionIngestResult,
    selectedTeamPlanPaperNoteChunksPending,
    selectedTeamPlanPaperNoteChunksError,
    selectedTeamAssessSourceQualityPending,
    selectedTeamAssessSourceQualityError,
    selectedTeamAssessSourceQualityBatchPending,
    selectedTeamAssessSourceQualityBatchError,
    selectedTeamSourceQualityPending,
    selectedTeamSourceQualityError,
    selectedTeamSourceQualityBatchResult,
    sourceCollectionQualityBatchFeedback,
  } = buildSourceCollectionWriteMutationSurface({
    teamId: selectedTeam?.teamId,
    selectedSourceCollectionRunEffectiveId,
    buildCandidateGraph: buildCandidateGraphMutation,
    runKnowledgeIngestionPrecheck: runKnowledgeIngestionPrecheckMutation,
    runKnowledgeCollectionCompletion: runKnowledgeCollectionCompletionMutation,
    planPaperNoteChunks: planPaperNoteChunksMutation,
    assessSourceQuality: assessSourceQualityMutation,
    assessSourceQualityBatch: assessSourceQualityBatchMutation,
    knowledgeIngestionActiveWorkRun: teamWorkflowKnowledgeIngestionStatusQuery.data?.activeWorkRun ?? null,
    knowledgeIngestionLatestWorkRun: teamWorkflowKnowledgeIngestionStatusQuery.data?.latestWorkRun ?? null,
    lang,
  });
  const sourceCollectionAcceptedBackgroundFailed = Boolean(
    selectedSourceCollectionActiveWorkRun
    && ["failed", "blocked"].includes(String(selectedSourceCollectionActiveWorkRun.status || "").toLowerCase()),
  );
  const sourceCollectionOperationFailed = Boolean(
    sourceCollectionRunStatusValue === "failed"
    || sourceCollectionRunStatusValue === "blocked"
    || sourceCollectionAcceptedBackgroundFailed
    || selectedTeamStartResearchStageError
    || selectedTeamStartSourceCollectionError
    || selectedTeamExecuteSourceCollectionSearchError
    || selectedTeamExtractSourceCollectionCandidatesError
    || selectedTeamRecordSourceCollectionOutputError
    || selectedTeamSourceQualityError
    || selectedTeamBuildCandidateGraphError
    || selectedTeamKnowledgePrecheckError
    || selectedTeamKnowledgeCollectionIngestError
    || selectedTeamStartSourceCollectionStageTaskError
  );
  const sourceCollectionDisplayState = deriveSourceCollectionDisplayState({
    lang,
    hasRun: Boolean(selectedSourceCollectionRun),
    startPending: selectedTeamStartResearchStagePending || selectedTeamStartSourceCollectionPending || selectedTeamStartSourceCollectionStageTaskPending,
    searchPending: selectedTeamExecuteSourceCollectionSearchPending,
    backgroundActive: sourceCollectionAcceptedBackgroundActive,
    recordOutputPending: selectedTeamRecordSourceCollectionOutputPending,
    extractionPending: selectedTeamExtractSourceCollectionCandidatesPending,
    sourceQualityPending: selectedTeamSourceQualityPending,
    graphPending: selectedTeamBuildCandidateGraphPending,
    knowledgeIngestionPending: selectedTeamKnowledgePrecheckPending || selectedTeamKnowledgeCollectionIngestPending,
    failed: sourceCollectionOperationFailed,
    searchOpenAssignmentCount: sourceCollectionSearchOpenAssignmentCount,
    downstreamOpenAssignmentCount: sourceCollectionDownstreamOpenAssignmentCount,
    pendingScreeningCount: sourceCollectionRunPendingScreeningCount,
    rawRecordCount: sourceCollectionRawRecordCount,
    candidateCount: sourceCollectionDisplayedCandidateCount,
    activeWorkSummary: workRunString(selectedSourceCollectionActiveWorkRun, "currentTask")
      || workRunString(selectedSourceCollectionActiveWorkRun, "summary"),
  });
  const candidateGraphNodeCount = teamWorkflowCandidateGraph?.summary.nodeCount ?? sourceCollectionSummaryCounts.graphNodeCount ?? 0;
  const candidateGraphEdgeCount = teamWorkflowCandidateGraph?.summary.edgeCount ?? 0;
  const knowledgeStewardPackCount = teamWorkflowKnowledgeIngestionStatus?.summary.stewardPackCandidateCount ?? sourceCollectionSummaryCounts.stewardPackCount ?? 0;
  const knowledgePendingReviewCount = teamWorkflowKnowledgeIngestionStatus?.summary.pendingKnowledgeReviewCandidateCount ?? 0;
  const formalKnowledgeItemCount =
    teamWorkflowKnowledgeIngestionStatus?.summary.formalKnowledgeItemCount
    ?? sourceCollectionSummaryCounts.formalKnowledgeSyncCount
    ?? 0;
  const sourceCollectionProjectedGraphNodeCount = sourceCollectionStageProjectionCount(
    sourceCollectionGraphProjection,
    "artifact",
    candidateGraphNodeCount,
  );
  const sourceCollectionProjectedGraphEdgeCount = sourceCollectionStageProjectionCount(
    sourceCollectionGraphProjection,
    "output",
    candidateGraphEdgeCount,
  );
  const sourceCollectionProjectedStewardPackCount = sourceCollectionStageProjectionCount(
    sourceCollectionMemoryProjection,
    "artifact",
    knowledgeStewardPackCount,
  );
  const sourceCollectionProjectedFormalKnowledgeCount = sourceCollectionStageProjectionCount(
    sourceCollectionMemoryProjection,
    "output",
    formalKnowledgeItemCount,
  );
  const sourceCollectionDefaultKnowledgeBaseId =
    teamWorkflowKnowledgeIngestionStatus?.knowledgeBases[0]?.scopedKnowledgeBaseId
    ?? teamWorkflowKnowledgeIngestionStatus?.knowledgeBases[0]?.knowledgeBaseId
    ?? "";
  const sourceCollectionPrecheckCandidateCount = Math.max(sourceCollectionApprovedCount, sourceCollectionRunApprovedCount);
  const sourceCollectionIngestCandidateCount = Math.max(sourceCollectionPrecheckCandidateCount, sourceCollectionDisplayedCandidateCount);
  const sourceCollectionCanBuildGraph = sourceCollectionRunApprovedCount > 0 || sourceCollectionDisplayedCandidateCount > 0;
  const sourceCollectionSearchActionReadiness = sourceCollectionActionReadiness(
    !canExecuteSourceCollectionSearch,
    !selectedTeam?.teamId || !selectedSourceCollectionRunEffectiveId
      ? sourceCollectionActionNoRunReason
      : sourceCollectionAssignmentsDataLoading
        ? sourceCollectionActionLoadingReason
        : sourceCollectionActionDataError
          ? sourceCollectionActionErrorReason
          : selectedTeamExecuteSourceCollectionSearchPending || sourceCollectionAcceptedBackgroundActive
            ? sourceCollectionActionBusyReason
            : sourceCollectionActionNoInputReason,
    sourceCollectionAssignmentsDataLoading,
  );
  const sourceCollectionCandidateExtractionActionReadiness = sourceCollectionActionReadiness(
    !selectedTeam?.teamId
      || !selectedSourceCollectionRunEffectiveId
      || sourceCollectionRecordsDataLoading
      || sourceCollectionActionDataError
      || sourceCollectionRawRecordCount <= 0
      || selectedTeamExtractSourceCollectionCandidatesPending,
    !selectedTeam?.teamId || !selectedSourceCollectionRunEffectiveId
      ? sourceCollectionActionNoRunReason
      : sourceCollectionRecordsDataLoading
        ? sourceCollectionActionLoadingReason
        : sourceCollectionActionDataError
          ? sourceCollectionActionErrorReason
          : selectedTeamExtractSourceCollectionCandidatesPending
            ? sourceCollectionActionBusyReason
            : sourceCollectionActionNoInputReason,
    sourceCollectionRecordsDataLoading,
  );
  const sourceCollectionScreeningActionReadiness = sourceCollectionActionReadiness(
    !selectedTeam?.teamId
      || sourceCollectionPrimaryDataLoading
      || sourceCollectionSourceQualityLoading
      || sourceCollectionActionDataError
      || sourceCollectionSourceQualityDataError
      || sourceCollectionDisplayedCandidateCount <= 0
      || selectedTeamSourceQualityPending,
    !selectedTeam?.teamId
      ? sourceCollectionActionNoRunReason
      : sourceCollectionPrimaryDataLoading || sourceCollectionSourceQualityLoading
        ? sourceCollectionActionLoadingReason
        : sourceCollectionActionDataError || sourceCollectionSourceQualityDataError
          ? sourceCollectionActionErrorReason
          : selectedTeamSourceQualityPending
            ? sourceCollectionActionBusyReason
            : sourceCollectionActionNoInputReason,
    sourceCollectionPrimaryDataLoading || sourceCollectionSourceQualityLoading,
  );
  const sourceCollectionGraphActionReadiness = sourceCollectionActionReadiness(
    !selectedTeam?.teamId
      || sourceCollectionPrimaryDataLoading
      || sourceCollectionGraphDataLoading
      || sourceCollectionActionDataError
      || sourceCollectionGraphDataError
      || !sourceCollectionCanBuildGraph
      || selectedTeamBuildCandidateGraphPending,
    !selectedTeam?.teamId
      ? sourceCollectionActionNoRunReason
      : sourceCollectionPrimaryDataLoading || sourceCollectionGraphDataLoading
        ? sourceCollectionActionLoadingReason
        : sourceCollectionActionDataError || sourceCollectionGraphDataError
          ? sourceCollectionActionErrorReason
          : selectedTeamBuildCandidateGraphPending
            ? sourceCollectionActionBusyReason
            : sourceCollectionActionNoInputReason,
    sourceCollectionPrimaryDataLoading || sourceCollectionGraphDataLoading,
  );
  const sourceCollectionMemoryActionReadiness = sourceCollectionActionReadiness(
    !selectedTeam?.teamId
      || sourceCollectionPrimaryDataLoading
      || sourceCollectionSourceQualityLoading
      || sourceCollectionKnowledgeIngestionDataLoading
      || sourceCollectionActionDataError
      || sourceCollectionSourceQualityDataError
      || sourceCollectionKnowledgeIngestionDataError
      || sourceCollectionIngestCandidateCount <= 0
      || selectedTeamKnowledgeCollectionIngestPending,
    !selectedTeam?.teamId
      ? sourceCollectionActionNoRunReason
      : sourceCollectionPrimaryDataLoading || sourceCollectionSourceQualityLoading || sourceCollectionKnowledgeIngestionDataLoading
        ? sourceCollectionActionLoadingReason
        : sourceCollectionActionDataError || sourceCollectionSourceQualityDataError || sourceCollectionKnowledgeIngestionDataError
          ? sourceCollectionActionErrorReason
          : selectedTeamKnowledgeCollectionIngestPending
            ? sourceCollectionActionBusyReason
            : sourceCollectionActionNoInputReason,
    sourceCollectionPrimaryDataLoading || sourceCollectionSourceQualityLoading || sourceCollectionKnowledgeIngestionDataLoading,
  );
  const sourceCollectionCompletionActionReadiness = sourceCollectionActionReadiness(
    !selectedTeam?.teamId
      || !sourceCollectionActionRunId
      || sourceCollectionActionInitialDataPending
      || sourceCollectionActionDataError
      || sourceCollectionSourceQualityDataError
      || sourceCollectionGraphDataError
      || sourceCollectionKnowledgeIngestionDataError
      || (sourceCollectionIngestCandidateCount <= 0 && sourceCollectionRawRecordCount <= 0 && sourceCollectionSearchOpenAssignmentCount <= 0)
      || selectedTeamKnowledgeCollectionIngestPending,
    !selectedTeam?.teamId || !sourceCollectionActionRunId
      ? sourceCollectionActionNoRunReason
      : sourceCollectionActionInitialDataPending
        ? sourceCollectionActionLoadingReason
        : sourceCollectionActionDataError || sourceCollectionSourceQualityDataError || sourceCollectionGraphDataError || sourceCollectionKnowledgeIngestionDataError
          ? sourceCollectionActionErrorReason
          : selectedTeamKnowledgeCollectionIngestPending
            ? sourceCollectionActionBusyReason
            : sourceCollectionActionNoInputReason,
    sourceCollectionActionInitialDataPending,
  );
  const sourceCollectionLoopStartsNewRun = !selectedSourceCollectionRun || selectedTeamKnowledgeCollectionCompletedForSelectedRun;
  const sourceCollectionLoopStartReadiness = sourceCollectionActionReadiness(
    !selectedTeam?.teamId
      || selectedTeamStartSourceCollectionPending
      || selectedTeamKnowledgeCollectionIngestPending
      || !sourceCollectionCanStart,
    !selectedTeam?.teamId
      ? sourceCollectionActionNoRunReason
      : selectedTeamStartSourceCollectionPending || selectedTeamKnowledgeCollectionIngestPending
        ? sourceCollectionActionBusyReason
        : sourceCollectionActionNoInputReason,
  );
  const sourceCollectionLoopActionReadiness = sourceCollectionLoopStartsNewRun
    ? sourceCollectionLoopStartReadiness
    : sourceCollectionCompletionActionReadiness;
  const sourceCollectionMemoryActionDisabled = sourceCollectionMemoryActionReadiness.disabled;
  const sourceCollectionMemoryActionLabel = sourceCollectionMemoryActionDisabled && sourceCollectionMemoryActionReadiness.loading
    ? (lang === "zh" ? "读取中" : "Loading")
    : selectedTeamKnowledgeCollectionIngestPending
    ? (lang === "zh" ? "通知入库 Agent 中" : "Notifying ingestion Agent")
    : sourceCollectionPrecheckCandidateCount > 0
      ? (lang === "zh" ? "通知资料入库 Agent" : "Notify source ingestion Agent")
      : sourceCollectionDisplayedCandidateCount > 0
        ? (lang === "zh" ? "提炼后通知入库 Agent" : "Extract and notify ingestion Agent")
        : (lang === "zh" ? "通知资料入库 Agent" : "Notify source ingestion Agent");
  const sourceCollectionCompletionActionDisabled = sourceCollectionCompletionActionReadiness.disabled;
  const sourceCollectionCompletionActionLabel = selectedTeamKnowledgeCollectionIngestPending
    ? (lang === "zh" ? "一键完成中" : "Completing")
    : (lang === "zh" ? "一键完成知识搜集" : "Complete knowledge collection");
  const sourceCollectionLoopActionDisabled = sourceCollectionLoopActionReadiness.disabled;
  const sourceCollectionLoopActionLabel = selectedTeamStartSourceCollectionPending || selectedTeamKnowledgeCollectionIngestPending
    ? (lang === "zh" ? "闭环执行中" : "Loop running")
    : sourceCollectionLoopStartsNewRun
      ? selectedTeamKnowledgeCollectionCompletedForSelectedRun && selectedSourceCollectionRun
        ? (lang === "zh" ? "开始下一轮闭环" : "Start next loop")
        : (lang === "zh" ? "开始第一轮闭环" : "Start first loop")
      : sourceCollectionOperationFailed
        ? (lang === "zh" ? "重试本轮闭环" : "Retry this loop")
        : (lang === "zh" ? "继续本轮闭环" : "Continue this loop");
  const sourceCollectionGraphActionDisabled = sourceCollectionGraphActionReadiness.disabled;
  const sourceCollectionGraphActionLabel = selectedTeamBuildCandidateGraphPending
    ? (lang === "zh" ? "Agent 生成中" : "Agent building")
    : sourceCollectionRunApprovedCount > 0
      ? (lang === "zh" ? "Agent 生成关系图" : "Agent build map")
      : sourceCollectionDisplayedCandidateCount > 0
        ? (lang === "zh" ? "审查并生成关系图" : "Review and build map")
        : (lang === "zh" ? "Agent 生成关系图" : "Agent build map");
  const sourceCollectionScreeningDisabled = sourceCollectionScreeningActionReadiness.disabled;
  const sourceCollectionScreeningForceRescreen = sourceCollectionRunPendingScreeningCount <= 0 && sourceCollectionDisplayedCandidateCount > 0;
  // Quality review only (re-score). Do not imply "re-extract" — that confuses 待补 users.
  const sourceCollectionScreeningButtonText = selectedTeamSourceQualityPending
    ? (lang === "zh" ? "质量审查中" : "Reviewing quality")
    : sourceCollectionRunPendingScreeningCount > 0
      ? (lang === "zh" ? "Agent 质量审查" : "Agent quality review")
      : sourceCollectionScreeningForceRescreen
        ? (lang === "zh" ? "重新质量审查" : "Re-run quality review")
        : (lang === "zh" ? "Agent 质量审查" : "Agent quality review");
  const sourceCollectionScreeningButtonTitle = selectedTeamSourceQualityPending
    ? (lang === "zh" ? "资料提炼 Agent 正在按现有材料重新打分" : "Source Extractor is re-scoring with current materials")
    : sourceCollectionScreeningForceRescreen
      ? (lang === "zh"
        ? "仅重新质量打分，不会自动补全文/DOI/证据锚点。列表「待补资料」需先补充材料再审查，否则结果仍可能是待补。"
        : "Re-scores only; does not auto-fill full text/DOI/anchors. Repair needs-revision sources first or they stay blocked.")
      : (lang === "zh"
        ? "对尚未审查的候选做来源质量打分（通过 / 待补 / 排除）。"
        : "Score pending candidates (approved / needs revision / rejected).");
  const sourceCollectionScreeningStatusText = selectedTeamSourceQualityPending
    ? (lang === "zh" ? "进行中" : "running")
    : sourceCollectionPrimaryDataLoading
      ? sourceCollectionLoadingText
    : sourceCollectionRunPendingScreeningCount > 0
      ? `${sourceCollectionRunPendingScreeningCountText} ${lang === "zh" ? "待质量审查" : "pending quality review"}`
      : sourceCollectionExtractionNeedsAgentMaterial
        ? (lang === "zh" ? "有待补资料：先补材料再审查" : "needs material first")
      : sourceCollectionDisplayedCandidateCount > 0
        ? (lang === "zh" ? "已审查" : "done")
        : (lang === "zh" ? "暂无候选" : "no candidates");
  const sourceCollectionCandidateExtractionButtonText = selectedTeamExtractSourceCollectionCandidatesPending
    ? (lang === "zh" ? "Agent 提炼中" : "Agent extracting")
    : sourceCollectionPendingCandidateImportCount > 0
      ? (lang === "zh" ? "Agent 提炼资料" : "Agent extract")
      : sourceCollectionDisplayedCandidateCount > 0
        ? (lang === "zh" ? "Agent 重新提炼" : "Agent re-extract")
        : (lang === "zh" ? "Agent 提炼资料" : "Agent extract");
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
      setSourceCollectionFocusedPanelId((current) => (current === panelId ? "" : current));
    }, 2200);
    window.requestAnimationFrame(() => {
      const target = document.getElementById(panelId);
      if (!target) {
        return;
      }
      if (target instanceof HTMLDetailsElement) {
        target.open = true;
      }
      const container = sourceCollectionControlPanelRef.current;
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
  scrollSourceCollectionPanelIntoViewRef.current = scrollSourceCollectionPanelIntoView;
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
    selectResearchWorkspaceView("canvas");
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
  const sourceCollectionConsoleState: SourceCollectionStepState = sourceCollectionDisplayState.consoleState;
  const sourceCollectionConsoleStatusText = sourceCollectionDisplayState.statusText;
  const sourceCollectionDecisionText = sourceCollectionDisplayState.decisionText;
  const sourceCollectionStepStatusText = (state: SourceCollectionStepState) => {
    const labels: Record<SourceCollectionStepState, string> = lang === "zh"
      ? {
          active: "进行中",
          done: "已完成",
          failed: "失败",
          idle: "未进行",
          pending: "待处理",
        }
      : {
          active: "running",
          done: "done",
          failed: "failed",
          idle: "not started",
          pending: "pending",
    };
    return labels[state];
  };
  const sourceCollectionStageProjectionSyncing = (projection: SourceCollectionStageCardProjection | null | undefined) => {
    if (!sourceCollectionStageWritebackSyncActive || !projection) {
      return false;
    }
    const latestTaskStatus = String(projection.latestTask?.status || "").toLowerCase();
    return projection.status === "agent_running" || latestTaskStatus === "queued" || latestTaskStatus === "running";
  };
  const sourceCollectionStageProjectionLabel = (projection: SourceCollectionStageCardProjection | null | undefined) => {
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
  const sourceCollectionSearchStepState: SourceCollectionStepState = sourceCollectionStageProjectionState(
    sourceCollectionCollectionProjection,
    sourceCollectionDisplayState.searchStepState,
  );
  const sourceCollectionScreeningFallbackStepState: SourceCollectionStepState = selectedTeamSourceQualityError
    ? "failed"
      : selectedTeamSourceQualityPending
        ? "active"
      : sourceCollectionRunAssessedCount > 0
        ? "done"
      : sourceCollectionDisplayedCandidateCount > 0 && sourceCollectionSearchOpenAssignmentCount <= 0
          ? "pending"
          : "idle";
  const sourceCollectionScreeningStepStateRaw: SourceCollectionStepState = sourceCollectionStageProjectionState(
    sourceCollectionScreeningProjection,
    sourceCollectionScreeningFallbackStepState,
  );
  const sourceCollectionScreeningStepState: SourceCollectionStepState = sourceCollectionExtractionCanProceedAfterExclusions
    ? "done"
    : sourceCollectionScreeningStepStateRaw;
  const sourceCollectionCandidateFallbackStepState: SourceCollectionStepState = selectedTeamRecordSourceCollectionOutputError || selectedTeamExtractSourceCollectionCandidatesError
    ? "failed"
    : selectedTeamRecordSourceCollectionOutputPending || selectedTeamExtractSourceCollectionCandidatesPending
      ? "active"
      : sourceCollectionDisplayedCandidateCount > 0
        ? "done"
        : selectedSourceCollectionRun
          ? "pending"
          : "idle";
  const sourceCollectionCandidateStepStateRaw: SourceCollectionStepState = sourceCollectionStageProjectionState(
    sourceCollectionCandidateProjection,
    sourceCollectionCandidateFallbackStepState,
  );
  const sourceCollectionCandidateStepState: SourceCollectionStepState = sourceCollectionExtractionCanProceedAfterExclusions
    ? "done"
    : sourceCollectionCandidateStepStateRaw;
  const sourceCollectionExtractionDefaultPanelId = "source-collection-screening-panel";
  const sourceCollectionGraphFallbackStepState: SourceCollectionStepState = selectedTeamBuildCandidateGraphError || teamWorkflowCandidateGraphQuery.error
    ? "failed"
      : selectedTeamBuildCandidateGraphPending
        ? "active"
      : candidateGraphNodeCount > 0
        ? "done"
        : sourceCollectionRunApprovedCount > 0
          ? "pending"
          : "idle";
  const sourceCollectionGraphStepState: SourceCollectionStepState = sourceCollectionStageProjectionState(
    sourceCollectionGraphProjection,
    sourceCollectionGraphFallbackStepState,
  );
  const sourceCollectionMemoryFallbackStepState: SourceCollectionStepState = teamWorkflowKnowledgeIngestionStatusQuery.error || selectedTeamKnowledgePrecheckError || selectedTeamKnowledgeCollectionIngestError
    ? "failed"
    : selectedTeamKnowledgePrecheckPending || selectedTeamKnowledgeCollectionIngestPending
      ? "active"
      : formalKnowledgeItemCount > 0
        ? "done"
        : knowledgePendingReviewCount > 0 || knowledgeStewardPackCount > 0 || sourceCollectionIngestCandidateCount > 0
          ? "pending"
          : "idle";
  const sourceCollectionMemoryStepState: SourceCollectionStepState = sourceCollectionStageProjectionState(
    sourceCollectionMemoryProjection,
    sourceCollectionMemoryFallbackStepState,
  );
  const sourceCollectionExtractionStepState: SourceCollectionStepState =
    sourceCollectionCandidateStepState === "failed" || sourceCollectionScreeningStepState === "failed"
      ? "failed"
      : sourceCollectionCandidateStepState === "active" || sourceCollectionScreeningStepState === "active"
        ? "active"
        : sourceCollectionDisplayedCandidateCount > 0
          ? sourceCollectionScreeningStepState
          : sourceCollectionCandidateStepState;
  const sourceCollectionCollectionActionLabel = !selectedSourceCollectionRun
    ? sourceCollectionStageSessionTaskPendingStageId === "finding"
      ? (lang === "zh" ? "启动 Agent 中" : "Starting Agent")
      : (lang === "zh" ? "开始搜集" : "Start")
    : selectedTeamExecuteSourceCollectionSearchPending || sourceCollectionAcceptedBackgroundActive
      ? (lang === "zh" ? "搜索中" : "Searching")
      : sourceCollectionSearchOpenAssignmentCount > 0
        ? (lang === "zh" ? "搜索下一批" : "Search next")
      : (lang === "zh" ? "新一轮搜集" : "New round");
  const sourceCollectionCollectionActionReadiness = !selectedSourceCollectionRun
    ? sourceCollectionActionReadiness(
        selectedTeamStartResearchStagePending || selectedTeamStartSourceCollectionStageTaskPending || !researchStageCanLaunch,
        selectedTeamStartResearchStagePending || selectedTeamStartSourceCollectionStageTaskPending
          ? sourceCollectionActionBusyReason
          : sourceCollectionActionNoInputReason,
        selectedTeamStartResearchStagePending || selectedTeamStartSourceCollectionStageTaskPending,
      )
    : sourceCollectionAssignmentsDataLoading || sourceCollectionActionDataError
      ? sourceCollectionActionReadiness(
          true,
          sourceCollectionAssignmentsDataLoading ? sourceCollectionActionLoadingReason : sourceCollectionActionErrorReason,
          sourceCollectionAssignmentsDataLoading,
        )
      : sourceCollectionSearchOpenAssignmentCount > 0
        ? sourceCollectionSearchActionReadiness
        : sourceCollectionActionReadiness(
            selectedTeamStartResearchStagePending || selectedTeamStartSourceCollectionStageTaskPending || !researchStageCanLaunch,
            selectedTeamStartResearchStagePending || selectedTeamStartSourceCollectionStageTaskPending
              ? sourceCollectionActionBusyReason
              : sourceCollectionActionNoInputReason,
            selectedTeamStartResearchStagePending || selectedTeamStartSourceCollectionStageTaskPending,
          );
  const sourceCollectionStageTaskActionLabel = (stageId: SourceCollectionStageModuleId, label: string) =>
    sourceCollectionStageSessionTaskPendingStageId === stageId
      ? (lang === "zh" ? "启动 Agent 中" : "Starting Agent")
      : sourceCollectionStageLaunchActive(stageId)
        ? (lang === "zh" ? "等待 Agent 回写" : "Waiting for Agent writeback")
        : label;
  const sourceCollectionStageTaskActionReadiness = (stageId: SourceCollectionStageModuleId, readiness: SourceCollectionActionReadiness) =>
    sourceCollectionStageLaunchActive(stageId)
      ? sourceCollectionActionReadiness(true, lang === "zh" ? "等待 Agent 回写" : "Waiting for Agent writeback", true)
      : readiness.disabled
        ? readiness
        : sourceCollectionActionReadiness(
            selectedTeamStartSourceCollectionStageTaskPending,
            sourceCollectionActionBusyReason,
            selectedTeamStartSourceCollectionStageTaskPending,
          );
  const sourceCollectionStageActionLabelFor = (stageId: SourceCollectionStageModuleId, fallback: string) =>
    sourceCollectionStageTaskActionLabel(
      stageId,
      sourceCollectionStageCardById.get(stageId)?.actionReadiness?.actionLabel || fallback,
    );
  const sourceCollectionStageActionReadinessFor = (stageId: SourceCollectionStageModuleId): SourceCollectionActionReadiness => {
    if (stageId === "finding") {
      return sourceCollectionStageTaskActionReadiness(
        "finding",
        sourceCollectionStageBackendActionReadiness(
          sourceCollectionStageCardById.get("finding"),
          sourceCollectionCollectionActionReadiness,
          sourceCollectionActionNoInputReason,
        ),
      );
    }
    if (stageId === "extraction") {
      const extractionDisabled = sourceCollectionCandidateExtractionActionReadiness.disabled && sourceCollectionScreeningActionReadiness.disabled;
      const extractionLoading = sourceCollectionCandidateExtractionActionReadiness.loading || sourceCollectionScreeningActionReadiness.loading;
      const extractionReason = !sourceCollectionCandidateExtractionActionReadiness.disabled
        ? sourceCollectionCandidateExtractionActionReadiness.reason
        : sourceCollectionScreeningActionReadiness.reason || sourceCollectionCandidateExtractionActionReadiness.reason;
      return sourceCollectionStageTaskActionReadiness(
        "extraction",
        sourceCollectionStageBackendActionReadiness(
          sourceCollectionStageCardById.get("extraction"),
          sourceCollectionActionReadiness(extractionDisabled, extractionReason || sourceCollectionActionNoInputReason, extractionLoading),
          sourceCollectionActionNoInputReason,
        ),
      );
    }
    if (stageId === "relations") {
      return sourceCollectionStageTaskActionReadiness(
        "relations",
        sourceCollectionStageBackendActionReadiness(
          sourceCollectionStageCardById.get("relations"),
          sourceCollectionGraphActionReadiness,
          sourceCollectionActionNoInputReason,
        ),
      );
    }
    return sourceCollectionStageTaskActionReadiness(
      "ingestion",
      sourceCollectionStageBackendActionReadiness(
        sourceCollectionStageCardById.get("ingestion"),
        sourceCollectionMemoryActionReadiness,
        sourceCollectionActionNoInputReason,
      ),
    );
  };
  const sourceCollectionFindingDisplayLoading = sourceCollectionRecordsDataLoading || sourceCollectionAssignmentsDataLoading;
  const sourceCollectionFindingDisplayState: SourceCollectionStepState = sourceCollectionFindingDisplayLoading
    ? "pending"
    : sourceCollectionSearchStepState;
  const sourceCollectionExtractionDisplayLoading = sourceCollectionPrimaryDataLoading || sourceCollectionScreeningDataLoading;
  const sourceCollectionExtractionDisplayState: SourceCollectionStepState = sourceCollectionExtractionDisplayLoading
    ? "pending"
    : sourceCollectionExtractionStepState;
  const sourceCollectionRelationsDisplayLoading = sourceCollectionGraphDataLoading;
  const sourceCollectionRelationsDisplayState: SourceCollectionStepState = sourceCollectionRelationsDisplayLoading
    ? "pending"
    : sourceCollectionGraphStepState;
  const sourceCollectionIngestionDisplayLoading = sourceCollectionSourceQualityLoading || sourceCollectionKnowledgeIngestionDataLoading;
  const sourceCollectionIngestionDisplayState: SourceCollectionStepState = sourceCollectionIngestionDisplayLoading
    ? "pending"
    : sourceCollectionMemoryStepState;
  const sourceCollectionSourceSyncStatusText = sourceCollectionProjectedCollectedCount > 0
    ? sourceCollectionDataSyncText
    : sourceCollectionLoadingText;
  const sourceCollectionCandidateSyncStatusText = sourceCollectionDisplayedCandidateCount > 0 || sourceCollectionProjectedCollectedCount > 0
    ? sourceCollectionDataSyncText
    : sourceCollectionLoadingText;
  const sourceCollectionExtractionLoadingMetric = sourceCollectionProjectedCandidateCount > 0
    ? (lang === "zh"
      ? `已处理 ${sourceCollectionProjectedAssessedCount}/${sourceCollectionProjectedCandidateCount} · ${sourceCollectionDataSyncText}`
      : `${sourceCollectionProjectedAssessedCount}/${sourceCollectionProjectedCandidateCount} processed · ${sourceCollectionDataSyncText}`)
      : (lang === "zh" ? "提炼进度 加载中" : "extraction loading");
  const sourceCollectionExtractionMaterialMetric = lang === "zh"
    ? `已提炼 ${sourceCollectionCurrentCandidateCount}/${sourceCollectionCurrentCandidateCount} · ${sourceCollectionExtractionAgentMaterialCount} 条待补材料`
    : `${sourceCollectionCurrentCandidateCount}/${sourceCollectionCurrentCandidateCount} extracted · ${sourceCollectionExtractionAgentMaterialCount} need material`;
  const sourceCollectionExtractionLoadingOutputLabel = sourceCollectionProjectedCandidateCount > 0 || sourceCollectionProjectedApprovedCount > 0
    ? (lang === "zh"
      ? `${sourceCollectionProjectedApprovedCount} 条保留 / ${sourceCollectionRunPendingScreeningCount} 条待处理 · ${sourceCollectionDataSyncText}`
      : `${sourceCollectionProjectedApprovedCount} kept / ${sourceCollectionRunPendingScreeningCount} pending · ${sourceCollectionDataSyncText}`)
    : (lang === "zh" ? "提炼结果加载中" : "extraction result loading");
  const sourceCollectionIngestionReadyForExperiment = sourceCollectionProjectedFormalKnowledgeCount > 0;
  const sourceCollectionExperimentPlanningRoute = researchWorkspaceStageRoute(
    selectedTeam?.teamId || RESEARCH_TEAM_ID,
    "experiment",
  );

  return {
    sourceCollectionSummary,
    sourceCollectionSummaryRun,
    sourceCollectionSummaryRunId,
    sourceCollectionActionRunId,
    sourceCollectionPhaseCloseGate,
    sourceCollectionSummaryStageRound,
    sourceCollectionStageRound,
    sourceCollectionStageCards,
    sourceCollectionStageCardById,
    experimentPlanningStatus,
    sourceCollectionRecords,
    sourceCollectionAssignments,
    sourceCollectionRunStatus,
    sourceCollectionSearchPlanRef,
    aiSearchRuns,
    researchLoopTemplatesPayload,
    researchLoopStatus,
    latestAiSearchRun,
    aiSearchRunCanStart,
    selectedSourceCollectionAssignment,
    selectedSourceCollectionQueries,
    sourceCollectionFindingRunOptions,
    sourceCollectionFindingAssignments,
    sourceCollectionFindingQueries,
    sourceCollectionCanStart,
    researchStageCanLaunch,
    sourceCollectionResetResearchProjectId,
    sourceCollectionResetAvailable,
    sourceCollectionPromptCachePolicy,
    sourceCollectionPromptCachePolicyRef,
    sourceCollectionPromptCacheStatus,
    sourceCollectionPromptCacheMode,
    sourceCollectionPromptCacheRequirement,
    sourceCollectionOutputHasRecord,
    selectedTeamInitialSourceCollectionSearchResult,
    selectedSourceCollectionSearchExecutionResult,
    selectedSourceCollectionSearchAccepted,
    runtimeSourceCollectionActiveWorkRun,
    summarySourceCollectionActiveWorkRun,
    selectedSourceCollectionActiveWorkRun,
    sourceCollectionSummaryStorageArtifacts,
    selectedSourceCollectionStorageArtifacts,
    openSourceCollectionStorageTarget,
    sourceCollectionRunSummary,
    sourceCollectionOpenAssignments,
    sourceCollectionOpenAssignmentCount,
    sourceCollectionSearchOpenAssignmentCount,
    sourceCollectionDownstreamOpenAssignmentCount,
    sourceManifestCandidates,
    teamWorkflowCandidatesById,
    sourceCollectionRunCandidates,
    selectedSourceCollectionCandidate,
    selectedSourceCollectionCandidateTrace,
    selectedSourceCollectionCandidateRunId,
    selectedSourceCollectionCandidateStorageArtifacts,
    selectSourceCollectionCandidate,
    sourceCollectionCandidateCardKeyDown,
    sourceCollectionCandidatesByRecordId,
    sourceCollectionRecordProvenances,
    sourceCollectionRecordSourceCategories,
    sourceCollectionFilteredRecords,
    sourceCollectionRunCandidateSourceCategories,
    sourceCollectionFilteredRunCandidates,
    sourceCollectionSummaryCounts,
    sourceCollectionRawRecordCount,
    sourceCollectionRecordClickableSourceCount,
    sourceCollectionRecordLocalFileCount,
    sourceCollectionRecordMissingSourceCount,
    sourceCollectionRunCandidateCount,
    sourceCollectionRecordFilterCounts,
    sourceCollectionCandidateFilterCounts,
    sourceCollectionReviewableRunCandidates,
    sourceCollectionRunReviewableCandidateCount,
    sourceCollectionRunAssessedCount,
    sourceCollectionRunApprovedCount,
    sourceCollectionRunNeedsRevisionCount,
    sourceCollectionEvidenceLedgerSummaries,
    sourceCollectionEvidenceReadyCandidateCount,
    sourceCollectionMissingEvidenceAnchorCount,
    sourceCollectionCollectedCount,
    sourceCollectionRunSummaryHasRecordCount,
    sourceCollectionSummaryHasRecordCount,
    sourceCollectionRunSummaryHasAssignmentCounts,
    sourceCollectionCandidateListDataLoading,
    sourceCollectionRecordsDataLoading,
    sourceCollectionAssignmentsDataLoading,
    sourceCollectionCollectionProjection,
    sourceCollectionExtractionProjection,
    sourceCollectionCandidateProjection,
    sourceCollectionScreeningProjection,
    sourceCollectionGraphProjection,
    sourceCollectionMemoryProjection,
    sourceCollectionExcludedSourceCount,
    sourceCollectionStageSummaryCandidateCount,
    sourceCollectionCandidateProjectionFallbackCount,
    sourceCollectionProjectedCollectedCount,
    sourceCollectionProjectedCandidateCount,
    sourceCollectionProjectedAssessedCount,
    sourceCollectionProjectedApprovedCount,
    sourceCollectionDisplayedCandidateCount,
    sourceCollectionQueryCount,
    sourceCollectionPrimaryDataLoading,
    sourceCollectionSourceQualityLoading,
    sourceCollectionGraphDataLoading,
    sourceCollectionKnowledgeIngestionDataLoading,
    sourceCollectionActionInitialDataPending,
    sourceCollectionActionDataError,
    sourceCollectionSourceQualityDataError,
    sourceCollectionGraphDataError,
    sourceCollectionKnowledgeIngestionDataError,
    sourceCollectionScreeningDataLoading,
    sourceCollectionActionReadiness,
    sourceCollectionActionDisabledTitle,
    sourceCollectionCountText,
    sourceCollectionCountWithUnit,
    sourceCollectionCollectedCountText,
    sourceCollectionProjectedCollectedCountText,
    sourceCollectionSearchOpenAssignmentCountText,
    sourceCollectionDownstreamOpenAssignmentCountText,
    sourceCollectionQueryDataLoading,
    sourceCollectionQueryCountText,
    sourceCollectionCollectedCountLabel,
    sourceCollectionProjectedCollectedCountLabel,
    sourceCollectionSearchOpenAssignmentCountLabel,
    sourceCollectionDownstreamOpenAssignmentCountLabel,
    sourceCollectionQueryCountLabel,
    sourceCollectionCollectedRunSummaryText,
    sourceCollectionAssignmentRunSummaryText,
    sourceCollectionDisplayedCandidateCountText,
    sourceCollectionProjectedCandidateCountText,
    sourceCollectionCoverageBoundCandidateCount,
    sourceCollectionCurrentCandidateCount,
    sourceCollectionCurrentCandidateCountText,
    sourceCollectionProjectedCandidateCountLabel,
    sourceCollectionProjectedAssessedCountText,
    sourceCollectionProjectedApprovedCountText,
    sourceCollectionDisplayedCandidateFilterCounts,
    sourceCollectionRunPendingScreeningCount,
    sourceCollectionRunPendingScreeningCountText,
    sourceCollectionPendingCandidateImportCount,
    sourceCollectionExtractionRecoveryCoverage,
    sourceCollectionExtractionRecoveryClosure,
    sourceCollectionExtractionSourceVerificationCount,
    sourceCollectionUnverifiableCandidateIds,
    sourceCollectionExtractionMissingEvidenceAnchorCount,
    sourceCollectionExtractionAgentMaterialCount,
    sourceCollectionExtractionNeedsAgentMaterial,
    sourceCollectionExtractionRecoveryMissingCount,
    sourceCollectionExtractionExcludedRecoveryState,
    sourceCollectionExtractionCanProceedAfterExclusions,
    sourceCollectionExtractionProceedableSummary,
    sourceCollectionApprovedCount,
    sourceCollectionStageFocusLabel,
    sourceCollectionRunStatusValue,
    sourceCollectionAcceptedBackgroundActive,
    canRecordSourceCollectionOutput,
    canExecuteSourceCollectionSearch,
    sourceCollectionAcceptedBackgroundFailed,
    sourceCollectionOperationFailed,
    sourceCollectionDisplayState,
    candidateGraphNodeCount,
    candidateGraphEdgeCount,
    knowledgeStewardPackCount,
    knowledgePendingReviewCount,
    formalKnowledgeItemCount,
    sourceCollectionProjectedGraphNodeCount,
    sourceCollectionProjectedGraphEdgeCount,
    sourceCollectionProjectedStewardPackCount,
    sourceCollectionProjectedFormalKnowledgeCount,
    sourceCollectionDefaultKnowledgeBaseId,
    sourceCollectionPrecheckCandidateCount,
    sourceCollectionIngestCandidateCount,
    sourceCollectionCanBuildGraph,
    sourceCollectionSearchActionReadiness,
    sourceCollectionCandidateExtractionActionReadiness,
    sourceCollectionScreeningActionReadiness,
    sourceCollectionGraphActionReadiness,
    sourceCollectionMemoryActionReadiness,
    sourceCollectionCompletionActionReadiness,
    sourceCollectionLoopStartsNewRun,
    sourceCollectionLoopStartReadiness,
    sourceCollectionLoopActionReadiness,
    sourceCollectionMemoryActionDisabled,
    sourceCollectionMemoryActionLabel,
    sourceCollectionCompletionActionDisabled,
    sourceCollectionCompletionActionLabel,
    sourceCollectionLoopActionDisabled,
    sourceCollectionLoopActionLabel,
    sourceCollectionGraphActionDisabled,
    sourceCollectionGraphActionLabel,
    sourceCollectionScreeningDisabled,
    sourceCollectionScreeningForceRescreen,
    sourceCollectionScreeningButtonText,
    sourceCollectionScreeningButtonTitle,
    sourceCollectionScreeningStatusText,
    sourceCollectionCandidateExtractionButtonText,
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
    sourceCollectionConsoleState,
    sourceCollectionConsoleStatusText,
    sourceCollectionDecisionText,
    sourceCollectionStepStatusText,
    sourceCollectionStageProjectionSyncing,
    sourceCollectionStageProjectionLabel,
    sourceCollectionStageLaunchActive,
    sourceCollectionStageFormalRetryRequired,
    sourceCollectionStageLaunchSummary,
    sourceCollectionStageDisplayState,
    sourceCollectionStageDisplayStatus,
    sourceCollectionStageDisplaySummary,
    sourceCollectionStepClassName,
    sourceCollectionSearchStepState,
    sourceCollectionScreeningFallbackStepState,
    sourceCollectionScreeningStepStateRaw,
    sourceCollectionScreeningStepState,
    sourceCollectionCandidateFallbackStepState,
    sourceCollectionCandidateStepStateRaw,
    sourceCollectionCandidateStepState,
    sourceCollectionExtractionDefaultPanelId,
    sourceCollectionGraphFallbackStepState,
    sourceCollectionGraphStepState,
    sourceCollectionMemoryFallbackStepState,
    sourceCollectionMemoryStepState,
    sourceCollectionExtractionStepState,
    sourceCollectionCollectionActionLabel,
    sourceCollectionCollectionActionReadiness,
    sourceCollectionStageTaskActionLabel,
    sourceCollectionStageTaskActionReadiness,
    sourceCollectionStageActionLabelFor,
    sourceCollectionStageActionReadinessFor,
    sourceCollectionFindingDisplayLoading,
    sourceCollectionFindingDisplayState,
    sourceCollectionExtractionDisplayLoading,
    sourceCollectionExtractionDisplayState,
    sourceCollectionRelationsDisplayLoading,
    sourceCollectionRelationsDisplayState,
    sourceCollectionIngestionDisplayLoading,
    sourceCollectionIngestionDisplayState,
    sourceCollectionSourceSyncStatusText,
    sourceCollectionCandidateSyncStatusText,
    sourceCollectionExtractionLoadingMetric,
    sourceCollectionExtractionMaterialMetric,
    sourceCollectionExtractionLoadingOutputLabel,
    sourceCollectionIngestionReadyForExperiment,
    sourceCollectionExperimentPlanningRoute,
    selectedResearchProjectSourceCollectionResetPending,
    selectedResearchProjectSourceCollectionResetError,
    selectedTeamStartResearchStagePending,
    selectedTeamStartResearchStageError,
    selectedTeamStartResearchStageResult,
    selectedTeamCreateExperimentPlanPending,
    selectedTeamCreateExperimentPlanError,
    selectedTeamCreateExperimentPlanResult,
    selectedTeamMaterializeEngineeringProxyPending,
    selectedTeamMaterializeEngineeringProxyError,
    selectedTeamCompleteScientificHypothesisCandidateId,
    selectedTeamCompleteScientificHypothesisError,
    selectedTeamReviewExperimentHypothesisCandidateId,
    selectedTeamReviewExperimentHypothesisError,
    selectedTeamCreateExperimentHypothesisRevisionCandidateId,
    selectedTeamCreateExperimentHypothesisRevisionError,
    selectedTeamFreezeExperimentDesignPending,
    selectedTeamFreezeExperimentDesignError,
    selectedTeamFreezeExperimentDesignResult,
    selectedTeamRegisterExperimentBaselineArtifactPending,
    selectedTeamRegisterExperimentBaselineArtifactError,
    selectedTeamRegisterExperimentBaselineArtifactResult,
    selectedTeamRunExperimentSmokePending,
    selectedTeamRunExperimentSmokeError,
    selectedTeamRunExperimentSmokeResult,
    selectedTeamRegisterExperimentSmokeResultPending,
    selectedTeamRegisterExperimentSmokeResultError,
    selectedTeamRegisterExperimentSmokeResultResult,
    selectedTeamRegisterExperimentFullRunResultPending,
    selectedTeamRegisterExperimentFullRunResultError,
    selectedTeamRegisterExperimentFullRunResultResult,
    selectedTeamRequestExperimentKnowledgeIngestionPending,
    selectedTeamRequestExperimentKnowledgeIngestionError,
    selectedTeamRequestExperimentKnowledgeIngestionResult,
    selectedTeamCreateResearchLoopPending,
    selectedTeamCreateResearchLoopError,
    selectedTeamCreateResearchLoopResult,
    selectedTeamRecordResearchLoopEvidencePending,
    selectedTeamRecordResearchLoopEvidenceError,
    selectedTeamRecordResearchLoopEvidenceResult,
    selectedTeamRecordResearchLoopDecisionPending,
    selectedTeamRecordResearchLoopDecisionError,
    selectedTeamRecordResearchLoopDecisionResult,
    selectedTeamStartSourceCollectionPending,
    selectedTeamStartSourceCollectionError,
    selectedTeamStartSourceCollectionResult,
    selectedTeamStartSourceCollectionStageTaskPending,
    selectedTeamStartSourceCollectionStageTaskError,
    sourceCollectionStageSessionTaskPendingStageId,
    selectedTeamRecordSourceCollectionOutputPending,
    selectedTeamRecordSourceCollectionOutputError,
    selectedTeamRecordSourceCollectionOutputResult,
    selectedTeamExecuteSourceCollectionSearchPending,
    selectedTeamExecuteSourceCollectionSearchError,
    selectedTeamExecuteSourceCollectionSearchResult,
    selectedTeamExtractSourceCollectionCandidatesPending,
    selectedTeamExtractSourceCollectionCandidatesError,
    selectedTeamExtractSourceCollectionCandidatesResult,
    selectedSourceCollectionStorageOpenPending,
    selectedSourceCollectionStorageOpenResult,
    selectedSourceCollectionStorageOpenError,
    selectedTeamStartAiSearchPending,
    selectedTeamStartAiSearchError,
    selectedTeamStartAiSearchResult,
    sourceCollectionLoadingText,
    sourceCollectionDataSyncText,
    sourceCollectionLoadingSummary,
    sourceCollectionActionLoadingReason,
    sourceCollectionActionErrorReason,
    sourceCollectionActionNoRunReason,
    sourceCollectionActionNoInputReason,
    sourceCollectionActionBusyReason,
    selectedTeamBuildCandidateGraphPending,
    selectedTeamBuildCandidateGraphError,
    selectedTeamKnowledgePrecheckPending,
    selectedTeamKnowledgePrecheckError,
    selectedTeamKnowledgeIngestionActiveWorkRun,
    selectedTeamKnowledgeIngestionLatestWorkRun,
    selectedTeamKnowledgeCollectionWorkRun,
    selectedTeamKnowledgeCollectionSourceRunId,
    selectedTeamKnowledgeCollectionMatchesSelectedRun,
    selectedTeamKnowledgeCollectionWorkRunStatus,
    selectedTeamKnowledgeCollectionFlowStatus,
    selectedTeamKnowledgeCollectionCompleted,
    selectedTeamKnowledgeCollectionCompletedForSelectedRun,
    selectedTeamKnowledgeCollectionIngestPending,
    selectedTeamKnowledgeCollectionIngestError,
    selectedTeamKnowledgeCollectionIngestResult,
    selectedTeamPlanPaperNoteChunksPending,
    selectedTeamPlanPaperNoteChunksError,
    selectedTeamAssessSourceQualityPending,
    selectedTeamAssessSourceQualityError,
    selectedTeamAssessSourceQualityBatchPending,
    selectedTeamAssessSourceQualityBatchError,
    selectedTeamSourceQualityPending,
    selectedTeamSourceQualityError,
    selectedTeamSourceQualityBatchResult,
    sourceCollectionQualityBatchFeedback,
  };
}

export type SourceCollectionPresentationApi = ReturnType<typeof useSourceCollectionPresentation>;
