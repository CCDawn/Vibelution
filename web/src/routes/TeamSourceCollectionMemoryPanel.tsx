import { type ReactNode, type SyntheticEvent } from "react";

import styles from "./TeamSourceCollectionMemoryPanel.styles";

export type TeamSourceCollectionMemoryPanelStat = {
  key: string;
  label: ReactNode;
  value: ReactNode;
};

type TeamSourceCollectionMemoryPanelProps = {
  lang: "zh" | "en";
  className: string;
  open: boolean;
  rangeText: ReactNode;
  filterBar: ReactNode;
  stats: TeamSourceCollectionMemoryPanelStat[];
  hasCandidates: boolean;
  emptyMessage: ReactNode;
  pagination: ReactNode;
  statusItems: ReactNode;
  error: ReactNode;
  children: ReactNode;
  onToggle: (event: SyntheticEvent<HTMLDetailsElement>) => void;
};

export function TeamSourceCollectionMemoryPanel({
  lang,
  className,
  open,
  rangeText,
  filterBar,
  stats,
  hasCandidates,
  emptyMessage,
  pagination,
  statusItems,
  error,
  children,
  onToggle,
}: TeamSourceCollectionMemoryPanelProps) {
  return (
    <details
      id="source-collection-memory-panel"
      className={className}
      open={open}
      onToggle={onToggle}
      tabIndex={-1}
    >
      <summary>
        <span>{lang === "zh" ? "入库审核" : "Knowledge ingestion review"}</span>
        <small>{rangeText}</small>
      </summary>
      {filterBar}
      <div className={styles.workflowSourceQualityStats}>
        {stats.map((stat) => (
          <span key={stat.key}>
            {stat.label} <strong>{stat.value}</strong>
          </span>
        ))}
      </div>
      {hasCandidates ? (
        <div
          className={styles.sourceCollectionMemoryListShell}
          role="region"
          tabIndex={0}
          aria-label={lang === "zh" ? "入库审核候选列表，可滚动查看" : "Knowledge ingestion candidates, scroll to review"}
        >
          <div className={styles.workflowCandidateList}>{children}</div>
        </div>
      ) : (
        <div className={styles.empty}>{emptyMessage}</div>
      )}
      {pagination}
      {statusItems ? (
        <div className={styles.workflowIngestionActions}>{statusItems}</div>
      ) : null}
      <div className={styles.workflowIngestionBoundary}>
        <span>{lang === "zh" ? "通过提炼复核" : "reviewed sources"}</span>
        <span>{lang === "zh" ? "写入团队知识库" : "write to Team Knowledge"}</span>
        <span>{lang === "zh" ? "保留来源追溯" : "keep source provenance"}</span>
      </div>
      {error}
    </details>
  );
}
