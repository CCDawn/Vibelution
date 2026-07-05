import { type ReactNode, type SyntheticEvent } from "react";

import panelFrameStyles from "./TeamSourceCollectionPanelFrame.styles";
import styles from "./TeamSourceCollectionGraphPanel.styles";

export type TeamSourceCollectionGraphPanelStat = {
  key: string;
  label: ReactNode;
  value: ReactNode;
};

type TeamSourceCollectionGraphPanelProps = {
  lang: "zh" | "en";
  focused: boolean;
  open: boolean;
  rangeText: ReactNode;
  filterBar: ReactNode;
  stats: TeamSourceCollectionGraphPanelStat[];
  hasGraph: boolean;
  emptyMessage: ReactNode;
  graphView: ReactNode;
  nodeListAriaLabel: string;
  nodeListItems: ReactNode;
  pagination: ReactNode;
  errors: ReactNode;
  onToggle: (event: SyntheticEvent<HTMLDetailsElement>) => void;
};

export function TeamSourceCollectionGraphPanel({
  lang,
  focused,
  open,
  rangeText,
  filterBar,
  stats,
  hasGraph,
  emptyMessage,
  graphView,
  nodeListAriaLabel,
  nodeListItems,
  pagination,
  errors,
  onToggle,
}: TeamSourceCollectionGraphPanelProps) {
  const className = [
    panelFrameStyles.workflowSourceCollectionDetails,
    focused ? panelFrameStyles.sourceCollectionFocusedPanel : "",
  ].filter(Boolean).join(" ");

  return (
    <details
      id="source-collection-graph-panel"
      className={className}
      open={open}
      onToggle={onToggle}
      tabIndex={-1}
    >
      <summary>
        <span>{lang === "zh" ? "入库关系图" : "Ingestion relationship map"}</span>
        <small>{rangeText}</small>
      </summary>
      {filterBar}
      {hasGraph ? (
        <>
          <div className={styles.workflowGraphStats}>
            {stats.map((stat) => (
              <span key={stat.key}>
                {stat.label} <strong>{stat.value}</strong>
              </span>
            ))}
          </div>
          {graphView}
          {nodeListItems ? (
            <div
              className={styles.sourceCollectionGraphNodeListShell}
              role="region"
              tabIndex={0}
              aria-label={nodeListAriaLabel}
            >
              <div className={styles.workflowCandidateList}>{nodeListItems}</div>
            </div>
          ) : null}
          {pagination}
        </>
      ) : (
        <div className={styles.empty}>{emptyMessage}</div>
      )}
      {errors}
    </details>
  );
}
