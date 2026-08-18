/**
 * Pure: team-scoped pending flags for createExperimentWorkspaceActions.
 * Extracted from useTeamsWorkbenchModel (behavior-conserving).
 */

type PendingTeamMutation = {
  isPending: boolean;
  variables?: { teamId?: string; candidateId?: string } | null;
};

export type ExperimentWorkspacePendingFlags = {
  createExperimentPlanPending: boolean;
  materializeEngineeringProxyPending: boolean;
  completeScientificHypothesisCandidateId: string;
  reviewExperimentHypothesisCandidateId: string;
  createExperimentHypothesisRevisionCandidateId: string;
  freezeExperimentDesignPending: boolean;
  resumeExperimentHypothesisPending: boolean;
  registerExperimentBaselineArtifactPending: boolean;
  registerExperimentSmokeResultPending: boolean;
  runExperimentSmokePending: boolean;
  registerExperimentFullRunResultPending: boolean;
  requestExperimentKnowledgeIngestionPending: boolean;
  createResearchLoopPending: boolean;
  recordResearchLoopEvidencePending: boolean;
  recordResearchLoopDecisionPending: boolean;
};

function teamPending(mutation: PendingTeamMutation, teamId: string): boolean {
  return mutation.isPending && mutation.variables?.teamId === teamId;
}

function teamPendingCandidateId(mutation: PendingTeamMutation, teamId: string): string {
  return teamPending(mutation, teamId) ? String(mutation.variables?.candidateId || "") : "";
}

export function buildExperimentWorkspacePendingFlags(options: {
  teamId: string;
  createExperimentPlanMutation: PendingTeamMutation;
  materializeEngineeringProxyHypothesisMutation: PendingTeamMutation;
  completeScientificHypothesisFromDesignMutation: PendingTeamMutation;
  reviewExperimentHypothesisMutation: PendingTeamMutation;
  createExperimentHypothesisRevisionMutation: PendingTeamMutation;
  freezeExperimentDesignMutation: PendingTeamMutation;
  resumeExperimentHypothesisMutation: PendingTeamMutation;
  registerExperimentBaselineArtifactMutation: PendingTeamMutation;
  registerExperimentSmokeResultMutation: PendingTeamMutation;
  runExperimentSmokeMutation: PendingTeamMutation;
  registerExperimentFullRunResultMutation: PendingTeamMutation;
  requestExperimentKnowledgeIngestionMutation: PendingTeamMutation;
  createResearchLoopMutation: PendingTeamMutation;
  recordResearchLoopEvidenceMutation: PendingTeamMutation;
  recordResearchLoopDecisionMutation: PendingTeamMutation;
}): ExperimentWorkspacePendingFlags {
  const { teamId } = options;
  return {
    createExperimentPlanPending: teamPending(options.createExperimentPlanMutation, teamId),
    materializeEngineeringProxyPending: teamPending(options.materializeEngineeringProxyHypothesisMutation, teamId),
    completeScientificHypothesisCandidateId: teamPendingCandidateId(
      options.completeScientificHypothesisFromDesignMutation,
      teamId,
    ),
    reviewExperimentHypothesisCandidateId: teamPendingCandidateId(
      options.reviewExperimentHypothesisMutation,
      teamId,
    ),
    createExperimentHypothesisRevisionCandidateId: teamPendingCandidateId(
      options.createExperimentHypothesisRevisionMutation,
      teamId,
    ),
    freezeExperimentDesignPending: teamPending(options.freezeExperimentDesignMutation, teamId),
    resumeExperimentHypothesisPending: teamPending(options.resumeExperimentHypothesisMutation, teamId),
    registerExperimentBaselineArtifactPending: teamPending(
      options.registerExperimentBaselineArtifactMutation,
      teamId,
    ),
    registerExperimentSmokeResultPending: teamPending(
      options.registerExperimentSmokeResultMutation,
      teamId,
    ),
    runExperimentSmokePending: teamPending(options.runExperimentSmokeMutation, teamId),
    registerExperimentFullRunResultPending: teamPending(
      options.registerExperimentFullRunResultMutation,
      teamId,
    ),
    requestExperimentKnowledgeIngestionPending: teamPending(
      options.requestExperimentKnowledgeIngestionMutation,
      teamId,
    ),
    createResearchLoopPending: teamPending(options.createResearchLoopMutation, teamId),
    recordResearchLoopEvidencePending: teamPending(options.recordResearchLoopEvidenceMutation, teamId),
    recordResearchLoopDecisionPending: teamPending(options.recordResearchLoopDecisionMutation, teamId),
  };
}
