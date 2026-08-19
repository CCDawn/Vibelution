import { type ReactNode } from "react";
import { Check, ChevronRight } from "lucide-react";

import { WORKBENCH_LAYOUT_IDS } from "../../../../components/layout/workbenchLayoutIds";
import {
  VButton,
  VMetricChip,
  VNativeButton,
  VSplitWorkspace,
  VStateRow,
  VStatusChip,
  VSurface,
  type VStatusTone,
} from "../../../../components/vui";
import type { ExtractionFlowStep } from "../extractionStageFlowGuide";
import type { SourceCollectionMaterializedKnowledgeIngestion } from "../stageProjection";
import styles from "./TeamSourceCollectionActiveStagePanel.styles";
import {
  TeamSourceCollectionStageActionIcon,
  type TeamSourceCollectionStandaloneStageIcon,
} from "./TeamSourceCollectionStandaloneStagePanel";

type TeamSourceCollectionActiveStageId = "finding" | "extraction" | "relations" | "ingestion";

type TeamSourceCollectionActiveStageAction = {
  tone: "primary" | "secondary";
  disabled: boolean;
  title: string;
  /** Short CTA copy — no "推进：" / "系统重试：" prefixes. */
  label: ReactNode;
  /** Quiet status chip above the CTA (e.g. system retry). */
  badge?: ReactNode;
  icon: TeamSourceCollectionStandaloneStageIcon;
  onAction: () => void;
};

type TeamSourceCollectionActiveStagePanelProps = {
  lang: "zh" | "en";
  stageId: TeamSourceCollectionActiveStageId;
  title: ReactNode;
  status: ReactNode;
  materializedKnowledgeIngestion?: SourceCollectionMaterializedKnowledgeIngestion | null;
  /** Extraction micro-flow step chips when provided. */
  flowSteps?: ExtractionFlowStep[] | null;
  primaryAction: TeamSourceCollectionActiveStageAction;
  /** Extra secondary actions after primary (e.g. 补导入 / 重新复核). */
  secondaryActions?: ReactNode;
  agentChatAction: ReactNode;
  agentConfigAction: ReactNode;
  /** Current-stage Agent cards stay visible beside the operational CTA. */
  agentConfiguration?: ReactNode;
  /** When true, only the hero primary is shown; secondaries/agent live under 更多操作. */
  collapseSecondaryActions?: boolean;
  errors: ReactNode;
  renderConversationPanel: () => ReactNode;
  compact?: boolean;
  renderScreeningPanel: () => ReactNode;
  /**
   * Integrated recovery/verification body for the extraction stage card.
   * When set, metrics+summary live in the right stage header (merged with 提炼 card).
   */
  renderIntegratedRecovery?: () => ReactNode;
  renderGraphPanel: () => ReactNode;
  renderMemoryPanel: () => ReactNode;
  /** Compact actions under the stage card (e.g. project reset buttons only). */
  footer?: ReactNode;
};

const SC_STAGE_RIGHT_PANE = {
  id: "sc-stage",
  defaultWidth: 320,
  minWidth: 260,
  maxWidth: 440,
} as const;

