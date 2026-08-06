/**
 * Source-collection active-stage workspace body.
 * Wave 8M: extracted from TeamsRoute.tsx for domain componentization.
 * Extraction stage merges recovery/verification into the right stage card.
 */
import { useState, type ReactNode } from "react";
import { CircleX, Link2, MessageSquare, RefreshCw, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";

import { VButton, VConfirmDialog, VNativeButton, VTooltip } from "../../../../components/vui";
import { ResearchWorkflowErrorSurface } from "../../ResearchWorkflowErrorSurface";
import { researchStageAgentManagementRoute } from "../../researchStageAgentPresentation";
import { buildExtractionRecoveryViewModel } from "../extractionRecoveryViewModel";
import { buildExtractionStageFlowGuide } from "../extractionStageFlowGuide";
import type { SourceCollectionExtractionRecoveryBag } from "../extractionRecoveryBag";
import {
  pickSourceCollectionPipelineModule,
  type SourceCollectionPipelineGraphHealth,
} from "../stageModulesModel";
import type { SourceCollectionStageModuleId } from "../stageProjection";
import { TeamSourceCollectionActiveStagePanel } from "./TeamSourceCollectionActiveStagePanel";
import { TeamSourceCollectionExtractionRecoveryWorkspacePanel } from "./TeamSourceCollectionExtractionRecoveryWorkspacePanel";
import { TeamSourceCollectionStageActionIcon } from "./TeamSourceCollectionStandaloneStagePanel";
import shellStyles from "../../../TeamsRoute.styles";
import workflowStyles from "../../../TeamsRoute.workflow.styles";

const styles = { ...shellStyles, ...workflowStyles } as Record<string, string>;

type Lang = "zh" | "en";

export type { SourceCollectionExtractionRecoveryBag };

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
  /** Current-stage Agent cards stay visible beside the operational CTA. */
  agentConfiguration?: ReactNode;
  startSourceCollectionStageSessionTask?: (
    stageId: SourceCollectionStageModuleId,
    options?: { formalRetry?: boolean },
  ) => void;
  sourceCollectionRunAvailable: boolean;
  sourceCollectionFindingStageCompact: boolean;
  selectedTeamStartSourceCollectionStageTaskError: Error | null;
  /** Explicit product failure for the fixed advance button (never silent). */
  sourceCollectionStageAdvanceFailure?: string;
  /** Graph health so primary CTA never says "retry ingest" while relations still block. */
  pipelineGraphHealth?: SourceCollectionPipelineGraphHealth | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionConversation: () => ReactNode;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionScreeningPanel: () => ReactNode;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionGraphPanel: () => ReactNode;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  renderSourceCollectionMemoryPanel: () => ReactNode;
  /** Extraction recovery inputs — when set, merge into extraction stage card. */
  extractionRecovery?: SourceCollectionExtractionRecoveryBag;
  /** Project-level source-collection reset (compact buttons under stage card). */
  projectReset?: {
    available: boolean;
    pending: boolean;
    includeDownstream: boolean;
    error: Error | null;
    onReset: (input: { includeDownstream: boolean }) => void;
  } | null;
};

