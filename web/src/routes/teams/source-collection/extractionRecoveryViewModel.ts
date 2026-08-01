/**
 * Pure view-model for source-collection extraction recovery / verification gate.
 * Shared by the standalone recovery banner and the integrated extraction stage card.
 */
import {
  sourceCollectionNonNegativeCount,
  sourceCollectionStageRecoveryStatusLabel,
  sourceCollectionStageUserSummary,
  type SourceCollectionStageCardProjection,
} from "./stageProjection";

export type ExtractionRecoveryTone = "danger" | "progressable";

export type ExtractionRecoveryViewModel = {
  tone: ExtractionRecoveryTone;
  titleLabel: string;
  statusLabel: string;
  summary: string;
  failedLabel: string;
  failedText: string;
  salvageLabel: string;
  salvageText: string;
  recoverLabel: string;
  recoverText: string;
  pendingReviewText: string;
  primaryActionText: string;
  primaryActionTitle: string | undefined;
  primaryActionKind: "chat" | "continue_task";
  showImportAction: boolean;
  importActionText: string;
  qualityReviewActionText: string;
  qualityReviewActionTitle: string;
  ariaLabel: string;
  /** Prefer recovery primary CTA over stage default primary when true. */
  preferPrimaryOverStageAction: boolean;
};

export type BuildExtractionRecoveryViewModelInput = {
  candidateProjection: SourceCollectionStageCardProjection | null | undefined;
  lang: "zh" | "en";
  sourceCollectionRawRecordCount: number;
  sourceCollectionRunApprovedCount: number;
  sourceCollectionDisplayedCandidateCount: number;
  sourceCollectionPrimaryDataLoading: boolean;
  sourceCollectionLoadingText: string;
  sourceCollectionCandidateStepState: string | null | undefined;
  sourceCollectionExtractionExcludedRecoveryState: {
    blockedByExcludedSources?: boolean;
    tone?: ExtractionRecoveryTone;
    summary?: string;
    statusLabel?: string;
    panelTitle?: string;
    panelAriaLabel?: string;
    failedLabel?: string;
    recoverLabel?: string;
    recoverText?: string;
    primaryActionText?: string;
    primaryActionTitle?: string;
  };
  sourceCollectionStageActionReadinessDisabled: boolean;
  sourceCollectionActionDisabledTitle: (label: string) => string | undefined;
  sourceCollectionRunPendingScreeningCountText: string;
};

function missingEvidenceAnchorCount(
  candidateProjection: SourceCollectionStageCardProjection | null | undefined,
): number | undefined {
  const materialized = candidateProjection?.latestTask?.materializedContentExtraction;
  const value = materialized?.missingEvidenceAnchorCount;
  return typeof value === "number" && Number.isFinite(value)
    ? Math.max(0, value)
    : undefined;
}

