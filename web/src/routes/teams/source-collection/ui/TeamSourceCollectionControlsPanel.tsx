import { forwardRef, type ReactNode } from "react";

import styles from "./TeamSourceCollectionControlsPanel.styles";

type TeamSourceCollectionControlsPanelProps = {
  lang: "zh" | "en";
  activeRunText: ReactNode;
  statusClassName: string;
  statusLabel: ReactNode;
  selectedSourcePanel: ReactNode;
  children: ReactNode;
};

export const TeamSourceCollectionControlsPanel = forwardRef<HTMLElement, TeamSourceCollectionControlsPanelProps>(
  function TeamSourceCollectionControlsPanel(
    { lang, activeRunText, statusClassName, statusLabel, selectedSourcePanel, children },
    ref,
  ) {
    return (
      <section
        id="source-collection-actions"
        ref={ref}
        className={styles.sourceCollectionControlPanel}
        aria-label={lang === "zh" ? "搜索资料控制台" : "Source collection controls"}
      >
        <div className={styles.workflowIngestionHeader}>
          <div>
            <strong>{lang === "zh" ? "步骤侧栏" : "Step side panel"}</strong>
            <span>{activeRunText}</span>
          </div>
          <span className={`${styles.workflowTag} ${statusClassName}`}>{statusLabel}</span>
        </div>
        {selectedSourcePanel}
        {children}
      </section>
    );
  },
);
