/**
 * Pure finding/prompt-cache/search-selection presentation for SC core.
 * Phase R2-n extract from useSourceCollectionPresentationCore (behavior-conserving).
 */
import type {
  DataProcessingCollectionAssignment,
  TeamWorkflowCandidate,
  TeamWorkflowSourceCollectionPromptCachePolicyRef,
  WorkRunSnapshot,
} from "../../../api/types";
import { isRecord } from "../workflowPresentation";
import {
  sourceCollectionActiveWorkRunFromRuntime,
  sourceCollectionRunLabel,
  sourceCollectionRunTitleLabel,
  translateResearchPhrase,
} from "./runModel";
import {
  SOURCE_COLLECTION_PROMPT_CACHE_POLICY,
  hasSourceCollectionPromptCachePolicy,
  sourceCollectionAgentRoleLabel,
  sourceCollectionLanguageLabel,
  sourceCollectionStatusLabel,
  sourceCollectionStorageArtifactsForRun,
  type SourceCollectionDraft,
  type SourceCollectionStorageArtifacts,
} from "./presentationModel";
import type { SourceCollectionOutputDraft } from "../sourceCollectionMutationModel";
import {
  sourceCollectionCandidateTrace,
  sourceCollectionSourceTypeLabel,
} from "./evidenceModel";

export type DeriveSourceCollectionSelectionPresentationInput = {
  lang: "zh" | "en";
  teamId: string;
  effectiveTeamId: string;
  sourceCollectionRuns: Array<{ runId: string; title?: string }>;
  sourceCollectionAssignments: DataProcessingCollectionAssignment[];
  sourceCollectionOutputDraft: SourceCollectionOutputDraft;
  sourceCollectionDraft: SourceCollectionDraft;
  activeSourceCollectionResearchProjectId: string;
  selectedSourceCollectionRun: {
    status?: string;
    scope?: {
      promptCachePolicyRef?: TeamWorkflowSourceCollectionPromptCachePolicyRef | null;
      dataSearchPlanRef?: {
        promptCachePolicyId?: string;
        promptCacheRequirement?: string;
        promptCacheGateStatus?: string;
      } | null;
    };
  } | null | undefined;
  sourceCollectionSearchPlanRef: {
    promptCachePolicyId?: string;
    promptCacheRequirement?: string;
    promptCacheGateStatus?: string;
  } | null | undefined;
  selectedTeamStartSourceCollectionResult: any;
  selectedTeamStartResearchStageResult: any;
  selectedTeamExecuteSourceCollectionSearchResult: any;
  runtimeSummaryData: unknown;
  selectedSourceCollectionRunEffectiveId: string;
  sourceCollectionSummary: any;
  teamWorkflowCandidates: TeamWorkflowCandidate[];
  selectedSourceCollectionCandidateId: string;
};