export function TeamSourceCollectionActiveStageWorkspacePanel(props: TeamSourceCollectionActiveStageWorkspacePanelProps) {
  const [excludeUnverifiableConfirmOpen, setExcludeUnverifiableConfirmOpen] = useState(false);
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
    agentConfiguration,
    startSourceCollectionStageSessionTask,
    sourceCollectionRunAvailable,
    sourceCollectionFindingStageCompact,
    selectedTeamStartSourceCollectionStageTaskError,
    sourceCollectionStageAdvanceFailure = "",
    pipelineGraphHealth = null,
    renderSourceCollectionConversation,
    renderSourceCollectionScreeningPanel,
    renderSourceCollectionGraphPanel,
    renderSourceCollectionMemoryPanel,
    extractionRecovery,
    projectReset = null,
  } = props;

  const activeModule =
    sourceCollectionStageModules.find((module: any) => module.id === selectedSourceCollectionStageId)
    ?? sourceCollectionStageModules[0];
  // Fixed right-rail CTA follows pipeline recommendation, not merely the open card.
  // Graph health forces relations while ingestion preflight would fail (e.g. missing links 60).
  const pipelineModule =
    pickSourceCollectionPipelineModule(sourceCollectionStageModules as any[], pipelineGraphHealth)
    ?? activeModule;
  const primaryStageAgentChatState = sourceCollectionStageAgentChatState(activeModule.id);
  const primaryStageAgentChatRoute = primaryStageAgentChatState.route;
  const primaryStageAgentChatLoading = primaryStageAgentChatState.status === "loading";
  const primaryStageAgentChatError = primaryStageAgentChatState.status === "error";
  const primaryStageAgentSessionCreateReady = primaryStageAgentChatState.status === "ready";
  const primaryStageAgentNeedsCollectionStart = primaryStageAgentChatState.status === "blocked"
    && activeModule.id === "finding"
    && !sourceCollectionRunAvailable;
  const primaryStageAgentBlockedByCollectionStart = primaryStageAgentChatState.status === "blocked";
  const primaryStageAgentRepairPending =
    primaryStageAgentChatState.status === "repair" && repairChallengeCupTeamAgentsMutation.isPending;
  const primaryStageAgentFallbackTitle = primaryStageAgentChatLoading
    ? (lang === "zh" ? "正在加载本轮 Agent 会话，请稍候" : "Loading the Agent session for this run")
    : primaryStageAgentChatError
      ? (lang === "zh" ? "Agent 配置加载失败，请刷新后重试" : "Agent configuration failed to load")
      : primaryStageAgentNeedsCollectionStart
        ? (lang === "zh" ? "请先点上方「推荐下一步」开始搜集，再进入 Agent 私聊" : "Use the recommended next step above to start collection first")
        : primaryStageAgentBlockedByCollectionStart
          ? (lang === "zh" ? "请先完成资料发现，再进入该阶段的 Agent 会话" : "Complete source finding before opening this stage's Agent session")
      : primaryStageAgentSessionCreateReady
        ? (lang === "zh" ? "为当前研究项目创建并打开此 Agent 的平级实验会话" : "Create and open this Agent's peer experiment session for the current research project")
        : (lang === "zh" ? "当前步骤缺少可用私聊，请先修复团队 Agent 绑定" : "No usable direct chat for this step");
  const primaryStageAgentFallbackLabel = primaryStageAgentChatLoading
    ? (lang === "zh" ? "加载本轮会话..." : "Loading session...")
    : primaryStageAgentChatError
      ? (lang === "zh" ? "Agent 加载失败" : "Agent load failed")
      : primaryStageAgentNeedsCollectionStart
        ? (lang === "zh" ? "先推进搜集再进入私聊" : "Advance collection first")
        : primaryStageAgentBlockedByCollectionStart
          ? (lang === "zh" ? "请先开始资料搜集" : "Start source collection first")
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

  const pipelineProjectionEarly = (pipelineModule as { projection?: any })?.projection;
  const pipelineLatestTaskEarly = pipelineProjectionEarly?.latestTask;
  const pipelineClosureEarly = pipelineLatestTaskEarly?.closureSummary;
  const pipelineTaskBlocked = Boolean(
    pipelineProjectionEarly?.status === "agent_blocked"
    || pipelineLatestTaskEarly?.status === "blocked"
    || pipelineLatestTaskEarly?.status === "failed"
    || pipelineClosureEarly?.userStatus === "failed"
    || pipelineClosureEarly?.advanceOutcome === "failed"
    || pipelineClosureEarly?.artifactStatus === "no_effect"
  );

  // Extraction micro-guide only owns primary when the pipeline is on extraction.
  const useExtractionGuidePrimary = Boolean(extractionFlowGuide) && pipelineModule.id === "extraction";
  const pipelinePrimaryAction = {
    tone: "primary" as const,
    disabled: Boolean(pipelineModule.actionDisabled),
    onAction: () => {
      // Blocked/failed prior attempt: always formal-retry through the stage starter when available.
      if (
        pipelineTaskBlocked
        && startSourceCollectionStageSessionTask
        && (pipelineModule.id === "finding"
          || pipelineModule.id === "extraction"
          || pipelineModule.id === "relations"
          || pipelineModule.id === "ingestion")
      ) {
        void startSourceCollectionStageSessionTask(pipelineModule.id as SourceCollectionStageModuleId, {
          formalRetry: true,
        });
        return;
      }
      pipelineModule.onAction?.();
    },
    title: sourceCollectionActionDisabledTitle(
      sourceCollectionStageActionReadinessFor(pipelineModule.id),
      pipelineModule.actionLabel,
    ) || String(pipelineModule.actionLabel || ""),
    icon: pipelineModule.actionIcon || ("play" as const),
    // Short CTA only. Retry is a badge; do not stack "系统重试：" into the button label.
    label: pipelineModule.id === "relations" && /推进失败|关系缺口|整理关系|missing graph|relations first/i.test(
      String(sourceCollectionStageAdvanceFailure || ""),
    )
      ? (lang === "zh" ? "继续整理关系" : "Continue mapping")
      : pipelineModule.actionLabel,
    badge: pipelineTaskBlocked
      ? (lang === "zh" ? "系统重试" : "System retry")
      : undefined,
  };

  const primaryAction = useExtractionGuidePrimary
    ? {
      tone: "primary" as const,
      disabled: extractionFlowGuide!.recommendedKind === "wait"
        || (
          (extractionFlowGuide!.recommendedKind === "supplement" || extractionFlowGuide!.recommendedKind === "extract")
          && Boolean(extractionReadiness?.disabled)
        )
        || (
          extractionFlowGuide!.recommendedKind === "quality_review"
          && Boolean(extractionRecovery?.sourceCollectionScreeningActionReadiness?.disabled)
        )
        || (
          (extractionFlowGuide!.recommendedKind === "import")
          && Boolean(extractionRecovery?.sourceCollectionCandidateExtractionActionReadiness?.disabled)
        ),
      onAction: runExtractionPrimary,
      title: extractionFlowGuide!.recommendedTitle,
      icon: extractionFlowGuide!.recommendedKind === "quality_review"
        ? "check" as const
        : extractionFlowGuide!.recommendedKind === "advance_relations"
          ? "play" as const
          : extractionFlowGuide!.recommendedKind === "chat"
            ? "check" as const
            : "play" as const,
      label: extractionFlowGuide!.recommendedLabel,
    }
    : pipelinePrimaryAction;

  const extractionSecondaryActions = extractionFlowGuide && pipelineModule.id === "extraction" ? (
    <>
      {recoveryViewModel?.showExcludeUnverifiableAction
      && Number(extractionRecovery?.unverifiableCandidateCount || 0) > 0
      && extractionRecovery?.excludeUnverifiableCandidates ? (
        <VNativeButton
          type="button"
          className={styles.sourceCollectionStageSecondaryAction ?? undefined}
          disabled={Boolean(extractionRecovery.excludeUnverifiableCandidatesPending)}
          onClick={() => setExcludeUnverifiableConfirmOpen(true)}
          title={recoveryViewModel.excludeUnverifiableActionTitle}
        >
          <CircleX size={13} />
          {recoveryViewModel.excludeUnverifiableActionText}
        </VNativeButton>
      ) : null}
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

  const stageAdvanceSecondary = pipelineModule.secondaryActionLabel && pipelineModule.onSecondaryAction ? (
    <VNativeButton
      type="button"
      className={styles.sourceCollectionStageSecondaryAction ?? undefined}
      disabled={Boolean(pipelineModule.secondaryActionDisabled)}
      onClick={() => pipelineModule.onSecondaryAction?.()}
      title={pipelineModule.secondaryActionLabel}
      data-testid="source-collection-stage-advance-secondary"
    >
      <TeamSourceCollectionStageActionIcon icon={pipelineModule.secondaryActionIcon || "play"} />
      {pipelineModule.secondaryActionLabel}
    </VNativeButton>
  ) : null;

  // When the open card is behind the pipeline (e.g. still on 找资料 while next is 提炼),
  // keep local work (搜索下一批) under 更多操作 — never steal the fixed progress CTA.
  const selectedLocalSecondary =
    activeModule.id !== pipelineModule.id
    && activeModule.actionLabel
    && activeModule.onAction
      ? (
          <VNativeButton
            type="button"
            className={styles.sourceCollectionStageSecondaryAction ?? undefined}
            disabled={Boolean(activeModule.actionDisabled)}
            onClick={() => activeModule.onAction?.()}
            title={String(activeModule.actionLabel)}
            data-testid="source-collection-stage-local-secondary"
          >
            <TeamSourceCollectionStageActionIcon icon={activeModule.actionIcon || "search"} />
            {activeModule.actionLabel}
          </VNativeButton>
        )
      : null;

  const secondaryActions = extractionSecondaryActions || stageAdvanceSecondary || selectedLocalSecondary
    ? (
        <>
          {extractionSecondaryActions}
          {stageAdvanceSecondary}
          {selectedLocalSecondary}
        </>
      )
    : null;

  const pipelineBlockedFailureText = pipelineTaskBlocked
    ? (
        lang === "zh"
          ? `推进失败（不合格）：${
              pipelineClosureEarly?.message
              || pipelineProjectionEarly?.userSummary
              || "上一轮阶段任务没有产生可用产物。"
            }${
              pipelineClosureEarly?.retryInstruction
                ? ` ${pipelineClosureEarly.retryInstruction}`
                : " 请点主按钮系统重试；不要把打开会话当作成功。"
            }`
          : `Advance failed: ${
              pipelineClosureEarly?.message
              || pipelineProjectionEarly?.userSummary
              || "Previous stage task produced no usable artifact."
            }${
              pipelineClosureEarly?.retryInstruction
                ? ` ${pipelineClosureEarly.retryInstruction}`
                : " Use the primary button to system-retry; opening chat is not success."
            }`
      )
    : "";

  const advanceFailureText = sourceCollectionStageAdvanceFailure || pipelineBlockedFailureText;

  const projectResetFooter = projectReset?.available || projectReset?.error ? (
    <>
      {projectReset.available ? (
        <>
          <VButton
            type="button"
            variant="danger"
            density="compact"
            onPress={() => projectReset.onReset({ includeDownstream: false })}
            isDisabled={projectReset.pending}
            icon={<Trash2 size={14} />}
            data-testid="source-collection-reset-sources-only"
          >
            {projectReset.pending && !projectReset.includeDownstream
              ? (lang === "zh" ? "正在清空…" : "Clearing…")
              : (lang === "zh" ? "清空本项目资料并重新开始" : "Clear this project's sources and restart")}
          </VButton>
          <VButton
            type="button"
            variant="danger"
            density="compact"
            onPress={() => projectReset.onReset({ includeDownstream: true })}
            isDisabled={projectReset.pending}
            icon={<Trash2 size={14} />}
            data-testid="source-collection-reset-cascade"
          >
            {projectReset.pending && projectReset.includeDownstream
              ? (lang === "zh" ? "正在清空…" : "Clearing…")
              : (lang === "zh" ? "连同实验与迭代一起清空" : "Clear sources + experiment/iteration")}
          </VButton>
        </>
      ) : null}
      {projectReset.error ? (
        <ResearchWorkflowErrorSurface
          lang={lang}
          message={projectReset.error.message}
          pending={projectReset.pending}
          onRecommendedAction={(action) => {
            if (action !== "reset_progress_cascade" && action !== "reset_source_only") {
              return;
            }
            projectReset.onReset({ includeDownstream: action === "reset_progress_cascade" });
          }}
        />
      ) : null}
    </>
  ) : null;

  return (
    <>
      <TeamSourceCollectionActiveStagePanel
      lang={lang}
      stageId={activeModule.id}
      compact={sourceCollectionActiveStageCompact}
      title={activeModule.label}
      status={recoveryViewModel ? recoveryViewModel.statusLabel : activeModule.status}
      flowSteps={useExtractionGuidePrimary ? extractionFlowGuide?.steps : null}
      primaryAction={{
        ...primaryAction,
        // Keep the button label short — no 推进：/推荐：/系统重试： stacking.
        label: useExtractionGuidePrimary
          ? extractionFlowGuide!.recommendedLabel
          : primaryAction.label,
      }}
      secondaryActions={secondaryActions}
      collapseSecondaryActions
      footer={projectResetFooter}
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
          onClick={() => {
            if (primaryStageAgentNeedsCollectionStart) {
              return;
            }
            openSourceCollectionStageAgentChat(activeModule.id);
          }}
          disabled={
            primaryStageAgentChatLoading
            || primaryStageAgentChatError
            || primaryStageAgentRepairPending
            || primaryStageAgentBlockedByCollectionStart
            || primaryStageAgentNeedsCollectionStart
          }
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
      agentConfiguration={agentConfiguration}
      errors={(
        <>
          {advanceFailureText ? (
            <div
              className={styles.messageError}
              role="alert"
              data-testid="source-collection-stage-advance-failure"
            >
              {advanceFailureText}
            </div>
          ) : null}
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
      <VConfirmDialog
        open={excludeUnverifiableConfirmOpen}
        onOpenChange={setExcludeUnverifiableConfirmOpen}
        tone="danger"
        title={lang === "zh" ? "排除本轮不可核验来源？" : "Exclude unverifiable sources from this run?"}
        description={lang === "zh"
          ? `将把 ${Number(extractionRecovery?.unverifiableCandidateCount || 0)} 条当前无法公开核验的来源标记为“已排除”。不会删除资料，也不会把它们判为通过；标题、DOI、核验失败原因和评审记录都会保留。`
          : `${Number(extractionRecovery?.unverifiableCandidateCount || 0)} source(s) that cannot currently be publicly verified will be marked as excluded. Nothing is deleted or approved; titles, DOIs, verification failures, and assessment history remain.`}
        confirmLabel={lang === "zh" ? "确认排除并继续" : "Exclude and continue"}
        cancelLabel={lang === "zh" ? "取消" : "Cancel"}
        confirmPending={Boolean(extractionRecovery?.excludeUnverifiableCandidatesPending)}
        onConfirm={() => {
          const exclude = extractionRecovery?.excludeUnverifiableCandidates;
          if (!exclude) {
            return;
          }
          void exclude().then(
            () => setExcludeUnverifiableConfirmOpen(false),
            () => undefined,
          );
        }}
      />
    </>
  );
}
