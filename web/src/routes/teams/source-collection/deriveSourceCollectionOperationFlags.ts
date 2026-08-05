/**
 * Pure run/operation flags for SC presentation (R2-q).
 */
import { workRunString } from "../workflowPresentation";
import { deriveSourceCollectionDisplayState } from "./runModel";

export type DeriveSourceCollectionOperationFlagsInput = {
  lang: "zh" | "en";
  runStatus?: { runStatus?: string } | null;
  selectedRunStatus?: string;
  selectedSourceCollectionSearchAccepted: boolean;
  selectedSourceCollectionActiveWorkRun: any;
  teamId?: string;
  selectedSourceCollectionRunEffectiveId: string;
  outputAssignmentId?: string;
  selectedAssignmentId?: string;
  sourceCollectionOutputHasRecord: boolean;
  selectedTeamRecordSourceCollectionOutputPending: boolean;
  sourceCollectionAssignmentsDataLoading: boolean;
  sourceCollectionActionDataError: boolean;
  sourceCollectionSearchOpenAssignmentCount: number;
  selectedTeamExecuteSourceCollectionSearchPending: boolean;
  selectedTeamStartResearchStageError: unknown;
  selectedTeamStartSourceCollectionError: unknown;
  selectedTeamExecuteSourceCollectionSearchError: unknown;
  selectedTeamExtractSourceCollectionCandidatesError: unknown;
  selectedTeamRecordSourceCollectionOutputError: unknown;
  selectedTeamSourceQualityError: unknown;
  selectedTeamBuildCandidateGraphError: unknown;
  selectedTeamKnowledgePrecheckError: unknown;
  selectedTeamKnowledgeCollectionIngestError: unknown;
  selectedTeamStartSourceCollectionStageTaskError: unknown;
  selectedTeamStartResearchStagePending: boolean;
  selectedTeamStartSourceCollectionPending: boolean;
  selectedTeamStartSourceCollectionStageTaskPending: boolean;
  selectedTeamRecordSourceCollectionOutputPending: boolean;
  selectedTeamExtractSourceCollectionCandidatesPending: boolean;
  selectedTeamSourceQualityPending: boolean;
  selectedTeamBuildCandidateGraphPending: boolean;
  selectedTeamKnowledgePrecheckPending: boolean;
  selectedTeamKnowledgeCollectionIngestPending: boolean;
  hasRun: boolean;
  searchOpenAssignmentCount: number;
  downstreamOpenAssignmentCount: number;
  pendingScreeningCount: number;
  rawRecordCount: number;
  candidateCount: number;
};

export function deriveSourceCollectionOperationFlags(input: DeriveSourceCollectionOperationFlagsInput) {
  const sourceCollectionRunStatusValue = String(
    input.runStatus?.runStatus || input.selectedRunStatus || "",
  ).toLowerCase();
  const sourceCollectionAcceptedBackgroundActive = Boolean(
    input.selectedSourceCollectionSearchAccepted
    && input.selectedSourceCollectionActiveWorkRun
    && ["running", "queued"].includes(String(input.selectedSourceCollectionActiveWorkRun.status || "").toLowerCase()),
  );
  const canRecordSourceCollectionOutput = Boolean(
    input.teamId
    && input.selectedSourceCollectionRunEffectiveId
    && (input.outputAssignmentId || input.selectedAssignmentId)
    && input.sourceCollectionOutputHasRecord
    && !input.selectedTeamRecordSourceCollectionOutputPending,
  );
  const canExecuteSourceCollectionSearch = Boolean(
    input.teamId
    && input.selectedSourceCollectionRunEffectiveId
    && !input.sourceCollectionAssignmentsDataLoading
    && !input.sourceCollectionActionDataError
    && input.sourceCollectionSearchOpenAssignmentCount > 0
    && !input.selectedTeamExecuteSourceCollectionSearchPending
    && !sourceCollectionAcceptedBackgroundActive,
  );
  const sourceCollectionAcceptedBackgroundFailed = Boolean(
    input.selectedSourceCollectionActiveWorkRun
    && ["failed", "blocked"].includes(String(input.selectedSourceCollectionActiveWorkRun.status || "").toLowerCase()),
  );
  const sourceCollectionOperationFailed = Boolean(
    sourceCollectionRunStatusValue === "failed"
    || sourceCollectionRunStatusValue === "blocked"
    || sourceCollectionAcceptedBackgroundFailed
    || input.selectedTeamStartResearchStageError
    || input.selectedTeamStartSourceCollectionError
    || input.selectedTeamExecuteSourceCollectionSearchError
    || input.selectedTeamExtractSourceCollectionCandidatesError
    || input.selectedTeamRecordSourceCollectionOutputError
    || input.selectedTeamSourceQualityError
    || input.selectedTeamBuildCandidateGraphError
    || input.selectedTeamKnowledgePrecheckError
    || input.selectedTeamKnowledgeCollectionIngestError
    || input.selectedTeamStartSourceCollectionStageTaskError
  );
  const sourceCollectionDisplayState = deriveSourceCollectionDisplayState({
    lang: input.lang,
    hasRun: input.hasRun,
    startPending: input.selectedTeamStartResearchStagePending || input.selectedTeamStartSourceCollectionPending || input.selectedTeamStartSourceCollectionStageTaskPending,
    searchPending: input.selectedTeamExecuteSourceCollectionSearchPending,
    backgroundActive: sourceCollectionAcceptedBackgroundActive,
    recordOutputPending: input.selectedTeamRecordSourceCollectionOutputPending,
    extractionPending: input.selectedTeamExtractSourceCollectionCandidatesPending,
    sourceQualityPending: input.selectedTeamSourceQualityPending,
    graphPending: input.selectedTeamBuildCandidateGraphPending,
    knowledgeIngestionPending: input.selectedTeamKnowledgePrecheckPending || input.selectedTeamKnowledgeCollectionIngestPending,
    failed: sourceCollectionOperationFailed,
    searchOpenAssignmentCount: input.searchOpenAssignmentCount,
    downstreamOpenAssignmentCount: input.downstreamOpenAssignmentCount,
    pendingScreeningCount: input.pendingScreeningCount,
    rawRecordCount: input.rawRecordCount,
    candidateCount: input.candidateCount,
    activeWorkSummary: workRunString(input.selectedSourceCollectionActiveWorkRun, "currentTask")
      || workRunString(input.selectedSourceCollectionActiveWorkRun, "summary"),
  });
  return {
    sourceCollectionRunStatusValue,
    sourceCollectionAcceptedBackgroundActive,
    canRecordSourceCollectionOutput,
    canExecuteSourceCollectionSearch,
    sourceCollectionAcceptedBackgroundFailed,
    sourceCollectionOperationFailed,
    sourceCollectionDisplayState,
  };
}