export function TeamSourceCollectionActiveStagePanel({
  lang,
  stageId,
  title,
  status,
  materializedKnowledgeIngestion = null,
  flowSteps = null,
  primaryAction,
  secondaryActions = null,
  agentChatAction,
  agentConfigAction,
  agentConfiguration = null,
  collapseSecondaryActions = false,
  errors,
  renderConversationPanel,
  compact = false,
  renderScreeningPanel,
  renderIntegratedRecovery,
  renderGraphPanel,
  renderMemoryPanel,
  footer = null,
}: TeamSourceCollectionActiveStagePanelProps) {
  const integratedRecovery = stageId === "extraction" && renderIntegratedRecovery
    ? renderIntegratedRecovery()
    : null;
  const hasFlowGuide = Boolean(flowSteps?.length);
  const hasIntegratedRecovery = Boolean(integratedRecovery);

  const resultPanel = stageId === "extraction"
    ? (
        <div className={styles.sourceCollectionExtractionPanels}>
          <div className={styles.sourceCollectionExtractionScrollRegion}>
            {renderScreeningPanel()}
          </div>
        </div>
      )
    : stageId === "relations"
      ? renderGraphPanel()
      : stageId === "ingestion"
        ? (
            <div className={styles.sourceCollectionIngestionPanels}>
              {renderGraphPanel()}
              {renderMemoryPanel()}
            </div>
          )
        : renderConversationPanel();

  const stageAside = (
    <div className={styles.sourceCollectionStageWorkspaceHeader}>
      <div>
        <strong>{title}</strong>
        <span>{status}</span>
      </div>
      {agentConfiguration}
      {stageId === "ingestion" ? (
        <SourceCollectionKnowledgeIngestionStatus
          lang={lang}
          payload={materializedKnowledgeIngestion}
        />
      ) : null}
      {hasFlowGuide ? (
        <div className={styles.sourceCollectionStageFlowGuide} role="region" aria-label={lang === "zh" ? "当前推荐流程" : "Recommended flow"}>
          <ol className={styles.sourceCollectionStageFlowSteps}>
            {flowSteps?.map((step) => (
              <li
                key={step.id}
                className={[
                  styles.sourceCollectionStageFlowStep,
                  step.state === "current" ? styles.sourceCollectionStageFlowStepCurrent : "",
                  step.state === "done" ? styles.sourceCollectionStageFlowStepDone : "",
                ].filter(Boolean).join(" ")}
                aria-current={step.state === "current" ? "step" : undefined}
              >
                {step.state === "done" ? (
                  <>
                    <Check size={11} aria-hidden="true" />
                    <span className="sr-only">{lang === "zh" ? "已完成：" : "Done: "}</span>
                  </>
                ) : null}
                {step.state === "current" ? <ChevronRight size={11} aria-hidden="true" /> : null}
                {step.label}
              </li>
            ))}
          </ol>
        </div>
      ) : null}
      {collapseSecondaryActions || hasFlowGuide ? (
        <div className={styles.sourceCollectionStageNextAction} role="region" aria-label={lang === "zh" ? "推荐下一步操作" : "Recommended next action"}>
          {primaryAction.badge ? (
            <span className={styles.sourceCollectionStageNextActionBadge}>{primaryAction.badge}</span>
          ) : null}
          <VButton
            type="button"
            variant={primaryAction.tone === "primary" ? "primary" : "secondary"}
            className={styles.sourceCollectionStageNextActionButton}
            isDisabled={primaryAction.disabled}
            onPress={primaryAction.onAction}
            title={primaryAction.title}
            icon={<TeamSourceCollectionStageActionIcon icon={primaryAction.icon} />}
          >
            {primaryAction.label}
          </VButton>
        </div>
      ) : (
        <div className={styles.sourceCollectionStageChatActions}>
          <VButton
            type="button"
            variant={primaryAction.tone === "primary" ? "primary" : "secondary"}
            className={primaryAction.tone === "primary" ? styles.sourceCollectionStagePrimaryAction : styles.sourceCollectionStageSecondaryAction}
            isDisabled={primaryAction.disabled}
            onPress={primaryAction.onAction}
            title={primaryAction.title}
            icon={<TeamSourceCollectionStageActionIcon icon={primaryAction.icon} />}
          >
            {primaryAction.label}
          </VButton>
          {secondaryActions}
          {agentChatAction}
          {agentConfigAction}
        </div>
      )}
      {hasIntegratedRecovery ? (
        <div className={styles.sourceCollectionStageIntegratedRecovery}>
          {integratedRecovery}
        </div>
      ) : null}
      {(collapseSecondaryActions || hasFlowGuide) ? (
        <details className={styles.sourceCollectionStageMoreActions}>
          <summary>{lang === "zh" ? "更多操作" : "More"}</summary>
          <div className={styles.sourceCollectionStageMoreActionsBody}>
            {secondaryActions}
            {agentChatAction}
            {agentConfigAction}
          </div>
        </details>
      ) : null}
      <div className={styles.sourceCollectionStageErrors}>{errors}</div>
      {footer ? (
        <div className={styles.sourceCollectionStageProjectReset} data-testid="source-collection-stage-project-reset">
          {footer}
        </div>
      ) : null}
    </div>
  );

  return (
    <section
      className={compact ? styles.sourceCollectionStageWorkspaceCompact : styles.sourceCollectionStageWorkspace}
      aria-label={lang === "zh" ? "当前阶段子页" : "Current stage workspace"}
      data-testid="source-collection-stage-workspace"
    >
      <VSplitWorkspace
        className={styles.sourceCollectionStageWorkspaceSplit}
        data-testid="source-collection-stage-split"
        resize={{
          layoutId: WORKBENCH_LAYOUT_IDS.teamsSourceCollectionStage,
          aside: SC_STAGE_RIGHT_PANE,
        }}
        main={(
          <div className={styles.sourceCollectionStageResultHost}>
            <div className={styles.sourceCollectionStageResult}>{resultPanel}</div>
          </div>
        )}
        aside={(
          <div className={styles.sourceCollectionStageAsideHost} data-vui-region="source-collection-stage-aside">
            {stageAside}
          </div>
        )}
      />
    </section>
  );
}

type SourceCollectionKnowledgeIngestionStatusProps = {
  lang: "zh" | "en";
  payload: SourceCollectionMaterializedKnowledgeIngestion | null | undefined;
};

