/**
 * Pure summary / stage-card / records projection for SC presentation.
 * Phase R2-o extract from useSourceCollectionPresentationCore (behavior-conserving).
 */
import type {
  DataProcessingCollectionAssignment,
  DataProcessingRecord,
  DataProcessingStatus,
} from "../../../api/types";
import { isRecord } from "../workflowPresentation";
import { latestWorkflowCandidate, workflowCandidateGraphFromCandidate, parseSourceCollectionStageModuleId } from "../teamRouteShellModel";
import {
  selectSourceCollectionStageRound,
  sourceCollectionPhaseCloseGateForRun,
  type ResearchStageRound,
  type SourceCollectionStageCardProjection,
  type SourceCollectionStageModuleId,
} from "./stageProjection";

export type DeriveSourceCollectionSummaryProjectionInput = {
  teamWorkflowCandidateGraphQueryData: { candidates?: unknown[] } | null | undefined;
  sourceCollectionSummaryQueryData: any;
  sourceCollectionRecordsQueryData: { records?: unknown } | null | undefined;
  sourceCollectionAssignmentsQueryData: { assignments?: unknown } | null | undefined;
  sourceCollectionRunStatusQueryData: DataProcessingStatus | null | undefined;
  selectedSourceCollectionRun: { scope?: { dataSearchPlanRef?: unknown } } | null | undefined;
  selectedSourceCollectionRunEffectiveId: string;
  researchStagePhases: any[];
  researchStageRoundStatus: any;
  aiSearchRunsQueryData: { runs?: unknown[] } | null | undefined;
  researchLoopTemplatesQueryData: unknown;
  researchLoopStatusQueryData: unknown;
  experimentPlanningStatusQueryData: unknown;
};

export function deriveSourceCollectionSummaryProjection(
  input: DeriveSourceCollectionSummaryProjectionInput,
) {
  const {
    teamWorkflowCandidateGraphQueryData,
    sourceCollectionSummaryQueryData,
    sourceCollectionRecordsQueryData,
    sourceCollectionAssignmentsQueryData,
    sourceCollectionRunStatusQueryData,
    selectedSourceCollectionRun,
    selectedSourceCollectionRunEffectiveId,
    researchStagePhases,
    researchStageRoundStatus,
    aiSearchRunsQueryData,
    researchLoopTemplatesQueryData,
    researchLoopStatusQueryData,
    experimentPlanningStatusQueryData,
  } = input;

  const teamWorkflowCandidateGraphRecord = latestWorkflowCandidate(
    teamWorkflowCandidateGraphQueryData?.candidates ?? [],
  );
  const teamWorkflowCandidateGraph = workflowCandidateGraphFromCandidate(teamWorkflowCandidateGraphRecord);

  const sourceCollectionSummary = sourceCollectionSummaryQueryData ?? null;
  const sourceCollectionSummaryRun = isRecord(sourceCollectionSummary?.run) ? sourceCollectionSummary.run : null;
  const sourceCollectionSummaryRunId = String(sourceCollectionSummaryRun?.runId || sourceCollectionSummary?.runId || "");
  const sourceCollectionActionRunId = selectedSourceCollectionRunEffectiveId || sourceCollectionSummaryRunId;
  const sourceCollectionPhaseCloseGate = sourceCollectionPhaseCloseGateForRun(
    sourceCollectionSummary,
    selectedSourceCollectionRunEffectiveId,
  );

  let sourceCollectionSummaryStageRound: ResearchStageRound | null = null;
  if (sourceCollectionSummary?.runId || sourceCollectionSummary?.stageCards?.length) {
    const summaryRunId = String(sourceCollectionSummary.runId || sourceCollectionSummaryRunId || "");
    if (!(selectedSourceCollectionRunEffectiveId && summaryRunId && summaryRunId !== selectedSourceCollectionRunEffectiveId)) {
      const roundRef = sourceCollectionSummary.stageRound ?? {};
      sourceCollectionSummaryStageRound = {
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
    }
  }

  const sourceCollectionStageRound = selectSourceCollectionStageRound(
    sourceCollectionSummaryStageRound,
    researchStagePhases,
    researchStageRoundStatus,
    selectedSourceCollectionRunEffectiveId,
  );
  const sourceCollectionStageCards = sourceCollectionStageRound?.sourceCollectionStageCards ?? [];
  const sourceCollectionStageCardById = (() => {
    const mapping = new Map<SourceCollectionStageModuleId, SourceCollectionStageCardProjection>();
    sourceCollectionStageCards.forEach((card) => {
      const stageId = parseSourceCollectionStageModuleId(card.stageId);
      if (stageId) {
        mapping.set(stageId, { ...card, stageId });
      }
    });
    return mapping;
  })();

  const experimentPlanningStatus = experimentPlanningStatusQueryData ?? null;
  const sourceCollectionRecords: DataProcessingRecord[] = Array.isArray(sourceCollectionRecordsQueryData?.records)
    ? (sourceCollectionRecordsQueryData.records as DataProcessingRecord[])
    : [];
  const sourceCollectionAssignments: DataProcessingCollectionAssignment[] = Array.isArray(
    sourceCollectionAssignmentsQueryData?.assignments,
  )
    ? (sourceCollectionAssignmentsQueryData.assignments as DataProcessingCollectionAssignment[])
    : [];
  const sourceCollectionRunStatus =
    sourceCollectionRunStatusQueryData ?? sourceCollectionSummary?.runStatus ?? null;
  const sourceCollectionSearchPlanRef = selectedSourceCollectionRun?.scope?.dataSearchPlanRef ?? null;
  const aiSearchRuns = Array.isArray(aiSearchRunsQueryData?.runs) ? aiSearchRunsQueryData.runs : [];
  const researchLoopTemplatesPayload = researchLoopTemplatesQueryData ?? null;
  const researchLoopStatus = researchLoopStatusQueryData ?? null;

  return {
    teamWorkflowCandidateGraphRecord,
    teamWorkflowCandidateGraph,
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
  };
}
