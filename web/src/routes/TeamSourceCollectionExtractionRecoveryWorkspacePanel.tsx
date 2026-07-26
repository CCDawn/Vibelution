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
    const sourceCollectionExtractionRecoveryMissingCount = Math.max(
      sourceCollectionExtractionRecoveryCoverageMissingCount,
      recoveryNumber(candidateProjection?.counts?.pending),
    );
    const sourceCollectionExtractionRecoveryFailureCount = Math.max(
      recoveryNumber(recoveryClosure?.failedCount),
      recoveryNumber(recoveryClosure?.blockedCount),
      recoveryNumber(recoveryCoverage?.blocked),
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
    const recoveryNeedsWork = Boolean(
      sourceCollectionExtractionRecoveryFailureCount > 0
      || sourceCollectionExtractionRecoveryInvalidCount > 0
      || recoveryCoverage?.complete === false
      || recoveryClosure?.userStatus === "failed"
      || candidateProjection?.status === "failed"
      || candidateProjection?.status === "agent_blocked"
      || candidateProjection?.status === "agent_interrupted"
      || sourceCollectionCandidateStepState === "failed"
    );
    if (!recoveryNeedsWork) {
      return null;
    }
    const recoveryFailureText = sourceCollectionExtractionRecoveryFailureCount > 0
      ? sourceCollectionExtractionRecoveryInputCount > 0
        ? `${sourceCollectionExtractionRecoveryFailureCount}/${sourceCollectionExtractionRecoveryInputCount}`
        : String(sourceCollectionExtractionRecoveryFailureCount)
      : (lang === "zh" ? "需要排查" : "review");
    const recoveryMissingText = sourceCollectionExtractionRecoveryMissingCount > 0
      ? String(sourceCollectionExtractionRecoveryMissingCount)
      : sourceCollectionExtractionRecoveryInvalidCount > 0
        ? String(sourceCollectionExtractionRecoveryInvalidCount)
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
      : sourceCollectionStageUserSummary(candidateProjection, lang)
      || (lang === "zh"
        ? "本轮资料提炼没有完全闭环；先保留可用候选，再补齐失败记录。"
        : "This extraction run did not close cleanly; keep usable candidates and recover failed records.");
    return (
      <TeamSourceCollectionExtractionRecoveryPanel
        lang={lang}
        tone={sourceCollectionExtractionExcludedRecoveryState.tone}
        ariaLabel={sourceCollectionExtractionExcludedRecoveryState.blockedByExcludedSources
          ? sourceCollectionExtractionExcludedRecoveryState.panelAriaLabel
          : undefined}
        titleLabel={sourceCollectionExtractionExcludedRecoveryState.blockedByExcludedSources
          ? sourceCollectionExtractionExcludedRecoveryState.panelTitle
          : undefined}
        statusLabel={sourceCollectionExtractionExcludedRecoveryState.blockedByExcludedSources
          ? sourceCollectionExtractionExcludedRecoveryState.statusLabel
          : sourceCollectionStageRecoveryStatusLabel("extraction", lang)}
        summary={recoverySummary}
        failedLabel={sourceCollectionExtractionExcludedRecoveryState.blockedByExcludedSources
          ? sourceCollectionExtractionExcludedRecoveryState.failedLabel
          : undefined}
        failedText={recoveryFailureText}
        salvageText={sourceCollectionExtractionRecoverySalvageText}
        recoverLabel={sourceCollectionExtractionExcludedRecoveryState.blockedByExcludedSources
          ? sourceCollectionExtractionExcludedRecoveryState.recoverLabel
          : undefined}
        recoverText={sourceCollectionPrimaryDataLoading
          ? sourceCollectionLoadingText
          : sourceCollectionExtractionExcludedRecoveryState.blockedByExcludedSources
            ? sourceCollectionExtractionExcludedRecoveryState.recoverText
            : recoveryMissingText}
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
