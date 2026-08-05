/**
 * F3 — pure pipeline step-state derivation for SC presentation.
 */
import type { SourceCollectionStepState } from "./runModel";
import {
  sourceCollectionStageProjectionState,
  type SourceCollectionStageCardProjection,
} from "./stageProjection";

export function sourceCollectionStepStatusText(
  lang: "zh" | "en",
  state: SourceCollectionStepState,
): string {
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
}

export type SourceCollectionPipelineStepStatesInput = {
  searchFallback: SourceCollectionStepState;
  collectionProjection: SourceCollectionStageCardProjection | null | undefined;
  screeningProjection: SourceCollectionStageCardProjection | null | undefined;
  candidateProjection: SourceCollectionStageCardProjection | null | undefined;
  graphProjection: SourceCollectionStageCardProjection | null | undefined;
  memoryProjection: SourceCollectionStageCardProjection | null | undefined;
  extractionCanProceedAfterExclusions: boolean;
  sourceQualityError: boolean;
  sourceQualityPending: boolean;
  runAssessedCount: number;
  displayedCandidateCount: number;
  searchOpenAssignmentCount: number;
  recordOutputError: boolean;
  extractError: boolean;
  recordOutputPending: boolean;
  extractPending: boolean;
  hasRun: boolean;
  graphError: boolean;
  graphQueryError: boolean;
  graphPending: boolean;
  graphNodeCount: number;
  runApprovedCount: number;
  knowledgeQueryError: boolean;
  knowledgePrecheckError: boolean;
  knowledgeIngestError: boolean;
  knowledgePrecheckPending: boolean;
  knowledgeIngestPending: boolean;
  formalKnowledgeItemCount: number;
  knowledgePendingReviewCount: number;
  knowledgeStewardPackCount: number;
  ingestCandidateCount: number;
};

export type SourceCollectionPipelineStepStates = {
  searchStepState: SourceCollectionStepState;
  screeningFallbackStepState: SourceCollectionStepState;
  screeningStepStateRaw: SourceCollectionStepState;
  screeningStepState: SourceCollectionStepState;
  candidateFallbackStepState: SourceCollectionStepState;
  candidateStepStateRaw: SourceCollectionStepState;
  candidateStepState: SourceCollectionStepState;
  extractionDefaultPanelId: string;
  graphFallbackStepState: SourceCollectionStepState;
  graphStepState: SourceCollectionStepState;
  memoryFallbackStepState: SourceCollectionStepState;
  memoryStepState: SourceCollectionStepState;
  extractionStepState: SourceCollectionStepState;
};

export function buildSourceCollectionPipelineStepStates(
  input: SourceCollectionPipelineStepStatesInput,
): SourceCollectionPipelineStepStates {
  const searchStepState = sourceCollectionStageProjectionState(
    input.collectionProjection,
    input.searchFallback,
  );
  const screeningFallbackStepState: SourceCollectionStepState = input.sourceQualityError
    ? "failed"
    : input.sourceQualityPending
      ? "active"
      : input.runAssessedCount > 0
        ? "done"
        : input.displayedCandidateCount > 0 && input.searchOpenAssignmentCount <= 0
          ? "pending"
          : "idle";
  const screeningStepStateRaw = sourceCollectionStageProjectionState(
    input.screeningProjection,
    screeningFallbackStepState,
  );
  const screeningStepState: SourceCollectionStepState = input.extractionCanProceedAfterExclusions
    ? "done"
    : screeningStepStateRaw;
  const candidateFallbackStepState: SourceCollectionStepState =
    input.recordOutputError || input.extractError
      ? "failed"
      : input.recordOutputPending || input.extractPending
        ? "active"
        : input.displayedCandidateCount > 0
          ? "done"
          : input.hasRun
            ? "pending"
            : "idle";
  const candidateStepStateRaw = sourceCollectionStageProjectionState(
    input.candidateProjection,
    candidateFallbackStepState,
  );
  const candidateStepState: SourceCollectionStepState = input.extractionCanProceedAfterExclusions
    ? "done"
    : candidateStepStateRaw;
  const graphFallbackStepState: SourceCollectionStepState =
    input.graphError || input.graphQueryError
      ? "failed"
      : input.graphPending
        ? "active"
        : input.graphNodeCount > 0
          ? "done"
          : input.runApprovedCount > 0
            ? "pending"
            : "idle";
  const graphStepState = sourceCollectionStageProjectionState(
    input.graphProjection,
    graphFallbackStepState,
  );
  const memoryFallbackStepState: SourceCollectionStepState =
    input.knowledgeQueryError || input.knowledgePrecheckError || input.knowledgeIngestError
      ? "failed"
      : input.knowledgePrecheckPending || input.knowledgeIngestPending
        ? "active"
        : input.formalKnowledgeItemCount > 0
          ? "done"
          : input.knowledgePendingReviewCount > 0
            || input.knowledgeStewardPackCount > 0
            || input.ingestCandidateCount > 0
            ? "pending"
            : "idle";
  const memoryStepState = sourceCollectionStageProjectionState(
    input.memoryProjection,
    memoryFallbackStepState,
  );
  const extractionStepState: SourceCollectionStepState =
    candidateStepState === "failed" || screeningStepState === "failed"
      ? "failed"
      : candidateStepState === "active" || screeningStepState === "active"
        ? "active"
        : input.displayedCandidateCount > 0
          ? screeningStepState
          : candidateStepState;

  return {
    searchStepState,
    screeningFallbackStepState,
    screeningStepStateRaw,
    screeningStepState,
    candidateFallbackStepState,
    candidateStepStateRaw,
    candidateStepState,
    extractionDefaultPanelId: "source-collection-screening-panel",
    graphFallbackStepState,
    graphStepState,
    memoryFallbackStepState,
    memoryStepState,
    extractionStepState,
  };
}
