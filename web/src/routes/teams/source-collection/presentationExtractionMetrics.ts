/**
 * F3 — pure extraction-recovery / focus-label metrics for SC presentation.
 * Keep useSourceCollectionPresentation as a wiring hook; edit copy/math here.
 */
import {
  deriveSourceCollectionExcludedRecoveryState,
  sourceCollectionEvidenceLedgerSummary,
} from "./evidenceModel";
import {
  sourceCollectionCandidateQualityState,
  sourceCollectionMaterialGapCount,
} from "./presentationModel";
import {
  sourceCollectionBoundCountToCurrentCoverage,
  sourceCollectionNonNegativeCount,
  sourceCollectionStageProjectionCount,
  type SourceCollectionStageCardProjection,
} from "./stageProjection";

export type ExtractionRecoveryMetricsInput = {
  lang: "zh" | "en";
  candidateProjection: SourceCollectionStageCardProjection | null | undefined;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  reviewableRunCandidates: any[];
  rawRecordCount: number;
  displayedCandidateCount: number;
  runNeedsRevisionCount: number;
  projectedApprovedCount: number;
  runPendingScreeningCount: number;
  excludedSourceCount: number;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  extractResult?: any;
  hasCurrentCandidates: boolean;
};

export type ExtractionRecoveryMetrics = {
  recoveryCoverage: unknown;
  recoveryClosure: unknown;
  sourceVerificationCount: number;
  unverifiableCandidateIds: string[];
  missingEvidenceAnchorCount: number;
  agentMaterialCount: number;
  needsAgentMaterial: boolean;
  recoveryMissingCount: number;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  excludedRecoveryState: any;
  canProceedAfterExclusions: boolean;
  proceedableSummary: string;
  pendingCandidateImportCount: number;
};

export function deriveSourceCollectionExtractionRecoveryMetrics(
  input: ExtractionRecoveryMetricsInput,
): ExtractionRecoveryMetrics {
  const {
    lang,
    candidateProjection,
    reviewableRunCandidates,
    rawRecordCount,
    displayedCandidateCount,
    runNeedsRevisionCount,
    projectedApprovedCount,
    runPendingScreeningCount,
    excludedSourceCount,
    extractResult,
    hasCurrentCandidates,
  } = input;

  const pendingCandidateImportCount = Math.max(0, rawRecordCount - displayedCandidateCount);
  const recoveryCoverage = candidateProjection?.currentCoverageSummary?.applicable
    ? candidateProjection.currentCoverageSummary
    : candidateProjection?.latestTask?.coverageSummary;
  const recoveryClosure = candidateProjection?.latestTask?.closureSummary;
  const sourceVerificationCount = Math.max(
    sourceCollectionNonNegativeCount((recoveryClosure as { blockedCount?: number } | undefined)?.blockedCount),
    sourceCollectionNonNegativeCount((recoveryCoverage as { blocked?: number } | undefined)?.blocked),
  );

  const blockedCount = sourceVerificationCount;
  const unverifiableCandidateIds =
    blockedCount <= 0
      ? []
      : reviewableRunCandidates
        .filter((candidate) => {
          const quality = sourceCollectionCandidateQualityState(candidate);
          const evidence = sourceCollectionEvidenceLedgerSummary(candidate);
          return quality.needsRevision && evidence?.missingAnchor !== true;
        })
        .map((candidate) => String(candidate.candidateId || "").trim())
        .filter(Boolean)
        .slice(0, blockedCount);

  const missingEvidenceAnchorCount = sourceCollectionBoundCountToCurrentCoverage(
    candidateProjection,
    candidateProjection?.latestTask?.materializedContentExtraction?.missingEvidenceAnchorCount,
  );
  const agentMaterialCount = sourceCollectionMaterialGapCount({
    hasCurrentCandidates,
    needsRevisionCount: runNeedsRevisionCount,
    missingEvidenceAnchorCount,
    taskBlockedCount: sourceVerificationCount,
    projectedPendingCount: sourceCollectionStageProjectionCount(candidateProjection, "pending", 0),
  });
  const needsAgentMaterial = agentMaterialCount > 0;
  const recoveryMissingCount = Math.max(
    sourceCollectionNonNegativeCount((recoveryCoverage as { missing?: number } | undefined)?.missing),
    sourceCollectionStageProjectionCount(candidateProjection, "pending", 0),
    pendingCandidateImportCount,
    sourceCollectionNonNegativeCount(extractResult?.pendingRecordCount),
  );
  const excludedRecoveryState = deriveSourceCollectionExcludedRecoveryState({
    lang,
    excludedCount: Math.max(
      excludedSourceCount,
      sourceCollectionNonNegativeCount((recoveryClosure as { excludedSourceCount?: number } | undefined)?.excludedSourceCount),
      sourceCollectionStageProjectionCount(candidateProjection, "excluded", 0),
    ),
    missingCount: recoveryMissingCount,
    importFailedCount: sourceCollectionNonNegativeCount(extractResult?.failedCount),
    importPendingRecordCount: Math.max(
      pendingCandidateImportCount,
      sourceCollectionNonNegativeCount(extractResult?.pendingRecordCount),
    ),
  });
  const canProceedAfterExclusions = Boolean(
    excludedRecoveryState.blockedByExcludedSources
    && projectedApprovedCount > 0
    && runPendingScreeningCount <= 0,
  );
  const proceedableSummary = lang === "zh"
    ? `${projectedApprovedCount} 条可进入关系整理；剩余 ${excludedRecoveryState.excludedCount} 条已排除，可查看原因或补充新来源。`
    : `${projectedApprovedCount} ready for relation mapping; ${excludedRecoveryState.excludedCount} excluded sources can be inspected or replaced.`;

  return {
    recoveryCoverage,
    recoveryClosure,
    sourceVerificationCount,
    unverifiableCandidateIds,
    missingEvidenceAnchorCount,
    agentMaterialCount,
    needsAgentMaterial,
    recoveryMissingCount,
    excludedRecoveryState,
    canProceedAfterExclusions,
    proceedableSummary,
    pendingCandidateImportCount,
  };
}

export function sourceCollectionStageFocusLabel(input: {
  lang: "zh" | "en";
  hasRun: boolean;
  searchOpenAssignmentCount: number;
  downstreamOpenAssignmentCount: number;
  runPendingScreeningCount: number;
  displayedCandidateCount: number;
}): string {
  const {
    lang,
    hasRun,
    searchOpenAssignmentCount,
    downstreamOpenAssignmentCount,
    runPendingScreeningCount,
    displayedCandidateCount,
  } = input;
  if (!hasRun) {
    return lang === "zh" ? "尚未启动" : "not started";
  }
  if (searchOpenAssignmentCount > 0) {
    return lang === "zh" ? "继续搜索" : "continue search";
  }
  if (downstreamOpenAssignmentCount > 0) {
    return lang === "zh" ? "继续提炼" : "continue extraction";
  }
  if (runPendingScreeningCount > 0) {
    return lang === "zh" ? "继续审查" : "continue review";
  }
  if (displayedCandidateCount > 0) {
    return lang === "zh" ? "准备实验" : "plan experiment";
  }
  return lang === "zh" ? "等待结果回写" : "waiting for writeback";
}