export function deriveSourceCollectionSelectionPresentation(
  input: DeriveSourceCollectionSelectionPresentationInput,
) {
  const {
    lang,
    teamId,
    effectiveTeamId,
    sourceCollectionRuns,
    sourceCollectionAssignments,
    sourceCollectionOutputDraft,
    sourceCollectionDraft,
    activeSourceCollectionResearchProjectId,
    selectedSourceCollectionRun,
    sourceCollectionSearchPlanRef,
    selectedTeamStartSourceCollectionResult,
    selectedTeamStartResearchStageResult,
    selectedTeamExecuteSourceCollectionSearchResult,
    runtimeSummaryData,
    selectedSourceCollectionRunEffectiveId,
    sourceCollectionSummary,
    teamWorkflowCandidates,
    selectedSourceCollectionCandidateId,
  } = input;

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
  const sourceCollectionCanStart = Boolean(teamId && sourceCollectionDraft.topic.trim());
  const researchStageCanLaunch = Boolean(teamId && sourceCollectionDraft.topic.trim());
  const sourceCollectionResetResearchProjectId = activeSourceCollectionResearchProjectId.trim();
  const sourceCollectionResetAvailable = Boolean(
    sourceCollectionResetResearchProjectId
    && sourceCollectionRuns.length > 0,
  );
  const sourceCollectionPromptCachePolicy =
    [
      selectedTeamStartSourceCollectionResult?.promptCachePolicy,
      selectedTeamStartSourceCollectionResult?.searchPlan?.promptCachePolicy,
      selectedTeamStartResearchStageResult?.promptCachePolicy,
      selectedTeamStartResearchStageResult?.sourceCollectionRun?.promptCachePolicy,
      selectedTeamStartResearchStageResult?.searchPlan?.promptCachePolicy,
      selectedTeamStartResearchStageResult?.stageRound?.promptCachePolicy,
    ].find(hasSourceCollectionPromptCachePolicy) ?? null;
  const sourceCollectionPromptCachePolicyRef: TeamWorkflowSourceCollectionPromptCachePolicyRef | null =
    selectedSourceCollectionRun?.scope?.promptCachePolicyRef
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
    sourceCollectionPromptCachePolicy?.requirement
    || sourceCollectionPromptCachePolicyRef?.requirement
    || SOURCE_COLLECTION_PROMPT_CACHE_POLICY.requirement;
  const sourceCollectionOutputHasRecord = Boolean(
    sourceCollectionOutputDraft.title.trim()
    || sourceCollectionOutputDraft.sourceRef.trim()
    || sourceCollectionOutputDraft.rawLocation.trim(),
  );
  const selectedTeamInitialSourceCollectionSearchResult =
    selectedTeamStartResearchStageResult?.sourceCollectionSearchExecution;
  const selectedSourceCollectionSearchExecutionResult =
    selectedTeamExecuteSourceCollectionSearchResult ?? selectedTeamInitialSourceCollectionSearchResult;
  const selectedSourceCollectionSearchAccepted = Boolean(selectedSourceCollectionSearchExecutionResult?.accepted);
  const runtimeSourceCollectionActiveWorkRun = sourceCollectionActiveWorkRunFromRuntime(
    runtimeSummaryData,
    selectedSourceCollectionRunEffectiveId,
  );
  const summarySourceCollectionActiveWorkRun = isRecord(sourceCollectionSummary?.activeWorkRun)
    ? sourceCollectionSummary.activeWorkRun as WorkRunSnapshot
    : undefined;
  const selectedSourceCollectionActiveWorkRun =
    runtimeSummaryData
      ? runtimeSourceCollectionActiveWorkRun ?? undefined
      : summarySourceCollectionActiveWorkRun ?? selectedSourceCollectionSearchExecutionResult?.activeWorkRun;
  const sourceCollectionSummaryStorageArtifacts =
    sourceCollectionSummary?.storageArtifacts as SourceCollectionStorageArtifacts | undefined;
  const selectedSourceCollectionStorageArtifacts =
    selectedSourceCollectionSearchExecutionResult?.storageArtifacts
    ?? sourceCollectionSummaryStorageArtifacts
    ?? sourceCollectionStorageArtifactsForRun(teamId || effectiveTeamId, selectedSourceCollectionRunEffectiveId);
  const sourceManifestCandidates = teamWorkflowCandidates.filter(
    (candidate) => candidate.candidateType === "source_manifest",
  );
  const teamWorkflowCandidatesById = (() => {
    const mapping = new Map<string, TeamWorkflowCandidate>();
    teamWorkflowCandidates.forEach((candidate) => {
      mapping.set(candidate.candidateId, candidate);
    });
    return mapping;
  })();
  const sourceCollectionRunCandidates = selectedSourceCollectionRunEffectiveId
    ? sourceManifestCandidates.filter(
      (candidate) => sourceCollectionCandidateTrace(candidate).runId === selectedSourceCollectionRunEffectiveId,
    )
    : sourceManifestCandidates;
  const selectedSourceCollectionCandidate =
    sourceManifestCandidates.find((candidate) => candidate.candidateId === selectedSourceCollectionCandidateId) ?? null;
  const selectedSourceCollectionCandidateTrace = selectedSourceCollectionCandidate
    ? sourceCollectionCandidateTrace(selectedSourceCollectionCandidate)
    : null;
  const selectedSourceCollectionCandidateRunId =
    selectedSourceCollectionCandidateTrace?.runId || selectedSourceCollectionRunEffectiveId;
  const selectedSourceCollectionCandidateStorageArtifacts =
    sourceCollectionStorageArtifactsForRun(teamId || effectiveTeamId, selectedSourceCollectionCandidateRunId)
    ?? selectedSourceCollectionStorageArtifacts;

  return {
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
    sourceManifestCandidates,
    teamWorkflowCandidatesById,
    sourceCollectionRunCandidates,
    selectedSourceCollectionCandidate,
    selectedSourceCollectionCandidateTrace,
    selectedSourceCollectionCandidateRunId,
    selectedSourceCollectionCandidateStorageArtifacts,
  };
}
