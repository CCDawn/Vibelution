/**
 * Source-collection active-stage workspace body.
 * Wave 8M: extracted from TeamsRoute.tsx for domain componentization.
 * Extraction stage merges recovery/verification into the right stage card.
 */
import type { ReactNode } from "react";
import { Link2, MessageSquare, RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";

import { VNativeButton, VTooltip } from "../components/vui";
import { researchStageAgentManagementRoute } from "./teams/researchStageAgentPresentation";
import { buildExtractionRecoveryViewModel } from "./teams/source-collection/extractionRecoveryViewModel";
import { buildExtractionStageFlowGuide } from "./teams/source-collection/extractionStageFlowGuide";
import type { SourceCollectionStageCardProjection, SourceCollectionStageModuleId } from "./teams/source-collection/stageProjection";
import { TeamSourceCollectionActiveStagePanel } from "./TeamSourceCollectionActiveStagePanel";
import { TeamSourceCollectionExtractionRecoveryWorkspacePanel } from "./TeamSourceCollectionExtractionRecoveryWorkspacePanel";
import shellStyles from "./TeamsRoute.styles";
import workflowStyles from "./TeamsRoute.workflow.styles";

const styles = { ...shellStyles, ...workflowStyles } as Record<string, string>;

type Lang = "zh" | "en";

export type TeamSourceCollectionActiveStageWorkspacePanelProps = {
  lang: Lang;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionStageModules: any[];
  selectedSourceCollectionStageId: SourceCollectionStageModuleId | string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionStageAgentChatState: (stageId: any) => any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  repairChallengeCupTeamAgentsMutation: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionActionDisabledTitle: (readiness: any, label: string) => string | undefined;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionStageActionReadinessFor: (stageId: any) => any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sourceCollectionStagePrimaryAgentBinding: (stageId: any) => any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  stageChatLabels: Record<string, { zh: string; en: string }>;
  openSourceCollectionStageAgentChat: (stageId: any) => void;
  startSourceCollectionStageSessionTask?: (stageId: SourceCollectionStageModuleId) => void;
  sourceCollectionFindingStageCompact: boolean;
  selectedTeamStartSourceCollectionStageTaskError: Error | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionConversation: () => ReactNode;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionScreeningPanel: () => ReactNode;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionGraphPanel: () => ReactNode;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionMemoryPanel: () => ReactNode;
  /** Extraction recovery inputs — when set, merge into extraction stage card. */
  extractionRecovery?: {
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
    /** Flow progression inputs for a single recommended CTA. */
    needsAgentMaterial?: boolean;
    pendingScreeningCount?: number;
    pendingImportCount?: number;
    canProceedAfterExclusions?: boolean;
    qualityReviewPending?: boolean;
    advanceToRelations?: () => void;
  };
};

export function TeamSourceCollectionActiveStageWorkspacePanel(props: TeamSourceCollectionActiveStageWorkspacePanelProps) {
  const {
    lang,
    sourceCollectionStageModules,
    selectedSourceCollectionStageId,
    sourceCollectionStageAgentChatState,
    repairChallengeCupTeamAgentsMutation,
    sourceCollectionActionDisabledTitle,
    sourceCollectionStageActionReadinessFor,
    sourceCollectionStagePrimaryAgentBinding,
    stageChatLabels,
    openSourceCollectionStageAgentChat,
    startSourceCollectionStageSessionTask,
    sourceCollectionFindingStageCompact,
    selectedTeamStartSourceCollectionStageTaskError,
    renderSourceCollectionConversation,
    renderSourceCollectionScreeningPanel,
    renderSourceCollectionGraphPanel,
    renderSourceCollectionMemoryPanel,
    extractionRecovery,
  } = props;

  const activeModule =
    sourceCollectionStageModules.find((module: any) => module.id === selectedSourceCollectionStageId)
    ?? sourceCollectionStageModules[0];
  const primaryStageAgentChatState = sourceCollectionStageAgentChatState(activeModule.id);
  const primaryStageAgentChatRoute = primaryStageAgentChatState.route;
  const primaryStageAgentChatLoading = primaryStageAgentChatState.status === "loading";
  const primaryStageAgentChatError = primaryStageAgentChatState.status === "error";
  const primaryStageAgentSessionCreateReady = primaryStageAgentChatState.status === "ready";
  const primaryStageAgentRepairPending =
    primaryStageAgentChatState.status === "repair" && repairChallengeCupTeamAgentsMutation.isPending;
  const primaryStageAgentFallbackTitle = primaryStageAgentChatLoading
    ? (lang === "zh" ? "正在加载本轮 Agent 会话，请稍候" : "Loading the Agent session for this run")
    : primaryStageAgentChatError
      ? (lang === "zh" ? "Agent 配置加载失败，请刷新后重试" : "Agent configuration failed to load")
      : primaryStageAgentSessionCreateReady
        ? (lang === "zh" ? "为当前研究项目创建并打开此 Agent 的平级实验会话" : "Create and open this Agent's peer experiment session for the current research project")
        : (lang === "zh" ? "当前步骤缺少可用私聊，请先修复团队 Agent 绑定" : "No usable direct chat for this step");
  const primaryStageAgentFallbackLabel = primaryStageAgentChatLoading
    ? (lang === "zh" ? "加载本轮会话..." : "Loading session...")
    : primaryStageAgentChatError
      ? (lang === "zh" ? "Agent 加载失败" : "Agent load failed")
      : primaryStageAgentSessionCreateReady
        ? (lang === "zh" ? "进入 Agent 私聊" : "Open Agent chat")
        : primaryStageAgentRepairPending
          ? (lang === "zh" ? "修复中" : "Repairing")
          : (lang === "zh" ? "修复团队 Agent" : "Repair Team Agents");
  const primaryStageAgentBinding = sourceCollectionStagePrimaryAgentBinding(activeModule.id);
  const primaryStageAgentConfigRoute = primaryStageAgentBinding?.agentId
    ? researchStageAgentManagementRoute(primaryStageAgentBinding.agentId)
    : "/agents";
  const primaryStageAgentConfigLabel = primaryStageAgentBinding?.agent
    ? (lang === "zh" ? "配置 Agent" : "Configure Agent")
    : (lang === "zh" ? "绑定 Agent" : "Bind Agent");
  const sourceCollectionActiveStageCompact =
    activeModule.id === "finding" && sourceCollectionFindingStageCompact;

  const extractionReadiness = sourceCollectionStageActionReadinessFor("extraction");
  const recoveryViewModel = activeModule.id === "extraction" && extractionRecovery
    ? buildExtractionRecoveryViewModel({
      candidateProjection: extractionRecovery.candidateProjection,
      lang,
      sourceCollectionRawRecordCount: extractionRecovery.sourceCollectionRawRecordCount,
      sourceCollectionRunApprovedCount: extractionRecovery.sourceCollectionRunApprovedCount,
      sourceCollectionDisplayedCandidateCount: extractionRecovery.sourceCollectionDisplayedCandidateCount,
      sourceCollectionPrimaryDataLoading: extractionRecovery.sourceCollectionPrimaryDataLoading,
      sourceCollectionLoadingText: extractionRecovery.sourceCollectionLoadingText,
      sourceCollectionCandidateStepState: extractionRecovery.sourceCollectionCandidateStepState,
      sourceCollectionExtractionExcludedRecoveryState: extractionRecovery.sourceCollectionExtractionExcludedRecoveryState,
      sourceCollectionStageActionReadinessDisabled: Boolean(extractionReadiness?.disabled),
      sourceCollectionActionDisabledTitle: (label) => sourceCollectionActionDisabledTitle(extractionReadiness, label),
      sourceCollectionRunPendingScreeningCountText: extractionRecovery.sourceCollectionRunPendingScreeningCountText,
    })
    : null;

  const extractionFlowGuide = activeModule.id === "extraction" && extractionRecovery
    ? buildExtractionStageFlowGuide({
      lang,
      needsAgentMaterial: Boolean(extractionRecovery.needsAgentMaterial || recoveryViewModel),
      pendingScreeningCount: Number(extractionRecovery.pendingScreeningCount || 0),
      approvedCount: Number(extractionRecovery.sourceCollectionRunApprovedCount || 0),
      displayedCandidateCount: Number(extractionRecovery.sourceCollectionDisplayedCandidateCount || 0),
      pendingImportCount: Number(extractionRecovery.pendingImportCount || 0),
      canProceedAfterExclusions: Boolean(extractionRecovery.canProceedAfterExclusions),
      qualityReviewPending: Boolean(extractionRecovery.qualityReviewPending),
      qualityReviewButtonText: extractionRecovery.sourceCollectionScreeningButtonText,
      recoveryPrimaryLabel: recoveryViewModel?.primaryActionText,
      recoveryPrimaryKind: recoveryViewModel?.primaryActionKind,
      recoveryActive: Boolean(recoveryViewModel),
    })
    : null;

  const runExtractionPrimary = () => {
    if (!extractionFlowGuide || !extractionRecovery) {
      activeModule.onAction?.();
      return;
    }
    switch (extractionFlowGuide.recommendedKind) {
      case "quality_review":
        extractionRecovery.runSourceCollectionScreeningAction();
        return;
      case "import":
      case "extract":
        extractionRecovery.runSourceCollectionCandidateExtractionAction();
        return;
      case "advance_relations":
        extractionRecovery.advanceToRelations?.();
        return;
      case "chat":
        openSourceCollectionStageAgentChat("extraction");
        return;
      case "wait":
        return;
      case "supplement":
      default:
        if (recoveryViewModel?.primaryActionKind === "chat") {
          openSourceCollectionStageAgentChat("extraction");
          return;
        }
        if (startSourceCollectionStageSessionTask) {
          startSourceCollectionStageSessionTask("extraction");
        } else {
          activeModule.onAction?.();
        }
    }
  };

  const primaryAction = extractionFlowGuide
    ? {
      tone: "primary" as const,
      disabled: extractionFlowGuide.recommendedKind === "wait"
        || (
          (extractionFlowGuide.recommendedKind === "supplement" || extractionFlowGuide.recommendedKind === "extract")
          && Boolean(extractionReadiness?.disabled)
        )
        || (
          extractionFlowGuide.recommendedKind === "quality_review"
          && Boolean(extractionRecovery?.sourceCollectionScreeningActionReadiness?.disabled)
        )
        || (
          (extractionFlowGuide.recommendedKind === "import")
          && Boolean(extractionRecovery?.sourceCollectionCandidateExtractionActionReadiness?.disabled)
        ),
      onAction: runExtractionPrimary,
      title: extractionFlowGuide.recommendedTitle,
      icon: extractionFlowGuide.recommendedKind === "quality_review"
        ? "check" as const
        : extractionFlowGuide.recommendedKind === "advance_relations"
          ? "play" as const
          : extractionFlowGuide.recommendedKind === "chat"
            ? "check" as const
            : "play" as const,
      label: extractionFlowGuide.recommendedLabel,
    }
    : {
      tone: activeModule.actionTone,
      disabled: activeModule.actionDisabled,
      onAction: activeModule.onAction,
      title: sourceCollectionActionDisabledTitle(sourceCollectionStageActionReadinessFor(activeModule.id), activeModule.actionLabel) || "",
      icon: activeModule.actionIcon,
      label: activeModule.actionLabel,
    };

  const secondaryActions = extractionFlowGuide ? (
    <>
      {extractionFlowGuide.showImportSecondary ? (
        <VNativeButton
          type="button"
          className={styles.sourceCollectionStageSecondaryAction ?? undefined}
          disabled={Boolean(extractionRecovery?.sourceCollectionCandidateExtractionActionReadiness?.disabled)}
          onClick={() => extractionRecovery?.runSourceCollectionCandidateExtractionAction()}
          title={sourceCollectionActionDisabledTitle(
            extractionRecovery?.sourceCollectionCandidateExtractionActionReadiness,
            recoveryViewModel?.importActionText || (lang === "zh" ? "补导入候选" : "Import candidates"),
          ) || (lang === "zh" ? "补导入候选" : "Import candidates")}
        >
          <RefreshCw size={13} />
          {recoveryViewModel?.importActionText || (lang === "zh" ? "补导入候选" : "Import candidates")}
        </VNativeButton>
      ) : null}
      {extractionFlowGuide.showQualityReviewSecondary ? (
        <VNativeButton
          type="button"
          className={styles.sourceCollectionStageSecondaryAction ?? undefined}
          disabled={Boolean(extractionRecovery?.sourceCollectionScreeningActionReadiness?.disabled)}
          onClick={() => extractionRecovery?.runSourceCollectionScreeningAction()}
          title={sourceCollectionActionDisabledTitle(
            extractionRecovery?.sourceCollectionScreeningActionReadiness,
            extractionRecovery?.sourceCollectionScreeningButtonText || recoveryViewModel?.qualityReviewActionText || "",
          )
            || extractionRecovery?.sourceCollectionScreeningButtonTitle
            || recoveryViewModel?.qualityReviewActionTitle
            || (lang === "zh" ? "补完材料后再用" : "Use after materials are repaired")}
        >
          {extractionRecovery?.sourceCollectionScreeningButtonText || recoveryViewModel?.qualityReviewActionText || (lang === "zh" ? "重新质量审查" : "Re-run quality review")}
        </VNativeButton>
      ) : null}
    </>
  ) : null;

  return (
    <TeamSourceCollectionActiveStagePanel
      lang={lang}
      stageId={activeModule.id}
      compact={sourceCollectionActiveStageCompact}
      title={activeModule.label}
      status={recoveryViewModel ? recoveryViewModel.statusLabel : activeModule.status}
      inputLabel={activeModule.inputLabel}
      outputLabel={activeModule.outputLabel}
      nextLabel={activeModule.nextLabel}
      flowSteps={extractionFlowGuide?.steps}
      flowNowHint={extractionFlowGuide?.nowHint}
      flowAfterHint={extractionFlowGuide?.afterHint}
      primaryActionEyebrow={extractionFlowGuide
        ? (lang === "zh" ? "▼ 点这里推进（只需这一个）" : "▼ Click here to proceed (only this)")
        : null}
      primaryActionHint={extractionFlowGuide
        ? (lang === "zh"
          ? `做完后：${extractionFlowGuide.afterHint}`
          : `Then: ${extractionFlowGuide.afterHint}`)
        : null}
      primaryAction={{
        ...primaryAction,
        label: extractionFlowGuide
          ? (lang === "zh"
            ? `推荐：${extractionFlowGuide.recommendedLabel}`
            : `Recommended: ${extractionFlowGuide.recommendedLabel}`)
          : primaryAction.label,
      }}
      secondaryActions={secondaryActions}
      collapseSecondaryActions={Boolean(extractionFlowGuide)}
      agentChatAction={primaryStageAgentChatRoute ? (
        <Link
          to={primaryStageAgentChatRoute}
          title={stageChatLabels[activeModule.id][lang]}
        >
          <MessageSquare size={13} />
          {lang === "zh" ? "进入 Agent 私聊" : "Open Agent chat"}
        </Link>
      ) : (
        <VNativeButton
          type="button"
          title={primaryStageAgentFallbackTitle}
          onClick={() => openSourceCollectionStageAgentChat(activeModule.id)}
          disabled={primaryStageAgentChatLoading || primaryStageAgentChatError || primaryStageAgentRepairPending}
        >
          <MessageSquare size={13} />
          {primaryStageAgentFallbackLabel}
        </VNativeButton>
      )}
      agentConfigAction={(
        <VTooltip content={lang === "zh" ? "当前阶段 Agent 配置" : "Current stage Agent configuration"}>
          <Link to={primaryStageAgentConfigRoute}>
            <Link2 size={13} />
            {primaryStageAgentConfigLabel}
          </Link>
        </VTooltip>
      )}
      errors={(
        <>
          {repairChallengeCupTeamAgentsMutation.error instanceof Error ? (
            <div className={styles.messageError}>{repairChallengeCupTeamAgentsMutation.error.message}</div>
          ) : null}
          {selectedTeamStartSourceCollectionStageTaskError ? (
            <div className={styles.messageError}>{selectedTeamStartSourceCollectionStageTaskError.message}</div>
          ) : null}
          {extractionRecovery?.sourceCollectionQualityBatchFeedback ? (
            <div className={styles.messageResult} role="status">
              {extractionRecovery.sourceCollectionQualityBatchFeedback}
            </div>
          ) : null}
        </>
      )}
      renderConversationPanel={renderSourceCollectionConversation}
      renderScreeningPanel={renderSourceCollectionScreeningPanel}
      renderIntegratedRecovery={activeModule.id === "extraction" && extractionRecovery
        ? () => (
          <TeamSourceCollectionExtractionRecoveryWorkspacePanel
            candidateProjection={extractionRecovery.candidateProjection}
            lang={lang}
            sourceCollectionRawRecordCount={extractionRecovery.sourceCollectionRawRecordCount}
            sourceCollectionRunApprovedCount={extractionRecovery.sourceCollectionRunApprovedCount}
            sourceCollectionDisplayedCandidateCount={extractionRecovery.sourceCollectionDisplayedCandidateCount}
            sourceCollectionPrimaryDataLoading={extractionRecovery.sourceCollectionPrimaryDataLoading}
            sourceCollectionLoadingText={extractionRecovery.sourceCollectionLoadingText}
            sourceCollectionCandidateStepState={extractionRecovery.sourceCollectionCandidateStepState}
            sourceCollectionExtractionExcludedRecoveryState={extractionRecovery.sourceCollectionExtractionExcludedRecoveryState}
            sourceCollectionActionDisabledTitle={sourceCollectionActionDisabledTitle}
            sourceCollectionStageActionReadinessFor={sourceCollectionStageActionReadinessFor}
            openSourceCollectionStageAgentChat={openSourceCollectionStageAgentChat}
            startSourceCollectionStageSessionTask={startSourceCollectionStageSessionTask || (() => undefined)}
            runSourceCollectionCandidateExtractionAction={extractionRecovery.runSourceCollectionCandidateExtractionAction}
            sourceCollectionCandidateExtractionActionReadiness={extractionRecovery.sourceCollectionCandidateExtractionActionReadiness}
            runSourceCollectionScreeningAction={extractionRecovery.runSourceCollectionScreeningAction}
            sourceCollectionScreeningActionReadiness={extractionRecovery.sourceCollectionScreeningActionReadiness}
            sourceCollectionScreeningButtonText={extractionRecovery.sourceCollectionScreeningButtonText}
            sourceCollectionRunPendingScreeningCountText={extractionRecovery.sourceCollectionRunPendingScreeningCountText}
            presentation="stageCard"
            includeChatAction={false}
          />
        )
        : undefined}
      renderGraphPanel={renderSourceCollectionGraphPanel}
      renderMemoryPanel={renderSourceCollectionMemoryPanel}
    />
  );
}
