/**
 * Source-collection extraction recovery workspace.
 * Wave 8L: extracted from TeamsRoute.tsx for domain componentization.
 * Recovery metrics/actions can also integrate into the extraction stage card.
 */
import { CheckCircle2, MessageSquare, Play, RefreshCw } from "lucide-react";

import { VButton } from "../../../../components/vui";
import {
  buildExtractionRecoveryViewModel,
} from "../extractionRecoveryViewModel";
import type { SourceCollectionActionReadiness, SourceCollectionStageCardProjection, SourceCollectionStageModuleId } from "../stageProjection";
import { TeamSourceCollectionExtractionRecoveryPanel } from "./TeamSourceCollectionExtractionRecoveryPanel";

type Lang = "zh" | "en";

type ExtractionRecoveryViewModelInput = Parameters<typeof buildExtractionRecoveryViewModel>[0];

export type TeamSourceCollectionExtractionRecoveryWorkspacePanelProps = {
  candidateProjection: SourceCollectionStageCardProjection | null | undefined;
  lang: Lang;
  sourceCollectionRawRecordCount: number;
  sourceCollectionRunApprovedCount: number;
  sourceCollectionDisplayedCandidateCount: number;
  sourceCollectionPrimaryDataLoading: boolean;
  sourceCollectionLoadingText: string;
  sourceCollectionCandidateStepState: ExtractionRecoveryViewModelInput["sourceCollectionCandidateStepState"];
  sourceCollectionExtractionExcludedRecoveryState: ExtractionRecoveryViewModelInput["sourceCollectionExtractionExcludedRecoveryState"];
  sourceCollectionActionDisabledTitle: (readiness: SourceCollectionActionReadiness, label: string) => string | undefined;
  sourceCollectionStageActionReadinessFor: (stageId: SourceCollectionStageModuleId) => SourceCollectionActionReadiness;
  openSourceCollectionStageAgentChat: (stageId: SourceCollectionStageModuleId) => void;
  startSourceCollectionStageSessionTask: (stageId: SourceCollectionStageModuleId) => void;
  runSourceCollectionCandidateExtractionAction: () => void;
  sourceCollectionCandidateExtractionActionReadiness: SourceCollectionActionReadiness;
  runSourceCollectionScreeningAction: () => void;
  sourceCollectionScreeningActionReadiness: SourceCollectionActionReadiness;
  sourceCollectionScreeningButtonText: string;
  sourceCollectionScreeningButtonTitle?: string;
  sourceCollectionRunPendingScreeningCountText: string;
  /**
   * `banner`: full recovery surface with its own action row (legacy / tests).
   * `stageCard`: metrics+summary only; actions live on the extraction stage header.
   */
  presentation?: "banner" | "stageCard";
  /** When false, omit 私聊 from banner actions (stage header already has it). */
  includeChatAction?: boolean;
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
    sourceCollectionScreeningButtonTitle,
    sourceCollectionRunPendingScreeningCountText,
    presentation = "banner",
    includeChatAction = true,
  } = props;

  const extractionReadiness = sourceCollectionStageActionReadinessFor("extraction");
  const viewModel = buildExtractionRecoveryViewModel({
    candidateProjection,
    lang,
    sourceCollectionRawRecordCount,
    sourceCollectionRunApprovedCount,
    sourceCollectionDisplayedCandidateCount,
    sourceCollectionPrimaryDataLoading,
    sourceCollectionLoadingText,
    sourceCollectionCandidateStepState,
    sourceCollectionExtractionExcludedRecoveryState,
    sourceCollectionStageActionReadinessDisabled: Boolean(extractionReadiness?.disabled),
    sourceCollectionActionDisabledTitle: (label) => sourceCollectionActionDisabledTitle(extractionReadiness, label),
    sourceCollectionRunPendingScreeningCountText,
  });

  if (!viewModel) {
    return null;
  }

  const stageCard = presentation === "stageCard";
  const actions = stageCard ? null : (
    <>
      <VButton
        type="button"
        density="compact"
        variant="primary"
        icon={viewModel.primaryActionKind === "chat" ? <MessageSquare size={13} /> : <Play size={13} />}
        onPress={viewModel.primaryActionKind === "chat"
          ? () => void openSourceCollectionStageAgentChat("extraction")
          : () => void startSourceCollectionStageSessionTask("extraction")}
        isDisabled={viewModel.primaryActionKind !== "chat" && Boolean(extractionReadiness?.disabled)}
        title={viewModel.primaryActionTitle}
      >
        {viewModel.primaryActionText}
      </VButton>
      {viewModel.showImportAction ? (
        <VButton
          type="button"
          density="compact"
          variant="secondary"
          icon={<RefreshCw size={13} />}
          onPress={runSourceCollectionCandidateExtractionAction}
          isDisabled={sourceCollectionCandidateExtractionActionReadiness.disabled}
          title={sourceCollectionActionDisabledTitle(sourceCollectionCandidateExtractionActionReadiness, viewModel.importActionText)}
        >
          {viewModel.importActionText}
        </VButton>
      ) : null}
      <VButton
        type="button"
        density="compact"
        variant="secondary"
        icon={<CheckCircle2 size={13} />}
        onPress={runSourceCollectionScreeningAction}
        isDisabled={sourceCollectionScreeningActionReadiness.disabled}
        title={sourceCollectionActionDisabledTitle(
          sourceCollectionScreeningActionReadiness,
          sourceCollectionScreeningButtonText || viewModel.qualityReviewActionText,
        )
          || sourceCollectionScreeningButtonTitle
          || viewModel.qualityReviewActionTitle}
      >
        {sourceCollectionScreeningButtonText || viewModel.qualityReviewActionText}
      </VButton>
      {includeChatAction ? (
        <VButton
          type="button"
          density="compact"
          variant="secondary"
          icon={<MessageSquare size={13} />}
          onPress={() => void openSourceCollectionStageAgentChat("extraction")}
        >
          {lang === "zh" ? "进入 Agent 私聊" : "Open Agent chat"}
        </VButton>
      ) : null}
    </>
  );

  return (
    <TeamSourceCollectionExtractionRecoveryPanel
      lang={lang}
      tone={viewModel.tone}
      ariaLabel={viewModel.ariaLabel}
      titleLabel={viewModel.titleLabel}
      statusLabel={viewModel.statusLabel}
      summary={viewModel.summary}
      failedLabel={viewModel.failedLabel}
      failedText={viewModel.failedText}
      salvageText={viewModel.salvageText}
      recoverLabel={viewModel.recoverLabel}
      recoverText={viewModel.recoverText}
      pendingReviewText={viewModel.pendingReviewText}
      actions={actions}
    />
  );
}
