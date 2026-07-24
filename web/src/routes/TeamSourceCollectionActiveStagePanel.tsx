import { type ReactNode } from "react";

import { VNativeButton } from "../components/vui";
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
  label: ReactNode;
  icon: TeamSourceCollectionStandaloneStageIcon;
  onAction: () => void;
};

type TeamSourceCollectionActiveStagePanelProps = {
  lang: "zh" | "en";
  stageId: TeamSourceCollectionActiveStageId;
  title: ReactNode;
  status: ReactNode;
  inputLabel: ReactNode;
  outputLabel: ReactNode;
  nextLabel: ReactNode;
  primaryAction: TeamSourceCollectionActiveStageAction;
  agentChatAction: ReactNode;
  agentConfigAction: ReactNode;
  errors: ReactNode;
  renderConversationPanel: () => ReactNode;
  compact?: boolean;
  renderCandidatePanel: () => ReactNode;
  renderScreeningPanel: () => ReactNode;
  renderGraphPanel: () => ReactNode;
  renderMemoryPanel: () => ReactNode;
};

export function TeamSourceCollectionActiveStagePanel({
  lang,
  stageId,
  title,
  status,
  inputLabel,
  outputLabel,
  nextLabel,
  primaryAction,
  agentChatAction,
  agentConfigAction,
  errors,
  renderConversationPanel,
  compact = false,
  renderCandidatePanel,
  renderScreeningPanel,
  renderGraphPanel,
  renderMemoryPanel,
}: TeamSourceCollectionActiveStagePanelProps) {
  const resultPanel = stageId === "extraction"
    ? (
        <div className={styles.sourceCollectionExtractionPanels}>
          {renderCandidatePanel()}
          {renderScreeningPanel()}
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

  return (
    <section className={compact ? styles.sourceCollectionStageWorkspaceCompact : styles.sourceCollectionStageWorkspace} aria-label={lang === "zh" ? "当前阶段子页" : "Current stage workspace"}>
      <div className={styles.sourceCollectionStageWorkspaceHeader}>
        <div>
          <strong>{title}</strong>
          <span>{status}</span>
        </div>
        <div className={styles.sourceCollectionStageHandoff}>
          <span><b>{lang === "zh" ? "输入" : "Input"}</b>{inputLabel}</span>
          <span><b>{lang === "zh" ? "输出" : "Output"}</b>{outputLabel}</span>
          <span className={styles.sourceCollectionStageHandoffNext}><b>{lang === "zh" ? "下一步" : "Next"}</b>{nextLabel}</span>
        </div>
        <div className={styles.sourceCollectionStageChatActions}>
          <VNativeButton
            type="button"
            className={primaryAction.tone === "primary" ? styles.sourceCollectionStagePrimaryAction : styles.sourceCollectionStageSecondaryAction}
            disabled={primaryAction.disabled}
            onClick={primaryAction.onAction}
            title={primaryAction.title}
          >
            <TeamSourceCollectionStageActionIcon icon={primaryAction.icon} />
            {primaryAction.label}
          </VNativeButton>
          {agentChatAction}
          {agentConfigAction}
        </div>
      </div>
      <div className={styles.sourceCollectionStageErrors}>{errors}</div>
      <div className={styles.sourceCollectionStageResult}>{resultPanel}</div>
    </section>
  );
}
