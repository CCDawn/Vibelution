import { type ReactNode } from "react";

import { WORKBENCH_LAYOUT_IDS } from "../../../../components/layout/workbenchLayoutIds";
import { VButton, VNativeButton, VSplitWorkspace } from "../../../../components/vui";
import type { ExtractionFlowStep } from "../extractionStageFlowGuide";
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
