/**
 * Team-scoped mutation surface helpers for TeamsRoute.
 * Phase 4: collapse repetitive pending/error/result flags so the route keeps less derived ctx.
 */

export type TeamScopedMutationLike<
  TData = unknown,
  TVariables extends { teamId?: string } = { teamId?: string },
> = {
  isPending: boolean;
  error: unknown;
  data?: TData;
  variables?: TVariables;
};

export type TeamScopedMutationSurface<TData> = {
  forTeam: boolean;
  pending: boolean;
  error: Error | null;
  result: TData | undefined;
};

/** Resolve pending / error / data only when mutation.variables.teamId matches the active team. */
export function teamScopedMutationSurface<TData, TVariables extends { teamId?: string }>(
  mutation: TeamScopedMutationLike<TData, TVariables>,
  teamId: string | undefined | null,
): TeamScopedMutationSurface<TData> {
  const forTeam = Boolean(teamId && mutation.variables?.teamId === teamId);
  return {
    forTeam,
    pending: Boolean(mutation.isPending && forTeam),
    error: forTeam && mutation.error instanceof Error ? mutation.error : null,
    result: forTeam ? mutation.data : undefined,
  };
}

/** Pending candidate id for hypothesis-style mutations (empty when not for active team). */
export function teamScopedMutationCandidateId<
  TVariables extends { teamId?: string; candidateId?: string },
>(
  mutation: TeamScopedMutationLike<unknown, TVariables>,
  teamId: string | undefined | null,
): string {
  const surface = teamScopedMutationSurface(mutation, teamId);
  if (!surface.pending) {
    return "";
  }
  return String(mutation.variables?.candidateId || "").trim();
}

export type TeamMutationSurfaceMapInput = {
  teamId: string | undefined | null;
  resetResearchProjectSourceCollection: TeamScopedMutationLike;
  startResearchStageRound: TeamScopedMutationLike;
  createExperimentPlan: TeamScopedMutationLike;
  materializeEngineeringProxyHypothesis: TeamScopedMutationLike;
  completeScientificHypothesisFromDesign: TeamScopedMutationLike<{ candidateId?: string } & Record<string, unknown>, { teamId?: string; candidateId?: string }>;
  reviewExperimentHypothesis: TeamScopedMutationLike<unknown, { teamId?: string; candidateId?: string }>;
  createExperimentHypothesisRevision: TeamScopedMutationLike<unknown, { teamId?: string; candidateId?: string }>;
  freezeExperimentDesign: TeamScopedMutationLike;
  registerExperimentBaselineArtifact: TeamScopedMutationLike;
  runExperimentSmoke: TeamScopedMutationLike;
  registerExperimentSmokeResult: TeamScopedMutationLike;
  registerExperimentFullRunResult: TeamScopedMutationLike;
  requestExperimentKnowledgeIngestion: TeamScopedMutationLike;
  createResearchLoop: TeamScopedMutationLike;
  recordResearchLoopEvidence: TeamScopedMutationLike;
  recordResearchLoopDecision: TeamScopedMutationLike;
  startSourceCollectionRun: TeamScopedMutationLike;
  startSourceCollectionStageSessionTask: TeamScopedMutationLike<unknown, { teamId?: string; stageId?: string }>;
  recordSourceCollectionOutput: TeamScopedMutationLike;
  executeSourceCollectionSearch: TeamScopedMutationLike;
  extractSourceCollectionCandidates: TeamScopedMutationLike<{ runId?: string } & Record<string, unknown>>;
  openSourceCollectionStorage: TeamScopedMutationLike;
  startAiSearchRun: TeamScopedMutationLike;
  /** Extra pending bits that are not pure team-scoped mutation state. */
  researchStageProjectAgentStarting?: boolean;
  researchStageProjectAgentError?: unknown;
  selectedSourceCollectionRunEffectiveId?: string;
};

/**
 * Flatten team-scoped mutation surfaces into the historical TeamsRoute flag names.
 * Keeps call sites stable while removing ~150 lines of repeated ternaries from the route.
 */