type SourceCollectionKnowledgeIngestionDisplayState = "pending" | "completed" | "failed";

function SourceCollectionKnowledgeIngestionStatus({
  lang,
  payload,
}: SourceCollectionKnowledgeIngestionStatusProps) {
  if (!payload || Object.keys(payload).length === 0) {
    return null;
  }

  const failedItems = Array.isArray(payload.failed) ? payload.failed : [];
  const failedCount = Number(payload.failedCount || 0);
  const statusText = [
    payload.status,
    payload.sourceReviewStatus,
    payload.knowledgeSubmissionStatus,
    payload.knowledgeReviewStatus,
  ]
    .map((value) => String(value || "").trim().toLowerCase())
    .filter(Boolean);
  const hasFailure = failedCount > 0
    || failedItems.length > 0
    || statusText.some((value) => value === "failed" || value === "error" || value === "blocked" || value.includes("failed"));
  const formalIds = Array.isArray(payload.formalKnowledgeItemIds)
    ? payload.formalKnowledgeItemIds.filter((value): value is string => Boolean(String(value || "").trim())).slice(0, 4)
    : [];
  const formalCount = Number.isFinite(Number(payload.formalKnowledgeItemCount))
    ? Math.max(0, Number(payload.formalKnowledgeItemCount))
    : null;
  const hasFormalSync = formalIds.length > 0 || (formalCount !== null && formalCount > 0);
  const state: SourceCollectionKnowledgeIngestionDisplayState = hasFailure
    ? "failed"
    : payload.status === "completed" && hasFormalSync
      ? "completed"
      : "pending";
  const stateLabel = state === "failed"
    ? (lang === "zh" ? "入库失败" : "Ingestion failed")
    : state === "completed"
      ? (lang === "zh" ? "已正式同步" : "Officially synced")
      : (lang === "zh" ? "等待正式同步" : "Awaiting official sync");
  const stateTone: VStatusTone = state === "failed"
    ? "danger"
    : state === "completed"
      ? "success"
      : "warning";
  const officialId = formalIds.length > 0
    ? `${lang === "zh" ? "正式知识 ID" : "Formal knowledge IDs"}: ${formalIds.join(", ")}`
    : String(payload.createdKnowledgeBaseId || payload.knowledgeBaseId || "").trim()
      ? `${lang === "zh" ? "知识库 ID" : "Knowledge base ID"}: ${String(payload.createdKnowledgeBaseId || payload.knowledgeBaseId).trim()}`
      : "";
  const firstFailure = failedItems.find((item) => item && typeof item === "object") as Record<string, unknown> | undefined;
  const failureReason = String(firstFailure?.error || firstFailure?.reason || "").trim()
    || (lang === "zh" ? "正式知识同步没有完成。" : "Official knowledge sync did not complete.");

  return (
    <VSurface
      as="section"
      tone="row"
      padding="compact"
      className={styles.sourceCollectionKnowledgeIngestionStatus}
      data-testid="source-collection-knowledge-ingestion-status"
      data-ingestion-state={state}
      aria-label={lang === "zh" ? "正式知识入库状态" : "Formal knowledge ingestion status"}
    >
      <div className={styles.sourceCollectionKnowledgeIngestionHeader}>
        <strong>{lang === "zh" ? "正式知识入库" : "Formal knowledge ingestion"}</strong>
        <VStatusChip tone={stateTone}>{stateLabel}</VStatusChip>
      </div>
      <div className={styles.sourceCollectionKnowledgeIngestionMetrics}>
        {formalCount !== null ? (
          <VMetricChip
            label={lang === "zh" ? "正式知识" : "Formal items"}
            value={lang === "zh" ? `${formalCount} 条` : formalCount}
          />
        ) : null}
        {officialId ? (
          <span className={styles.sourceCollectionKnowledgeIngestionId} title={officialId}>
            {officialId}
          </span>
        ) : null}
      </div>
      {state === "failed" ? (
        <VStateRow tone="danger" role="alert" className={styles.sourceCollectionKnowledgeIngestionMessage}>
          {lang === "zh"
            ? `${failureReason} 失败不会计为正式知识；请修复后重试资料入库。`
            : `${failureReason} Failed items are not counted as formal knowledge; fix the issue and retry ingestion.`}
        </VStateRow>
      ) : state === "pending" ? (
        <VStateRow tone="warning" role="status" className={styles.sourceCollectionKnowledgeIngestionMessage}>
          {lang === "zh" ? "当前结果仍在等待审核或正式知识同步。" : "The result is still awaiting review or official knowledge sync."}
        </VStateRow>
      ) : null}
    </VSurface>
  );
}
