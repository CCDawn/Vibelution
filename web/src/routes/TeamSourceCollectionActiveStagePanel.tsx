import { type ReactNode } from "react";

import styles from "./TeamSourceCollectionActiveStagePanel.styles";

type TeamSourceCollectionActiveStagePanelProps = {
  lang: "zh" | "en";
  title: ReactNode;
  status: ReactNode;
  inputLabel: ReactNode;
  outputLabel: ReactNode;
  nextLabel: ReactNode;
  primaryAction: ReactNode;
  agentChatAction: ReactNode;
  agentConfigAction: ReactNode;
  errors: ReactNode;
  children: ReactNode;
};

export function TeamSourceCollectionActiveStagePanel({
  lang,
  title,
  status,
  inputLabel,
  outputLabel,
  nextLabel,
  primaryAction,
  agentChatAction,
  agentConfigAction,
  errors,
  children,
}: TeamSourceCollectionActiveStagePanelProps) {
  return (
    <section className={styles.sourceCollectionStageWorkspace} aria-label={lang === "zh" ? "当前阶段子页" : "Current stage workspace"}>
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
          {primaryAction}
          {agentChatAction}
          {agentConfigAction}
        </div>
      </div>
      {errors}
      {children}
    </section>
  );
}