export function buildTeamsRouteMutationSurface(input: TeamMutationSurfaceMapInput) {
  const teamId = input.teamId;
  const resetSc = teamScopedMutationSurface(input.resetResearchProjectSourceCollection, teamId);
  const startStage = teamScopedMutationSurface(input.startResearchStageRound, teamId);
  const createPlan = teamScopedMutationSurface(input.createExperimentPlan, teamId);
  const materializeProxy = teamScopedMutationSurface(input.materializeEngineeringProxyHypothesis, teamId);
  const completeHypothesis = teamScopedMutationSurface(input.completeScientificHypothesisFromDesign, teamId);
  const reviewHypothesis = teamScopedMutationSurface(input.reviewExperimentHypothesis, teamId);
  const reviseHypothesis = teamScopedMutationSurface(input.createExperimentHypothesisRevision, teamId);
  const freezeDesign = teamScopedMutationSurface(input.freezeExperimentDesign, teamId);
  const registerBaseline = teamScopedMutationSurface(input.registerExperimentBaselineArtifact, teamId);
  const runSmoke = teamScopedMutationSurface(input.runExperimentSmoke, teamId);
  const registerSmoke = teamScopedMutationSurface(input.registerExperimentSmokeResult, teamId);
  const registerFullRun = teamScopedMutationSurface(input.registerExperimentFullRunResult, teamId);
  const requestKnowledge = teamScopedMutationSurface(input.requestExperimentKnowledgeIngestion, teamId);
  const createLoop = teamScopedMutationSurface(input.createResearchLoop, teamId);
  const recordEvidence = teamScopedMutationSurface(input.recordResearchLoopEvidence, teamId);
  const recordDecision = teamScopedMutationSurface(input.recordResearchLoopDecision, teamId);
  const startSc = teamScopedMutationSurface(input.startSourceCollectionRun, teamId);
  const startStageTask = teamScopedMutationSurface(input.startSourceCollectionStageSessionTask, teamId);
  const recordOutput = teamScopedMutationSurface(input.recordSourceCollectionOutput, teamId);
  const executeSearch = teamScopedMutationSurface(input.executeSourceCollectionSearch, teamId);
  const extractCandidates = teamScopedMutationSurface(input.extractSourceCollectionCandidates, teamId);
  const openStorage = teamScopedMutationSurface(input.openSourceCollectionStorage, teamId);
  const startAiSearch = teamScopedMutationSurface(input.startAiSearchRun, teamId);

  const researchStageAgentError =
    input.researchStageProjectAgentError instanceof Error ? input.researchStageProjectAgentError : null;

  const extractResult =
    extractCandidates.forTeam
    && extractCandidates.result?.runId === input.selectedSourceCollectionRunEffectiveId
      ? extractCandidates.result
      : null;

  return {
    selectedResearchProjectSourceCollectionResetPending: resetSc.pending,
    selectedResearchProjectSourceCollectionResetError: resetSc.error,
    selectedTeamStartResearchStagePending: startStage.pending || Boolean(input.researchStageProjectAgentStarting),
    selectedTeamStartResearchStageError: startStage.error ?? researchStageAgentError,
    selectedTeamStartResearchStageResult: startStage.result,
    selectedTeamCreateExperimentPlanPending: createPlan.pending,
    selectedTeamCreateExperimentPlanError: createPlan.error,
    selectedTeamCreateExperimentPlanResult: createPlan.result,
    selectedTeamMaterializeEngineeringProxyPending: materializeProxy.pending,
    selectedTeamMaterializeEngineeringProxyError: materializeProxy.error,
    selectedTeamCompleteScientificHypothesisCandidateId: teamScopedMutationCandidateId(
      input.completeScientificHypothesisFromDesign,
      teamId,
    ),
    selectedTeamCompleteScientificHypothesisError: completeHypothesis.error,
    selectedTeamReviewExperimentHypothesisCandidateId: teamScopedMutationCandidateId(
      input.reviewExperimentHypothesis,
      teamId,
    ),
    selectedTeamReviewExperimentHypothesisError: reviewHypothesis.error,
    selectedTeamCreateExperimentHypothesisRevisionCandidateId: teamScopedMutationCandidateId(
      input.createExperimentHypothesisRevision,
      teamId,
    ),
    selectedTeamCreateExperimentHypothesisRevisionError: reviseHypothesis.error,
    selectedTeamFreezeExperimentDesignPending: freezeDesign.pending,
    selectedTeamFreezeExperimentDesignError: freezeDesign.error,
    selectedTeamFreezeExperimentDesignResult: freezeDesign.result,
    selectedTeamRegisterExperimentBaselineArtifactPending: registerBaseline.pending,
    selectedTeamRegisterExperimentBaselineArtifactError: registerBaseline.error,
    selectedTeamRegisterExperimentBaselineArtifactResult: registerBaseline.result,
    selectedTeamRunExperimentSmokePending: runSmoke.pending,
    selectedTeamRunExperimentSmokeError: runSmoke.error,
    selectedTeamRunExperimentSmokeResult: runSmoke.result,
    selectedTeamRegisterExperimentSmokeResultPending: registerSmoke.pending,
    selectedTeamRegisterExperimentSmokeResultError: registerSmoke.error,
    selectedTeamRegisterExperimentSmokeResultResult: registerSmoke.result,
    selectedTeamRegisterExperimentFullRunResultPending: registerFullRun.pending,
    selectedTeamRegisterExperimentFullRunResultError: registerFullRun.error,
    selectedTeamRegisterExperimentFullRunResultResult: registerFullRun.result,
    selectedTeamRequestExperimentKnowledgeIngestionPending: requestKnowledge.pending,
    selectedTeamRequestExperimentKnowledgeIngestionError: requestKnowledge.error,
    selectedTeamRequestExperimentKnowledgeIngestionResult: requestKnowledge.result,
    selectedTeamCreateResearchLoopPending: createLoop.pending,
    selectedTeamCreateResearchLoopError: createLoop.error,
    selectedTeamCreateResearchLoopResult: createLoop.result,
    selectedTeamRecordResearchLoopEvidencePending: recordEvidence.pending,
    selectedTeamRecordResearchLoopEvidenceError: recordEvidence.error,
    selectedTeamRecordResearchLoopEvidenceResult: recordEvidence.result,
    selectedTeamRecordResearchLoopDecisionPending: recordDecision.pending,
    selectedTeamRecordResearchLoopDecisionError: recordDecision.error,
    selectedTeamRecordResearchLoopDecisionResult: recordDecision.result,
    selectedTeamStartSourceCollectionPending: startSc.pending,
    selectedTeamStartSourceCollectionError: startSc.error,
    selectedTeamStartSourceCollectionResult: startSc.result,
    selectedTeamStartSourceCollectionStageTaskPending: startStageTask.pending,
    selectedTeamStartSourceCollectionStageTaskError: startStageTask.error,
    sourceCollectionStageSessionTaskPendingStageId: startStageTask.pending
      ? String(input.startSourceCollectionStageSessionTask.variables?.stageId || "")
      : "",
    selectedTeamRecordSourceCollectionOutputPending: recordOutput.pending,
    selectedTeamRecordSourceCollectionOutputError: recordOutput.error,
    selectedTeamRecordSourceCollectionOutputResult: recordOutput.result,
    selectedTeamExecuteSourceCollectionSearchPending: executeSearch.pending,
    selectedTeamExecuteSourceCollectionSearchError: executeSearch.error,
    selectedTeamExecuteSourceCollectionSearchResult: executeSearch.result,
    selectedTeamExtractSourceCollectionCandidatesPending: extractCandidates.pending,
    selectedTeamExtractSourceCollectionCandidatesError: extractCandidates.error,
    selectedTeamExtractSourceCollectionCandidatesResult: extractResult,
    selectedSourceCollectionStorageOpenPending: openStorage.pending,
    selectedSourceCollectionStorageOpenResult: openStorage.result,
    selectedSourceCollectionStorageOpenError: openStorage.error,
    selectedTeamStartAiSearchPending: startAiSearch.pending,
    selectedTeamStartAiSearchError: startAiSearch.error,
    selectedTeamStartAiSearchResult: startAiSearch.result,
  };
}

export type TeamsRouteMutationSurface = ReturnType<typeof buildTeamsRouteMutationSurface>;