export function buildExtractionRecoveryViewModel(
  input: BuildExtractionRecoveryViewModelInput,
): ExtractionRecoveryViewModel | null {
  const {
    candidateProjection,
    lang,
    sourceCollectionRawRecordCount,
    sourceCollectionRunApprovedCount,
    sourceCollectionDisplayedCandidateCount,
    sourceCollectionPrimaryDataLoading,
    sourceCollectionLoadingText,
    sourceCollectionCandidateStepState,
    sourceCollectionExtractionExcludedRecoveryState,
    sourceCollectionStageActionReadinessDisabled,
    sourceCollectionActionDisabledTitle,
    sourceCollectionRunPendingScreeningCountText,
  } = input;

  const currentCoverage = candidateProjection?.currentCoverageSummary;
  const hasCurrentCoverage = Boolean(currentCoverage?.applicable);
  const currentCoverageComplete = hasCurrentCoverage && currentCoverage?.complete === true;
  const recoveryCoverage = hasCurrentCoverage
    ? currentCoverage
    : candidateProjection?.latestTask?.coverageSummary;
  const recoveryClosure = candidateProjection?.latestTask?.closureSummary;
  const recoveryNumber = sourceCollectionNonNegativeCount;
  const currentCoverageTotal = recoveryNumber(currentCoverage?.total);
  const inputCount = hasCurrentCoverage && currentCoverageTotal > 0
    ? currentCoverageTotal
    : Math.max(
      recoveryNumber(recoveryCoverage?.total),
      recoveryNumber(candidateProjection?.counts?.input),
      sourceCollectionRawRecordCount,
    );
  const invalidCount = Math.max(
    recoveryNumber(recoveryCoverage?.invalid),
    recoveryClosure?.invalidIds?.length ?? 0,
    candidateProjection?.latestTask?.invalidRecordIds?.length ?? 0,
    candidateProjection?.latestTask?.invalidCandidateIds?.length ?? 0,
  );
  const coverageMissingCount = recoveryNumber(recoveryCoverage?.missing);
  const sourceVerificationCount = Math.max(
    recoveryNumber(recoveryClosure?.blockedCount),
    recoveryNumber(recoveryCoverage?.blocked),
  );
  const rawMaterializedEvidenceGapCount = missingEvidenceAnchorCount(candidateProjection);
  const materializedEvidenceGapCount = rawMaterializedEvidenceGapCount === undefined
    ? undefined
    : inputCount > 0
      ? Math.min(rawMaterializedEvidenceGapCount, inputCount)
      : rawMaterializedEvidenceGapCount;
  const evidenceGapCount = materializedEvidenceGapCount ?? sourceVerificationCount;
  const evidenceWorkCount = Math.max(evidenceGapCount, sourceVerificationCount);
  const failureCount = Math.max(
    recoveryNumber(recoveryClosure?.failedCount),
    invalidCount,
    recoveryCoverage?.complete === false ? coverageMissingCount : 0,
  );
  const salvageSignals = [
    recoveryNumber(recoveryClosure?.successCount),
    recoveryNumber(candidateProjection?.counts?.output),
    sourceCollectionRunApprovedCount,
  ].filter((value) => value > 0);
  const rawSalvageCount = salvageSignals.length
    ? Math.max(...salvageSignals)
    : sourceCollectionDisplayedCandidateCount;
  const salvageCount = hasCurrentCoverage && inputCount > 0
    ? Math.min(rawSalvageCount, inputCount)
    : rawSalvageCount;
  const salvageText = sourceCollectionPrimaryDataLoading
    ? sourceCollectionLoadingText
    : String(salvageCount);
  const hasHardFailure = Boolean(
    failureCount > 0
    || recoveryCoverage?.complete === false
    || recoveryClosure?.userStatus === "failed"
    || candidateProjection?.status === "failed"
    || candidateProjection?.status === "agent_blocked"
    || candidateProjection?.status === "agent_interrupted"
    || (!currentCoverageComplete && sourceCollectionCandidateStepState === "failed"),
  );
  const evidenceGapOnly = Boolean(
    !hasHardFailure
    && evidenceGapCount > 0
    && materializedEvidenceGapCount !== 0,
  );
  const sourceVerificationOnly = Boolean(
    !hasHardFailure
    && materializedEvidenceGapCount === 0
    && sourceVerificationCount > 0,
  );
  const excluded = Boolean(sourceCollectionExtractionExcludedRecoveryState.blockedByExcludedSources);
  const recoveryNeedsWork = Boolean(hasHardFailure || evidenceWorkCount > 0 || excluded);
  if (!recoveryNeedsWork) {
    return null;
  }

  const issueCount = hasHardFailure
    ? failureCount
    : sourceVerificationOnly
      ? sourceVerificationCount
      : evidenceGapCount;
  const failedText = issueCount > 0
    ? inputCount > 0
      ? `${issueCount}/${inputCount}`
      : String(issueCount)
    : (lang === "zh" ? "需要排查" : "review");
  const recoveryCoverageText = recoveryNumber(recoveryCoverage?.total) > 0
    ? `${recoveryNumber(recoveryCoverage?.processed)}/${recoveryNumber(recoveryCoverage?.total)}`
    : sourceCollectionStageRecoveryStatusLabel("extraction", lang);

  const primaryActionText = excluded
    ? String(sourceCollectionExtractionExcludedRecoveryState.primaryActionText || (lang === "zh" ? "进入 Agent 私聊" : "Open Agent chat"))
    : sourceVerificationOnly
      ? (lang === "zh" ? "要求 Agent 补充材料" : "Request Agent material supplement")
      : evidenceGapOnly
        ? (lang === "zh" ? "要求 Agent 补充证据" : "Request Agent evidence supplement")
        : (lang === "zh" ? "继续 Agent 提炼" : "Continue Agent extraction");

  const primaryActionTitle = excluded
    ? sourceCollectionExtractionExcludedRecoveryState.primaryActionTitle
    : sourceCollectionActionDisabledTitle(primaryActionText);

  const nextStepGuide = lang === "zh"
    ? "现在只点主按钮推进；质量审查是补完材料后的下一步，单独点审查不会消除「待补」。"
    : "Use the primary button only for now; quality review is the next step after materials are repaired—review alone will not clear needs-revision.";
  const summary = excluded
    ? String(sourceCollectionExtractionExcludedRecoveryState.summary || "")
    : sourceVerificationOnly
      ? (lang === "zh"
        ? `候选资料已提炼 ${salvageCount}/${inputCount}；其中 ${sourceVerificationCount} 条需核验版本/可靠性（不等于缺证据锚点）。${nextStepGuide}`
        : `${salvageCount}/${inputCount} extracted; ${sourceVerificationCount} need version/reliability checks (not the same as missing evidence anchors). ${nextStepGuide}`)
      : evidenceGapOnly
        ? (lang === "zh"
          ? `还有证据锚点缺口。请先让 Agent 补页码/段落/DOI 锚点或可核验摘要。${nextStepGuide}`
          : `Evidence-anchor gaps remain. Have the Agent add page/paragraph/DOI anchors or a verifiable abstract. ${nextStepGuide}`)
      : (
        (sourceCollectionStageUserSummary(candidateProjection, lang)
          || (lang === "zh"
            ? "本轮资料提炼没有完全闭环；先保留可用候选，再补齐失败记录。"
            : "This extraction run did not close cleanly; keep usable candidates and recover failed records."))
        + ` ${nextStepGuide}`
      );

  return {
    tone: excluded
      ? (sourceCollectionExtractionExcludedRecoveryState.tone || "danger")
      : evidenceGapOnly || sourceVerificationOnly
        ? "progressable"
        : "danger",
    titleLabel: excluded
      ? String(sourceCollectionExtractionExcludedRecoveryState.panelTitle || (lang === "zh" ? "提炼失败恢复" : "Extraction recovery"))
      : sourceVerificationOnly
        ? (lang === "zh" ? "来源核验" : "Source verification")
        : evidenceGapOnly
          ? (lang === "zh" ? "证据补全" : "Evidence completion")
          : (lang === "zh" ? "提炼失败恢复" : "Extraction recovery"),
    statusLabel: excluded
      ? String(sourceCollectionExtractionExcludedRecoveryState.statusLabel || sourceCollectionStageRecoveryStatusLabel("extraction", lang))
      : sourceVerificationOnly
        ? (lang === "zh" ? "提炼完成，待核验来源" : "Extraction complete; source verification required")
        : evidenceGapOnly
          ? (lang === "zh" ? "提炼完成，待补证据" : "Extraction complete; evidence needed")
          : sourceCollectionStageRecoveryStatusLabel("extraction", lang),
    summary,
    failedLabel: excluded
      ? String(sourceCollectionExtractionExcludedRecoveryState.failedLabel || (lang === "zh" ? "提炼失败" : "failed extraction"))
      : sourceVerificationOnly
        ? (lang === "zh" ? "待核验来源" : "sources to verify")
        : evidenceGapOnly
          ? (lang === "zh" ? "待补证据" : "evidence gaps")
          : (lang === "zh" ? "提炼失败" : "failed extraction"),
    failedText,
    salvageLabel: lang === "zh" ? "可保留" : "salvageable",
    salvageText,
    recoverLabel: excluded
      ? String(sourceCollectionExtractionExcludedRecoveryState.recoverLabel || (lang === "zh" ? "待补提炼" : "to recover"))
      : sourceVerificationOnly
        ? (lang === "zh" ? "提炼覆盖" : "extraction coverage")
        : evidenceGapOnly
          ? (lang === "zh" ? "提炼覆盖" : "extraction coverage")
          : (lang === "zh" ? "待补提炼" : "to recover"),
    recoverText: sourceCollectionPrimaryDataLoading
      ? sourceCollectionLoadingText
      : excluded
        ? String(sourceCollectionExtractionExcludedRecoveryState.recoverText || recoveryCoverageText)
        : recoveryCoverageText,
    pendingReviewText: sourceCollectionRunPendingScreeningCountText,
    primaryActionText,
    primaryActionTitle: excluded
      ? primaryActionTitle
      : (sourceCollectionStageActionReadinessDisabled ? primaryActionTitle : undefined),
    primaryActionKind: excluded ? "chat" : "continue_task",
    showImportAction: !excluded,
    importActionText: lang === "zh" ? "补导入候选" : "Import candidates",
    /** Secondary review action: re-score only; does not rewrite source material. */
    qualityReviewActionText: lang === "zh" ? "重新质量审查" : "Re-run quality review",
    qualityReviewActionTitle: lang === "zh"
      ? "仅根据现有材料重新打分。不会自动补全文/DOI/证据锚点；待补资料需先补充再审查。"
      : "Re-scores with current materials only. Does not auto-fill full text/DOI/anchors; repair needs-revision sources first.",
    ariaLabel: excluded
      ? String(sourceCollectionExtractionExcludedRecoveryState.panelAriaLabel || (lang === "zh" ? "资料提炼失败恢复工作台" : "Source extraction recovery panel"))
      : sourceVerificationOnly
        ? (lang === "zh" ? "资料提炼来源核验工作台" : "Source extraction verification panel")
        : evidenceGapOnly
          ? (lang === "zh" ? "资料提炼证据补全工作台" : "Source extraction evidence completion panel")
          : (lang === "zh" ? "资料提炼失败恢复工作台" : "Source extraction recovery panel"),
    preferPrimaryOverStageAction: true,
  };
}
