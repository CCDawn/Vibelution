/**
 * Source-collection extraction recovery workspace.
 * Wave 8L: extracted from TeamsRoute.tsx for domain componentization.
 */
import { CheckCircle2, MessageSquare, Play, RefreshCw } from "lucide-react";

import { VButton } from "../components/vui";
import {
  sourceCollectionStageRecoveryStatusLabel,
  sourceCollectionStageUserSummary,
  sourceCollectionNonNegativeCount,
  type SourceCollectionStageCardProjection,
  type SourceCollectionStageModuleId,
} from "./teams/source-collection/stageProjection";
import { TeamSourceCollectionExtractionRecoveryPanel } from "./TeamSourceCollectionExtractionRecoveryPanel";

type Lang = "zh" | "en";

function extractionMissingEvidenceAnchorCount(candidateProjection: SourceCollectionStageCardProjection | null | undefined) {
  const materialized = candidateProjection?.latestTask?.materializedContentExtraction;
  const value = materialized?.missingEvidenceAnchorCount;
  return typeof value === "number" && Number.isFinite(value)
    ? Math.max(0, value)
    : undefined;
}

export type TeamSourceCollectionExtractionRecoveryWorkspacePanelProps = {
  candidateProjection: SourceCollectionStageCardProjection | null | undefined;
  lang: Lang;
  sourceCollectionRawRecordCount: number;
  sourceCollectionRunApprovedCount: number;
  sourceCollectionDisplayedCandidateCount: number;
  sourceCollectionPrimaryDataLoading: boolean;
  sourceCollectionLoadingText: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionCandidateStepState: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionExtractionExcludedRecoveryState: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionActionDisabledTitle: (readiness: any, label: string) => string | undefined;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionStageActionReadinessFor: (stageId: SourceCollectionStageModuleId) => any;
  openSourceCollectionStageAgentChat: (stageId: SourceCollectionStageModuleId) => void;
  startSourceCollectionStageSessionTask: (stageId: SourceCollectionStageModuleId) => void;
  runSourceCollectionCandidateExtractionAction: () => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionCandidateExtractionActionReadiness: any;
  runSourceCollectionScreeningAction: () => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionScreeningActionReadiness: any;
  sourceCollectionScreeningButtonText: string;
  sourceCollectionRunPendingScreeningCountText: string;
};

