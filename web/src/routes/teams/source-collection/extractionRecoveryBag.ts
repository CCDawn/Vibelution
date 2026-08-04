/**
 * Active-stage extraction recovery bag assembled by TeamsRoute and consumed by
 * TeamSourceCollectionActiveStageWorkspacePanel.
 */
import type { SourceCollectionStageCardProjection } from "./stageProjection";

export type SourceCollectionExtractionRecoveryBag = {
  candidateProjection: SourceCollectionStageCardProjection | null | undefined;
  sourceCollectionRawRecordCount: number;
  sourceCollectionRunApprovedCount: number;
  sourceCollectionDisplayedCandidateCount: number;
  sourceCollectionPrimaryDataLoading: boolean;
  sourceCollectionLoadingText: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionCandidateStepState: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionExtractionExcludedRecoveryState: any;
  runSourceCollectionCandidateExtractionAction: () => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionCandidateExtractionActionReadiness: any;
  runSourceCollectionScreeningAction: () => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionScreeningActionReadiness: any;
  sourceCollectionScreeningButtonText: string;
  sourceCollectionScreeningButtonTitle?: string;
  sourceCollectionRunPendingScreeningCountText: string;
  sourceCollectionQualityBatchFeedback?: string | null;
  needsAgentMaterial?: boolean;
  pendingScreeningCount?: number;
  pendingImportCount?: number;
  canProceedAfterExclusions?: boolean;
  qualityReviewPending?: boolean;
  advanceToRelations?: () => void;
  unverifiableCandidateCount?: number;
  excludeUnverifiableCandidates?: () => Promise<void>;
  excludeUnverifiableCandidatesPending?: boolean;
};

/**
 * Normalize the extraction recovery bag for the active-stage card.
 * Keeps numeric counters finite and preserves action callbacks from the route.
 */
export function buildSourceCollectionExtractionRecoveryBag(
  input: SourceCollectionExtractionRecoveryBag,
): SourceCollectionExtractionRecoveryBag {
  return {
    ...input,
    sourceCollectionRawRecordCount: Math.max(0, Number(input.sourceCollectionRawRecordCount) || 0),
    sourceCollectionRunApprovedCount: Math.max(0, Number(input.sourceCollectionRunApprovedCount) || 0),
    sourceCollectionDisplayedCandidateCount: Math.max(0, Number(input.sourceCollectionDisplayedCandidateCount) || 0),
    pendingScreeningCount: Math.max(0, Number(input.pendingScreeningCount) || 0),
    pendingImportCount: Math.max(0, Number(input.pendingImportCount) || 0),
    unverifiableCandidateCount: Math.max(0, Number(input.unverifiableCandidateCount) || 0),
    needsAgentMaterial: Boolean(input.needsAgentMaterial),
    canProceedAfterExclusions: Boolean(input.canProceedAfterExclusions),
    qualityReviewPending: Boolean(input.qualityReviewPending),
  };
}
