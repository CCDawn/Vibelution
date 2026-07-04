import { type ReactNode, type SyntheticEvent } from "react";

import styles from "./TeamSourceCollectionGraphPanel.styles";

export type TeamSourceCollectionGraphPanelStat = {
  key: string;
  label: ReactNode;
  value: ReactNode;
};

type TeamSourceCollectionGraphPanelProps = {
  lang: "zh" | "en";
  className: string;
  open: boolean;
  rangeText: ReactNode;
  filterBar: ReactNode;
  stats: TeamSourceCollectionGraphPanelStat[];
  hasGraph: boolean;
  emptyMessage: ReactNode;
  graphView: ReactNode;
  nodeList: ReactNode;
  pagination: ReactNode;
  errors: ReactNode;
  onToggle: (event: SyntheticEvent<HTMLDetailsElement>) => void;
};

export function TeamSourceCollectionGraphPanel({
  lang,
  className,
  open,
  rangeText,
  filterBar,
  stats,
  hasGraph,
  emptyMessage,
  graphView,
  nodeList,
  pagination,
  errors,
  onToggle,
}: TeamSourceCollectionGraphPanelProps) {
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
          {nodeList}
          {pagination}
        </>
      ) : (
        <div className={styles.empty}>{emptyMessage}</div>
      )}
      {errors}
    </details>
  );
}