export function TeamSourceCollectionExtractionRecoveryWorkspacePanel(props: TeamSourceCollectionExtractionRecoveryWorkspacePanelProps) {
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
    sourceCollectionActionDisabledTitle,
    sourceCollectionStageActionReadinessFor,
    openSourceCollectionStageAgentChat,
    startSourceCollectionStageSessionTask,
    runSourceCollectionCandidateExtractionAction,
    sourceCollectionCandidateExtractionActionReadiness,
    runSourceCollectionScreeningAction,
    sourceCollectionScreeningActionReadiness,
    sourceCollectionScreeningButtonText,
    sourceCollectionRunPendingScreeningCountText,
  } = props;


    const recoveryCoverage = candidateProjection?.currentCoverageSummary?.complete === false
      ? candidateProjection.currentCoverageSummary
      : candidateProjection?.latestTask?.coverageSummary;
    const recoveryClosure = candidateProjection?.latestTask?.closureSummary;
    const recoveryNumber = sourceCollectionNonNegativeCount;
    const sourceCollectionExtractionRecoveryInputCount = Math.max(
      recoveryNumber(recoveryCoverage?.total),
      recoveryNumber(candidateProjection?.counts?.input),
      sourceCollectionRawRecordCount,
    );
    const sourceCollectionExtractionRecoveryInvalidCount = Math.max(
      recoveryNumber(recoveryCoverage?.invalid),
      recoveryClosure?.invalidIds?.length ?? 0,
      candidateProjection?.latestTask?.invalidRecordIds?.length ?? 0,
      candidateProjection?.latestTask?.invalidCandidateIds?.length ?? 0,
    );
    const sourceCollectionExtractionRecoveryCoverageMissingCount = recoveryNumber(recoveryCoverage?.missing);
    const sourceCollectionExtractionRecoverySourceVerificationCount = Math.max(
      recoveryNumber(recoveryClosure?.blockedCount),
      recoveryNumber(recoveryCoverage?.blocked),
    );
    const materializedEvidenceGapCount = extractionMissingEvidenceAnchorCount(candidateProjection);
    const sourceCollectionExtractionRecoveryEvidenceGapCount = materializedEvidenceGapCount
      ?? sourceCollectionExtractionRecoverySourceVerificationCount;
    const sourceCollectionExtractionRecoveryEvidenceWorkCount = Math.max(
      sourceCollectionExtractionRecoveryEvidenceGapCount,
      sourceCollectionExtractionRecoverySourceVerificationCount,
    );
    const sourceCollectionExtractionRecoveryFailureCount = Math.max(
      recoveryNumber(recoveryClosure?.failedCount),
      sourceCollectionExtractionRecoveryInvalidCount,
      recoveryCoverage?.complete === false ? sourceCollectionExtractionRecoveryCoverageMissingCount : 0,
    );
    const sourceCollectionExtractionRecoverySalvageSignals = [
      recoveryNumber(recoveryClosure?.successCount),
      recoveryNumber(candidateProjection?.counts?.output),
      sourceCollectionRunApprovedCount,
    ].filter((value: any) => value > 0);
    const sourceCollectionExtractionRecoverySalvageCount = sourceCollectionExtractionRecoverySalvageSignals.length
      ? Math.max(...sourceCollectionExtractionRecoverySalvageSignals)
      : sourceCollectionDisplayedCandidateCount;
    const sourceCollectionExtractionRecoverySalvageText = sourceCollectionPrimaryDataLoading
      ? sourceCollectionLoadingText
      : String(sourceCollectionExtractionRecoverySalvageCount);
    const sourceCollectionExtractionRecoveryHasHardFailure = Boolean(
      sourceCollectionExtractionRecoveryFailureCount > 0
      || recoveryCoverage?.complete === false
      || recoveryClosure?.userStatus === "failed"
      || candidateProjection?.status === "failed"
      || candidateProjection?.status === "agent_blocked"
      || candidateProjection?.status === "agent_interrupted"
      || sourceCollectionCandidateStepState === "failed"
    );
    const sourceCollectionExtractionRecoveryEvidenceGapOnly = Boolean(
      !sourceCollectionExtractionRecoveryHasHardFailure
      && sourceCollectionExtractionRecoveryEvidenceGapCount > 0
      && materializedEvidenceGapCount !== 0
    );
    const sourceCollectionExtractionRecoverySourceVerificationOnly = Boolean(
      !sourceCollectionExtractionRecoveryHasHardFailure
      && materializedEvidenceGapCount === 0
      && sourceCollectionExtractionRecoverySourceVerificationCount > 0
    );
    const recoveryNeedsWork = Boolean(
      sourceCollectionExtractionRecoveryHasHardFailure
      || sourceCollectionExtractionRecoveryEvidenceWorkCount > 0
    );
    if (!recoveryNeedsWork) {
      return null;
    }
    const sourceCollectionExtractionRecoveryIssueCount = sourceCollectionExtractionRecoveryHasHardFailure
      ? sourceCollectionExtractionRecoveryFailureCount
      : sourceCollectionExtractionRecoverySourceVerificationOnly
        ? sourceCollectionExtractionRecoverySourceVerificationCount
        : sourceCollectionExtractionRecoveryEvidenceGapCount;
    const recoveryFailureText = sourceCollectionExtractionRecoveryIssueCount > 0
      ? sourceCollectionExtractionRecoveryInputCount > 0
        ? `${sourceCollectionExtractionRecoveryIssueCount}/${sourceCollectionExtractionRecoveryInputCount}`
        : String(sourceCollectionExtractionRecoveryIssueCount)
      : (lang === "zh" ? "需要排查" : "review");
    const recoveryCoverageText = recoveryNumber(recoveryCoverage?.total) > 0
      ? `${recoveryNumber(recoveryCoverage?.processed)}/${recoveryNumber(recoveryCoverage?.total)}`
      : sourceCollectionStageRecoveryStatusLabel("extraction", lang);
    const sourceCollectionRecoveryAgentActionText = sourceCollectionExtractionExcludedRecoveryState.blockedByExcludedSources
      ? sourceCollectionExtractionExcludedRecoveryState.primaryActionText
      : (lang === "zh" ? "继续 Agent 提炼" : "Continue Agent extraction");
    const sourceCollectionRecoveryAgentActionTitle = sourceCollectionExtractionExcludedRecoveryState.blockedByExcludedSources
      ? sourceCollectionExtractionExcludedRecoveryState.primaryActionTitle
      : sourceCollectionActionDisabledTitle(
        sourceCollectionStageActionReadinessFor("extraction"),
        sourceCollectionRecoveryAgentActionText,
      );
    const sourceCollectionImportCandidateActionText = lang === "zh" ? "补导入候选" : "Import candidates";
    const recoverySummary = sourceCollectionExtractionExcludedRecoveryState.blockedByExcludedSources
      ? sourceCollectionExtractionExcludedRecoveryState.summary
      : sourceCollectionExtractionRecoverySourceVerificationOnly
        ? (lang === "zh"
          ? `候选资料已提炼 ${sourceCollectionExtractionRecoverySalvageCount}/${sourceCollectionExtractionRecoveryInputCount}；其中 ${sourceCollectionExtractionRecoverySourceVerificationCount} 条来源需要核验版本或可靠性，不代表缺少证据锚点。`
          : `${sourceCollectionExtractionRecoverySalvageCount}/${sourceCollectionExtractionRecoveryInputCount} candidate sources were extracted; ${sourceCollectionExtractionRecoverySourceVerificationCount} still need version or reliability verification, not additional evidence anchors.`)
      : sourceCollectionStageUserSummary(candidateProjection, lang)
      || (lang === "zh"
        ? "本轮资料提炼没有完全闭环；先保留可用候选，再补齐失败记录。"
        : "This extraction run did not close cleanly; keep usable candidates and recover failed records.");
    return (
      <TeamSourceCollectionExtractionRecoveryPanel
        lang={lang}
        tone={sourceCollectionExtractionExcludedRecoveryState.blockedByExcludedSources
          ? sourceCollectionExtractionExcludedRecoveryState.tone
          : sourceCollectionExtractionRecoveryEvidenceGapOnly
            ? "progressable"
            : "danger"}
        ariaLabel={sourceCollectionExtractionExcludedRecoveryState.blockedByExcludedSources
          ? sourceCollectionExtractionExcludedRecoveryState.panelAriaLabel
          : sourceCollectionExtractionRecoverySourceVerificationOnly
            ? (lang === "zh" ? "资料提炼来源核验工作台" : "Source extraction verification panel")
          : sourceCollectionExtractionRecoveryEvidenceGapOnly
            ? (lang === "zh" ? "资料提炼证据补全工作台" : "Source extraction evidence completion panel")
            : undefined}
        titleLabel={sourceCollectionExtractionExcludedRecoveryState.blockedByExcludedSources
          ? sourceCollectionExtractionExcludedRecoveryState.panelTitle
          : sourceCollectionExtractionRecoverySourceVerificationOnly
            ? (lang === "zh" ? "来源核验" : "Source verification")
          : sourceCollectionExtractionRecoveryEvidenceGapOnly
            ? (lang === "zh" ? "证据补全" : "Evidence completion")
            : undefined}
        statusLabel={sourceCollectionExtractionExcludedRecoveryState.blockedByExcludedSources
          ? sourceCollectionExtractionExcludedRecoveryState.statusLabel
          : sourceCollectionExtractionRecoverySourceVerificationOnly
            ? (lang === "zh" ? "提炼完成，待核验来源" : "Extraction complete; sources need verification")
          : sourceCollectionExtractionRecoveryEvidenceGapOnly
            ? (lang === "zh" ? "提炼完成，待补证据" : "Extraction complete; evidence needed")
            : sourceCollectionStageRecoveryStatusLabel("extraction", lang)}
        summary={recoverySummary}
        failedLabel={sourceCollectionExtractionExcludedRecoveryState.blockedByExcludedSources
          ? sourceCollectionExtractionExcludedRecoveryState.failedLabel
          : sourceCollectionExtractionRecoverySourceVerificationOnly
            ? (lang === "zh" ? "待核验来源" : "sources to verify")
          : sourceCollectionExtractionRecoveryEvidenceGapOnly
            ? (lang === "zh" ? "待补证据" : "evidence gaps")
            : undefined}
        failedText={recoveryFailureText}
        salvageText={sourceCollectionExtractionRecoverySalvageText}
        recoverLabel={sourceCollectionExtractionExcludedRecoveryState.blockedByExcludedSources
          ? sourceCollectionExtractionExcludedRecoveryState.recoverLabel
          : sourceCollectionExtractionRecoveryEvidenceGapOnly
            ? (lang === "zh" ? "提炼覆盖" : "extraction coverage")
            : undefined}
        recoverText={sourceCollectionPrimaryDataLoading
          ? sourceCollectionLoadingText
          : sourceCollectionExtractionExcludedRecoveryState.blockedByExcludedSources
            ? sourceCollectionExtractionExcludedRecoveryState.recoverText
            : recoveryCoverageText}
        pendingReviewText={sourceCollectionRunPendingScreeningCountText}
        actions={(
          <>
          <VButton
            type="button"
            density="compact"
            variant="primary"
            icon={sourceCollectionExtractionExcludedRecoveryState.blockedByExcludedSources ? <MessageSquare size={13} /> : <Play size={13} />}
            onPress={sourceCollectionExtractionExcludedRecoveryState.blockedByExcludedSources
              ? () => void openSourceCollectionStageAgentChat("extraction")
              : () => void startSourceCollectionStageSessionTask("extraction")}
            isDisabled={!sourceCollectionExtractionExcludedRecoveryState.blockedByExcludedSources && sourceCollectionStageActionReadinessFor("extraction").disabled}
            title={sourceCollectionRecoveryAgentActionTitle}
          >
            {sourceCollectionRecoveryAgentActionText}
          </VButton>
          {!sourceCollectionExtractionExcludedRecoveryState.blockedByExcludedSources ? (
            <VButton
              type="button"
              density="compact"
              variant="secondary"
              icon={<RefreshCw size={13} />}
              onPress={runSourceCollectionCandidateExtractionAction}
              isDisabled={sourceCollectionCandidateExtractionActionReadiness.disabled}
              title={sourceCollectionActionDisabledTitle(sourceCollectionCandidateExtractionActionReadiness, sourceCollectionImportCandidateActionText)}
            >
              {sourceCollectionImportCandidateActionText}
            </VButton>
          ) : null}
          <VButton
            type="button"
            density="compact"
            variant="secondary"
            icon={<CheckCircle2 size={13} />}
            onPress={runSourceCollectionScreeningAction}
            isDisabled={sourceCollectionScreeningActionReadiness.disabled}
            title={sourceCollectionActionDisabledTitle(sourceCollectionScreeningActionReadiness, sourceCollectionScreeningButtonText)}
          >
            {sourceCollectionScreeningButtonText}
          </VButton>
          <VButton
            type="button"
            density="compact"
            variant="secondary"
            icon={<MessageSquare size={13} />}
            onPress={() => void openSourceCollectionStageAgentChat("extraction")}
          >
            {lang === "zh" ? "进入 Agent 私聊" : "Open Agent chat"}
          </VButton>
          </>
        )}
      />
    );

}
